#!/usr/bin/env python3
"""Offline preparation of a separate private-overlay Comet v3 fleet. No SSH/firewall writes."""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Ubuntu 22.04 hosts: local, pinned tomli dependency
    import tomli as tomllib
import urllib.error
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
sys.path.insert(0, str(WORKSPACE))
from ecdsa import Ed25519, SigningKey, VerifyingKey
from computechain.blockchain.comet.economics import VERSION, UNIT, MIN_SELF_STAKE, MAX_TOTAL_POWER, EVIDENCE_BLOCKS, EVIDENCE_SECONDS, BLOCK_GAS_LIMIT
from computechain.blockchain.comet.staking import consensus_key, initial_state
from computechain.blockchain.comet.transaction import canonical, valid_address
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private
from computechain.scripts.comet_devnet import read, write, set_toml, operator_lock
from computechain.scripts import comet_checkpoint as anchors

SOURCE_COMMIT = "0880b4d378f347ab16e54ec677ff50d803f37d62"
NGINX = "nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94"
REG_FIELDS = {"format", "chain_id", "inventory_sha256", "name", "node_id", "node_pubkey", "consensus_key", "owner", "consensus_signature", "node_signature"}
RPC_METHODS = ("status", "block", "commit", "validators", "consensus_params", "genesis")


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", value):
        raise ValueError("names/chain ID must be safe lowercase labels (2..40 characters)")
    return value


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def outside_git(path):
    resolved=Path(path).resolve()
    if any((p / ".git").exists() or (p / ".git").is_symlink() for p in (resolved,*resolved.parents)):
        raise ValueError("generated identities/bundles must stay outside Git checkouts")
    return resolved


def private_network(value):
    net = ipaddress.IPv4Network(value, strict=True)
    if not any(net.subnet_of(ipaddress.IPv4Network(n)) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise ValueError("locations must use explicit RFC1918 subnets")
    return net


def inventory(value):
    if not isinstance(value, dict) or set(value) != {"format", "chain_id", "base_port", "locations", "nodes", "readers"} or type(value["format"]) is not int or value["format"] != 1:
        raise ValueError("invalid fleet inventory fields/version; credentials are not inventory")
    label(value["chain_id"])
    locations = value["locations"]
    if not isinstance(locations, dict) or not 3 <= len(locations) <= 16:
        raise ValueError("declare at least three distinct locations")
    nets = {label(name): private_network(subnet) for name, subnet in locations.items()}
    if any(a.overlaps(b) for i,a in enumerate(nets.values()) for b in list(nets.values())[i+1:]):
        raise ValueError("location subnets overlap")
    readers=value["readers"]
    if not isinstance(readers,list) or len(readers)>16 or len(set(readers))!=len(readers):
        raise ValueError("invalid read-only observer addresses")
    for value_ip in readers:
        address=ipaddress.IPv4Address(value_ip)
        if not any(address in net and address not in (net.network_address,net.broadcast_address) for net in nets.values()):
            raise ValueError("observer address must be inside a declared location")
    nodes = value["nodes"]
    if not isinstance(nodes, list) or not 6 <= len(nodes) <= 16:
        raise ValueError("initial fleet needs 6..16 nodes")
    base = value["base_port"]
    if type(base) is not int or not 1024 <= base <= 65535 - 10*len(nodes):
        raise ValueError("invalid fleet port range")
    names, validators, witness_hosts, witness_sites = set(), [], set(), set()
    machines, host_machines = {}, {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"name", "location", "host", "machine", "role", "stake_cpc", "witness"}:
            raise ValueError("invalid node fields")
        if label(node["name"]) in names or node["location"] not in nets:
            raise ValueError("duplicate name or unknown location")
        names.add(node["name"])
        machine=label(node["machine"])
        if machine in machines and machines[machine]!=node["location"]:
            raise ValueError("a physical machine cannot span declared locations")
        if node["host"] in host_machines and host_machines[node["host"]]!=machine:
            raise ValueError("one host address cannot identify different physical machines")
        machines[machine]=node["location"]; host_machines[node["host"]]=machine
        if len(node["name"])>24:
            raise ValueError("node name is too long for its dedicated service user")
        host = ipaddress.IPv4Address(node["host"])
        net = nets[node["location"]]
        if str(host) != node["host"] or host not in net or host in (net.network_address, net.broadcast_address):
            raise ValueError("host is not a usable address in its declared location")
        if node["role"] not in ("validator", "full") or type(node["stake_cpc"]) is not int or type(node["witness"]) is not bool:
            raise ValueError("invalid node role/stake/witness")
        if node["role"] == "validator":
            if not MIN_SELF_STAKE//UNIT <= node["stake_cpc"] <= 100_000:
                raise ValueError("invalid genesis validator stake")
            validators.append(node)
        elif node["stake_cpc"] != 0:
            raise ValueError("full node must have zero genesis power")
        if node["witness"]:
            witness_hosts.add(node["host"])
            witness_sites.add(node["location"])
    if len(validators) < 4 or len({n["location"] for n in validators}) < 3:
        raise ValueError("at least four validators across three locations required")
    if len(witness_hosts) < 2 or len(witness_sites) < 2:
        raise ValueError("checkpoint witnesses need distinct hosts and locations")
    if sum(n["stake_cpc"] for n in validators) > MAX_TOTAL_POWER or sum(n["stake_cpc"]+1000 for n in validators) >= 1_000_000:
        raise ValueError("genesis power/supply overflow")
    return json.loads(json.dumps(value))


def topology(value):
    value = inventory(value)
    powers, hosts, machines = defaultdict(int), defaultdict(int), defaultdict(int)
    total = sum(n["stake_cpc"] for n in value["nodes"])
    for n in value["nodes"]:
        powers[n["location"]] += n["stake_cpc"]
        hosts[n["host"]] += n["stake_cpc"]
        machines[n["machine"]] += n["stake_cpc"]
    def failures(groups):
        return {name:{"lost_power":p,"remaining_power":total-p,"can_finalize":3*(total-p)>2*total} for name,p in groups.items()}
    return {"chain_id":value["chain_id"],"total_power":total,"locations":failures(powers),
        "hosts":failures(hosts),"machines":failures(machines),"all_location_failures_tolerated":all(3*(total-p)>2*total for p in powers.values()),
        "note":"Quorum arithmetic only; actual tunnel paths and failure-domain independence require on-host testing."}


def binary_identity(binary):
    binary = Path(binary).resolve()
    metadata = read(binary.parent.parent / "comet-build.json")
    actual = digest_file(binary)
    if metadata["source_commit"] != SOURCE_COMMIT or metadata["binary_sha256"] != actual:
        raise ValueError("Comet binary does not match the pinned build metadata")
    return actual


def registration_message(record):
    return b"ComputeChain/fleet-registration/v1\0" + canonical({k:v for k,v in record.items() if not k.endswith("signature")})


def init_identity(value, name, home, binary):
    value = inventory(value)
    spec = next((n for n in value["nodes"] if n["name"] == name), None)
    if spec is None:
        raise ValueError("unknown node")
    binary_identity(binary)
    # Fail BEFORE generating keys when the host cannot compute the address hash.
    hashlib.new('ripemd160')
    home = Path(home).absolute()
    if home.exists() or home.is_symlink():
        raise ValueError("identity requires a NEW home; existing keys/data are preserved")
    home=outside_git(home)
    home.mkdir(parents=True, mode=0o700)
    subprocess.run([str(binary),"init","--home",str(home)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for folder in ("config","data"):
        (home / folder).chmod(0o700)
    for filename in ("node_key.json","priv_validator_key.json"):
        (home / "config" / filename).chmod(0o600)
    (home / "data/priv_validator_state.json").chmod(0o600)
    owner = generate_private_key()
    descriptor = os.open(home / "owner-private.hex",os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,"w") as stream:
        stream.write(owner.hex())
    return register_identity(value,name,home,binary)


def register_identity(value,name,home,binary):
    """Finish a failed NEW identity init, preserving all three existing private keys."""
    value=inventory(value)
    if name not in {n['name'] for n in value['nodes']}: raise ValueError('unknown node')
    binary_identity(binary)
    home=outside_git(home)
    if (home/'registration.json').exists() or (home/'registration.json').is_symlink():
        raise ValueError('registration already exists; no overwrite')
    fresh(home)
    owner=bytes.fromhex((home/'owner-private.hex').read_text())
    # Only this node-local init reads its own keys. Nothing private is exported.
    consensus = SigningKey.from_string(base64.b64decode(read(home / "config/priv_validator_key.json")["priv_key"]["value"])[:32],curve=Ed25519)
    transport = SigningKey.from_string(base64.b64decode(read(home / "config/node_key.json")["priv_key"]["value"])[:32],curve=Ed25519)
    node_pub = transport.verifying_key.to_string()
    record = {"format":1,"chain_id":value["chain_id"],"inventory_sha256":hashlib.sha256(canonical(value)).hexdigest(),
        "name":name,"node_id":hashlib.sha256(node_pub).hexdigest()[:40],"node_pubkey":node_pub.hex(),
        "consensus_key":consensus.verifying_key.to_string().hex(),"owner":address_from_pubkey(public_key_from_private(owner))}
    local_identity(home,record)
    message = registration_message(record)
    record.update(consensus_signature=consensus.sign(message).hex(),node_signature=transport.sign(message).hex())
    write(home / "registration.json",record)
    return record


def registrations(value, records):
    value = inventory(value)
    if len(records) != len(value["nodes"]):
        raise ValueError("one public registration per node required")
    result, ids, keys, owners = {}, set(), set(), set()
    inv_hash = hashlib.sha256(canonical(value)).hexdigest()
    for r in records:
        if not isinstance(r,dict) or set(r) != REG_FIELDS or type(r["format"]) is not int or r["format"] != 1:
            raise ValueError("invalid public registration fields")
        if r["chain_id"] != value["chain_id"] or r["inventory_sha256"] != inv_hash or r["name"] not in {n["name"] for n in value["nodes"]}:
            raise ValueError("registration belongs to another node/inventory/chain")
        raw = consensus_key(r["consensus_key"])
        transport = consensus_key(r["node_pubkey"])
        if r["node_id"] != hashlib.sha256(transport).hexdigest()[:40] or not valid_address(r["owner"]):
            raise ValueError("invalid node ID or owner")
        if r["name"] in result or r["node_id"] in ids or r["consensus_key"] in keys or r["owner"] in owners:
            raise ValueError("duplicate node/consensus key/owner; never clone validator keys")
        try:
            message = registration_message(r)
            for public, field in ((raw,"consensus_signature"),(transport,"node_signature")):
                signature = r[field]
                if not isinstance(signature,str) or not re.fullmatch(r"[0-9a-f]{128}",signature) or not VerifyingKey.from_string(public,curve=Ed25519).verify(bytes.fromhex(signature),message):
                    raise ValueError("invalid registration signature")
        except Exception as exc:
            raise ValueError("invalid registration possession proof") from exc
        result[r["name"]] = r
        ids.add(r["node_id"]); keys.add(r["consensus_key"]); owners.add(r["owner"])
    return result


def ports(value, name):
    i = next(i for i,n in enumerate(value["nodes"]) if n["name"] == name)
    base = value["base_port"] + i*10
    return dict(p2p=base,rpc=base+1,abci=base+2,metrics=base+3,gateway=base+4,read_adapter=base+5)


def gateway(value, spec):
    p = ports(value,spec["name"])
    allowed = "\n".join("    allow "+host+";" for host in sorted({n["host"] for n in value["nodes"]}|set(value["readers"])))
    locations = "\n".join(f"    location = /{method} {{ proxy_pass http://127.0.0.1:{p['read_adapter']}; }}" for method in RPC_METHODS)
    return f'''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 128; }}
http {{
  access_log /dev/stdout;
  server_tokens off;
  client_body_temp_path /tmp/body;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  limit_req_zone $binary_remote_addr zone=reads:1m rate=20r/s;
  limit_conn_zone $binary_remote_addr zone=clients:1m;
  client_header_timeout 5s;
  client_body_timeout 5s;
  keepalive_timeout 5s;
  send_timeout 10s;
  client_max_body_size 8k;
  proxy_connect_timeout 2s;
  proxy_read_timeout 10s;
  proxy_send_timeout 5s;
  proxy_buffering off;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $remote_addr;
  server {{
    listen {spec['host']}:{p['gateway']};
    server_name _;
{allowed}
    deny all;
    limit_req zone=reads burst=40 nodelay;
    limit_req_status 429;
    limit_conn clients 8;
    if ($request_method !~ ^(GET|HEAD|POST)$) {{ return 405; }}
    add_header X-Content-Type-Options nosniff always;
{locations}
    location = / {{ proxy_pass http://127.0.0.1:{p['read_adapter']}; }}
    location = /metrics {{ if ($request_method !~ ^(GET|HEAD)$) {{ return 405; }} proxy_pass http://127.0.0.1:{p['metrics']}; }}
    location / {{ return 404; }}
  }}
}}
'''


def compose(spec, lightweight=False):
    return f'''services:
  rpc:
    image: {NGINX}
    network_mode: host
    user: "101:101"
    entrypoint: ["nginx"]
    command: ["-c", "/etc/nginx/nginx.conf", "-g", "daemon off;"]
    volumes: ["./rpc-nginx.conf:/etc/nginx/nginx.conf:ro"]
    read_only: true
    tmpfs: ["/tmp:rw,noexec,nosuid,size=16m,mode=1777"]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    mem_limit: {"64m" if lightweight else "128m"}
    cpus: {"0.10" if lightweight else "0.50"}
    pids_limit: 64
    logging:
      driver: json-file
      options: {{max-size: "10m", max-file: "3"}}
'''


def firewall(value,spec):
    p=ports(value,spec["name"])
    addresses=", ".join(sorted({n["host"] for n in value["nodes"]}))
    readers=", ".join(sorted({n["host"] for n in value["nodes"]}|set(value["readers"])))
    table="cpc_"+spec["name"].replace("-","_")
    return f'''# Review/install explicitly; no flush of existing rules. Not applied by this tool.
table inet {table} {{
  set peers {{ type ipv4_addr; elements = {{ {addresses} }} }}
  set readers {{ type ipv4_addr; elements = {{ {readers} }} }}
  chain input {{
    type filter hook input priority 0; policy accept;
    ip daddr {spec['host']} tcp dport {p['p2p']} ip saddr @peers accept
    ip daddr {spec['host']} tcp dport {p['gateway']} ip saddr @readers accept
    ip daddr {spec['host']} tcp dport {{ {p['p2p']}, {p['gateway']} }} drop
  }}
}}
'''


def home_root(value):
    """Explicit home-contained profile; paths are approved in each bundle manifest."""
    if not isinstance(value,str) or not re.fullmatch(r"/(root|home/[a-z_][a-z0-9_-]*)/computechain-node",value):
        raise ValueError("home root must be /root/computechain-node or /home/USER/computechain-node")
    return value


def units(value,spec,root=None):
    name=spec["name"]; chain=value["chain_id"]
    prefix=f"cpc-{chain}-{name}"
    home=f"/var/lib/computechain/{chain}/{name}"
    app_home=f"/var/lib/computechain-app/{chain}/{name}"
    ops=f"/etc/computechain/{chain}/{name}"
    workspace="/opt/computechain-workspace"
    if root is not None:
        root=home_root(root)
        home=f"{root}/{chain}/nodes/{name}"
        app_home=f"{root}/{chain}/apps/{name}"
        workspace=f"{root}/runtime"
    python=f"{workspace}/.tools/blockchain-venv/bin/python" if root is None else "/usr/bin/python3"
    sandbox="ProtectHome=true\n" if root is None else f"ProtectHome=tmpfs\nBindReadOnlyPaths={workspace}\nBindPaths={home}\nSlice={prefix}.slice\nNice=10\nCPUAccounting=true\nMemoryAccounting=true\n"
    user=f"cpc-{name}"
    p=ports(value,name)
    common=f'''User={user}
WorkingDirectory={workspace}
Environment=PYTHONPATH={workspace}:{workspace}/.deps
Environment=PYTHONDONTWRITEBYTECODE=1
{"" if root is None else "Environment=OPENSSL_CONF="+workspace+"/openssl.cnf"}
UMask=0077
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
{sandbox}ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths={home}
LimitNOFILE=4096
'''
    app_common=common.replace(f"User={user}",f"User=cpa-{name}").replace(f"ReadWritePaths={home}",f"ReadWritePaths={app_home}").replace(f"BindPaths={home}",f"BindPaths={app_home}")
    app=f'''[Unit]
Description=CPC {name} private ABCI application
After=network-online.target
[Service]
{app_common}ExecStart={python} -m computechain.blockchain.comet.node --datadir {app_home} --chain-id {chain} --listen 127.0.0.1:{p['abci']} --snapshot-interval 5
InaccessiblePaths={"-" if root else ""}{home}
MemoryMax={"160M" if root else "512M"}
TasksMax=64
[Install]
WantedBy=multi-user.target
'''
    engine=f'''[Unit]
Description=CPC {name} CometBFT engine
Wants=network-online.target
After=network-online.target {prefix}-app.service
Requires={prefix}-app.service
[Service]
{common}ExecStart={python} -m computechain.scripts.multisite run-engine --home {home} --binary {workspace}/.tools/bin/cometbft
Environment=GOMAXPROCS=2
Environment=GOMEMLIMIT=192MiB
MemoryMax={"256M" if root else "1G"}
TasksMax=128
[Install]
WantedBy=multi-user.target
'''
    rpc=f'''[Unit]
Description=CPC {name} private read-only state-sync RPC gateway
After=docker.service {prefix}-engine.service {prefix}-readrpc.service
Requires=docker.service {prefix}-engine.service {prefix}-readrpc.service
[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory={ops}
ExecStart=/usr/bin/docker compose --project-name {prefix}-rpc --file {ops}/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose --project-name {prefix}-rpc --file {ops}/docker-compose.yml down
TimeoutStartSec=90
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
'''
    adapter=f'''[Unit]
Description=CPC {name} loopback read-only native JSON-RPC adapter
After={prefix}-engine.service
Requires={prefix}-engine.service
[Service]
User=cpa-{name}
WorkingDirectory={workspace}
Environment=PYTHONPATH={workspace}:{workspace}/.deps
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={python} -m computechain.scripts.rpc_read_gateway --listen 127.0.0.1:{p['read_adapter']} --upstream http://127.0.0.1:{p['rpc']}
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
{"ProtectHome=true" if root is None else "ProtectHome=tmpfs"}
{"" if root is None else "BindReadOnlyPaths="+workspace}
{"" if root is None else "Slice="+prefix+".slice"}
InaccessiblePaths={"-" if root else ""}{home}
MemoryMax={"48M" if root else "128M"}
TasksMax=32
[Install]
WantedBy=multi-user.target
'''
    result={prefix+"-app.service":app,prefix+"-engine.service":engine,prefix+"-readrpc.service":adapter,prefix+"-rpc.service":rpc}
    if root is not None:
        result[prefix+".slice"]="[Slice]\nCPUQuota=30%\nMemoryHigh=384M\nMemoryMax=448M\nTasksMax=224\n"
    return result


def assemble(value, records, destination, faucet, binary, home_roots=None):
    value=inventory(value)
    if home_roots is not None:
        if not isinstance(home_roots,dict) or set(home_roots)!={n['name'] for n in value['nodes']}:
            raise ValueError("one approved home root per node required")
        home_roots={name:home_root(root) for name,root in home_roots.items()}
        for host in {n['host'] for n in value['nodes']}:
            if len({home_roots[n['name']] for n in value['nodes'] if n['host']==host})!=1:
                raise ValueError("nodes on one host must share its operator home root")
    regs=registrations(value,records)
    binary_hash=binary_identity(binary)
    if not valid_address(faucet):
        raise ValueError("a controlled PUBLIC faucet address is required, never its key")
    destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("bundle output must be new; no overwrite")
    destination=outside_git(destination)
    with tempfile.TemporaryDirectory(prefix="cpc-genesis-template-") as scratch:
        template=Path(scratch)/"node"
        subprocess.run([str(binary),"init","--home",str(template)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        genesis=read(template / "config/genesis.json")
        original_config=(template / "config/config.toml").read_text()
    genesis.update(chain_id=value["chain_id"],genesis_time=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),initial_height="1",validators=[])
    accounts={}
    bonded=0
    app_validators=[]
    for spec in value["nodes"]:
        if spec["role"]!="validator": continue
        r=regs[spec["name"]]; amount=spec["stake_cpc"]*UNIT
        bonded+=amount
        accounts[r["owner"]]={"balance":1000*UNIT,"nonce":0}
        raw=bytes.fromhex(r["consensus_key"])
        genesis["validators"].append({"address":hashlib.sha256(raw).hexdigest()[:40].upper(),
            "pub_key":{"type":"tendermint/PubKeyEd25519","value":base64.b64encode(raw).decode()},"power":str(spec["stake_cpc"]),"name":spec["name"]})
        app_validators.append({"pub_key":r["consensus_key"],"owner":r["owner"],"self_stake":amount,"commission_bps":1000})
    remainder=1_000_000*UNIT-bonded-sum(a["balance"] for a in accounts.values())
    accounts.setdefault(faucet,{"balance":0,"nonce":0})["balance"]+=remainder
    genesis["app_state"]={"schema":VERSION,"accounts":accounts,"validators":app_validators}
    initial_state(value["chain_id"],genesis["app_state"])
    params=genesis["consensus_params"]
    params["block"].update(max_bytes="2097152",max_gas=str(BLOCK_GAS_LIMIT))
    params["evidence"].update(max_age_num_blocks=str(EVIDENCE_BLOCKS),max_age_duration=str(EVIDENCE_SECONDS*10**9))
    params["version"]["app"]=str(VERSION)
    raw_genesis=canonical(genesis)+b"\n"
    genesis_hash=hashlib.sha256(raw_genesis).hexdigest()
    destination.mkdir(parents=True,mode=0o700)
    write(destination / "inventory.json",value)
    write(destination / "topology.json",topology(value))
    (destination / "genesis.json").write_bytes(raw_genesis)
    for spec in value["nodes"]:
        root=None if home_roots is None else home_roots[spec['name']]
        folder=destination / spec["name"]; folder.mkdir(mode=0o700)
        (folder / "genesis.json").write_bytes(raw_genesis)
        config=folder / "config.toml"; config.write_text(original_config)
        p=ports(value,spec["name"])
        peers=",".join(f"{regs[n['name']]['node_id']}@{n['host']}:{ports(value,n['name'])['p2p']}" for n in value["nodes"] if n["name"]!=spec["name"])
        set_toml(config,"",{"proxy_app":json.dumps(f"127.0.0.1:{p['abci']}"),"abci":'"grpc"',"moniker":json.dumps(spec["name"]),"log_level":'"error"'})
        set_toml(config,"rpc",{"laddr":json.dumps(f"tcp://127.0.0.1:{p['rpc']}"),"unsafe":"false","max_open_connections":"32"})
        set_toml(config,"p2p",{"laddr":json.dumps(f"tcp://{spec['host']}:{p['p2p']}"),"external_address":json.dumps(f"{spec['host']}:{p['p2p']}"),"persistent_peers":json.dumps(peers),"pex":"false","addr_book_strict":"false","allow_duplicate_ip":"true","max_num_inbound_peers":"16","max_num_outbound_peers":"16","persistent_peers_max_dial_period":'"5s"'})
        set_toml(config,"consensus",{"timeout_commit":'"2s"' if root else '"1s"',"timeout_propose":'"3s"',"timeout_prevote":'"1s"',"timeout_precommit":'"1s"'})
        set_toml(config,"instrumentation",{"prometheus":"true","prometheus_listen_addr":json.dumps(f"127.0.0.1:{p['metrics']}")})
        set_toml(config,"statesync",{"enable":"false"})
        artifacts={"rpc-nginx.conf":gateway(value,spec),"docker-compose.yml":compose(spec,root is not None),"firewall.nft":firewall(value,spec),**units(value,spec,root)}
        for filename,content in artifacts.items(): (folder / filename).write_text(content)
        manifest={"format":1,"schema":VERSION,"chain_id":value["chain_id"],"node":spec,"ports":p,
            "application_home":f"/var/lib/computechain-app/{value['chain_id']}/{spec['name']}" if root is None else f"{root}/{value['chain_id']}/apps/{spec['name']}",
            "inventory_sha256":hashlib.sha256(canonical(value)).hexdigest(),"genesis_sha256":genesis_hash,
            "binary_sha256":binary_hash,"source_commit":SOURCE_COMMIT,"registration":regs[spec["name"]],
            "peers":[{**n,"ports":ports(value,n["name"]),"node_id":regs[n["name"]]["node_id"]} for n in value["nodes"] if n["name"]!=spec["name"]],
            "files":{f:digest_file(folder / f) for f in ["config.toml","genesis.json",*artifacts]}}
        if root is not None: manifest['home_root']=root
        write(folder / "node.json",manifest)
    return {"bundle":str(destination),"genesis_sha256":genesis_hash,"nodes":len(value["nodes"]),"private_keys_exported":False,
        "manifest_sha256":{n["name"]:digest_file(destination / n["name"] / "node.json") for n in value["nodes"]},"topology":topology(value)}


def fresh(home,application_home=None):
    home=Path(home)
    if any((home / n).is_symlink() for n in ("config","data","application","config/config.toml","config/genesis.json","data/priv_validator_state.json")):
        raise ValueError("node paths must not be symlinks")
    if any((home / n).exists() or (home / n).is_symlink() for n in ("application/application.sqlite","data/state.db","data/blockstore.db")) or int(read(home / "data/priv_validator_state.json")["height"])!=0:
        raise ValueError("configure/bootstrap requires fresh history; existing keys/state are preserved")
    if application_home is not None:
        path=Path(application_home)
        if path.is_symlink() or (path / "application.sqlite").exists() or (path / "application.sqlite").is_symlink():
            raise ValueError("separate application has existing history; no reset")


def local_identity(home,record):
    home=Path(home)
    for filename,field in (("priv_validator_key.json","consensus_key"),("node_key.json","node_pubkey")):
        path=home / "config" / filename
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("private key files must be non-symlink and mode0600")
        seed=base64.b64decode(read(path)["priv_key"]["value"],validate=True)[:32]
        if SigningKey.from_string(seed,curve=Ed25519).verifying_key.to_string().hex()!=record[field]:
            raise ValueError("local signing/transport key differs from approved registration")
    owner=home / "owner-private.hex"
    if owner.is_symlink() or owner.stat().st_mode & 0o077:
        raise ValueError("owner key must be private and non-symlink")
    if address_from_pubkey(public_key_from_private(bytes.fromhex(owner.read_text())))!=record["owner"]:
        raise ValueError("local owner key differs from approved registration")


def atomic_copy(source,target,mode):
    target=Path(target)
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix=".artifact-",delete=False) as stream:
        temporary=Path(stream.name)
        try:
            stream.write(Path(source).read_bytes()); stream.flush(); os.fsync(stream.fileno())
            temporary.chmod(mode); os.replace(temporary,target)
        finally: temporary.unlink(missing_ok=True)


def configure(home,bundle,manifest_sha256):
    home=Path(home).resolve(); bundle=Path(bundle).resolve()
    if not isinstance(manifest_sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",manifest_sha256) or (bundle / "node.json").is_symlink() or digest_file(bundle / "node.json")!=manifest_sha256:
        raise ValueError("bundle manifest must match the separately approved SHA256")
    with operator_lock(home):
        m=read(bundle / "node.json")
        fresh(home,m["application_home"])
        if read(home / "registration.json")!=m["registration"]:
            raise ValueError("bundle does not match this node's local identity")
        local_identity(home,m["registration"])
        root=m.get('home_root')
        if root is not None:
            root=home_root(root)
            if home != Path(root)/m['chain_id']/'nodes'/m['node']['name'] or m['application_home']!=str(Path(root)/m['chain_id']/'apps'/m['node']['name']):
                raise ValueError("home-contained manifest paths do not match the installed node")
        expected={"config.toml","genesis.json","rpc-nginx.conf","docker-compose.yml","firewall.nft",*units({"chain_id":m["chain_id"],"base_port":m["ports"]["p2p"],"nodes":[m["node"]]},m["node"],root)}
        if set(m["files"])!=expected or any((bundle / f).is_symlink() or digest_file(bundle / f)!=h for f,h in m["files"].items()):
            raise ValueError("bundle artifact identity mismatch")
        if digest_file(bundle / "genesis.json")!=m["genesis_sha256"]:
            raise ValueError("bundle genesis mismatch")
        parsed=tomllib.loads((bundle / "config.toml").read_text())
        p=m["ports"]
        if parsed["proxy_app"]!=f"127.0.0.1:{p['abci']}" or parsed["abci"]!="grpc" or parsed["rpc"]["unsafe"] or parsed["rpc"]["laddr"]!=f"tcp://127.0.0.1:{p['rpc']}" or parsed["statesync"]["enable"]:
            raise ValueError("bundle exposes privileged RPC/ABCI or implicit state sync")
        for filename in m["files"]:
            target=home / "config" / filename if filename in ("config.toml","genesis.json") else home / filename
            if target.is_symlink(): raise ValueError("refuse symlink artifact target")
            atomic_copy(bundle / filename,target,0o644 if filename=="rpc-nginx.conf" else 0o600)
        write(home / "node.json",m)  # readiness marker LAST; partial configuration cannot start
    return {"configured":m["node"]["name"],"genesis_sha256":m["genesis_sha256"],"keys_preserved":True}


def checked_home(home):
    home=Path(home).resolve()
    m=read(home / "node.json")
    label(m["chain_id"]); label(m["node"]["name"])
    if m["source_commit"]!=SOURCE_COMMIT or m["schema"]!=VERSION or read(home / "registration.json")!=m["registration"]:
        raise ValueError("installed manifest/registration mismatch")
    for f,h in m["files"].items():
        if Path(f).name!=f:
            raise ValueError("invalid installed artifact path")
        target=home / "config" / f if f in ("config.toml","genesis.json") else home / f
        if target.is_symlink() or digest_file(target)!=h:
            raise ValueError("installed artifact changed; explicit reviewed reconfiguration required")
    if digest_file(home / "config/genesis.json")!=m["genesis_sha256"]:
        raise ValueError("installed genesis mismatch")
    # Confirm the public registration still matches this home, not another node's copied key.
    local_identity(home,m["registration"])
    return m


def doctor(home,binary):
    home=Path(home).resolve(); m=read(home / "node.json")
    checked_home(home)
    if binary_identity(binary)!=m["binary_sha256"] or digest_file(home / "config/genesis.json")!=m["genesis_sha256"]:
        raise ValueError("local binary/genesis identity mismatch")
    addresses=json.loads(subprocess.check_output(["ip","-j","-4","addr","show"],text=True))
    own=m["node"]["host"]
    if own not in {a["local"] for interface in addresses for a in interface.get("addr_info",[])}:
        raise ValueError("inventory address is not assigned to this host")
    routes=[]
    if 'network_profile' in m:
        from computechain.scripts.fleet_network import peer_addresses
        destinations={host for _,host,_ in peer_addresses(m)}
    else:
        destinations={p['host'] for p in m['peers']}
    for host in sorted(destinations):
        route=json.loads(subprocess.check_output(["ip","-j","-4","route","get",host],text=True))[0]
        if not route.get("dev") or route.get("type") in ("blackhole","unreachable","prohibit"):
            raise ValueError("peer route is unavailable")
        routes.append({"host":host,"interface":route["dev"]})
    clock=subprocess.check_output(["timedatectl","show","-p","NTPSynchronized","--value"],text=True).strip()
    if clock!="yes": raise ValueError("host clock is not synchronized; fix NTP before startup")
    strict_bootstrap=False
    if 'bootstrap_profile' in m:
        from computechain.scripts.bootstrap_protocol import pinned_trust
        from computechain.scripts.signed_checkpoint import verify
        approved=pinned_trust(home,m)
        strict_bootstrap=tomllib.loads((home/'config/config.toml').read_text())['statesync']['enable']
        if not strict_bootstrap and 'bootstrap_completed' not in m:
            raise ValueError('fresh signed-bootstrap follower awaits checkpoint; no implicit full-sync fallback')
        if strict_bootstrap:
            verify(m['checkpoint_attestation'],approved['operator_public_key'],{'schema':VERSION,'chain_id':m['chain_id'],'genesis_sha256':m['genesis_sha256']})
    if "state_sync_anchor" in m and (strict_bootstrap or ('bootstrap_profile' not in m and not (home / "data/blockstore.db").exists())):
        if anchors.validate(m["state_sync_anchor"],{"schema":VERSION,"chain_id":m["chain_id"],"genesis_sha256":m["genesis_sha256"]})<anchors.STARTUP_BUDGET_SECONDS:
            raise ValueError("state-sync checkpoint near expiry before engine startup")
    return {"node":m["node"]["name"],"routes":routes,"clock_synchronized":True,"overlay_path_not_yet_proven":True,
            'p2p_transport':'public-endpoints' if 'network_profile' in m else 'private-overlay'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("RPC redirects are forbidden; use the approved peer endpoint")


def remote_call(peer,method,*,timeout=2,**params):
    if method not in RPC_METHODS:
        raise ValueError("unapproved remote RPC method")
    host=ipaddress.IPv4Address(peer["host"])
    if not any(host in ipaddress.IPv4Network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")):
        raise ValueError("remote RPC requires a literal overlay/LAN address")
    port=peer["ports"]["gateway"]
    if type(port) is not int or not 1024<=port<=65535:
        raise ValueError("invalid remote RPC port")
    url=f"http://{host}:{port}/{method}?"+urllib.parse.urlencode(params)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(url,timeout=timeout) as response:
        raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:
        raise ValueError("remote RPC response exceeds the size limit")
    value=json.loads(raw)
    if value.get("error"):
        raise RuntimeError("remote RPC failed")
    return value["result"]


def checkpoint_context(home,names):
    m=checked_home(home)
    peers=[]
    for name in names:
        peer=next((p for p in m["peers"] if p["name"]==name and p["witness"]),None)
        if peer is None or peer in peers: raise ValueError("choose distinct approved remote witnesses")
        peers.append(peer)
    if len(peers)<2 or len({p["host"] for p in peers})<2 or len({p["location"] for p in peers})<2:
        raise ValueError("remote witnesses need at least two distinct hosts/locations")
    config={"schema":VERSION,"chain_id":m["chain_id"],"genesis_sha256":m["genesis_sha256"],
        "genesis_file":str(Path(home) / "config/genesis.json"),"nodes":peers,
        "expected_node_ids":{i:p["node_id"] for i,p in enumerate(peers)}}
    call=lambda i,method,**params:remote_call(peers[i],method,**params)
    return m,config,call,tuple(range(len(peers)))


def fleet_checkpoint(home,path,names):
    _,config,call,indexes=checkpoint_context(home,names)
    value=anchors.capture(config,call,indexes)
    anchors.export(path,value)
    return value


def bootstrap(home,path,names):
    home=Path(home).resolve()
    with operator_lock(home):
        m,config,call,indexes=checkpoint_context(home,names)
        fresh(home,m["application_home"])
        if m["node"]["role"]!="full":
            raise ValueError("bootstrap is only for a fresh full node; no validator signing-state reset")
        value=anchors.load(path)
        verified=anchors.check_witnesses(value,config,call,indexes)
        peers=[config["nodes"][i] for i in verified["witnesses"]]
        cfg=home / "config/config.toml"
        set_toml(cfg,"statesync",{"enable":"true","rpc_servers":json.dumps(",".join(f"http://{p['host']}:{p['ports']['gateway']}" for p in peers)),
            "trust_height":str(value["height"]),"trust_hash":json.dumps(value["block_hash"]),"trust_period":json.dumps(str(anchors.TRUST_SECONDS)+"s"),
            "discovery_time":'"5s"',"chunk_request_timeout":'"5s"',"chunk_fetchers":"2","max_snapshot_chunks":"64"})
        m["files"]["config.toml"]=digest_file(cfg)
        m["state_sync_anchor"]=value
        write(home / "node.json",m)
        return {"configured":m["node"]["name"],"state_sync_enabled":True,"native_verification_still_required":True,**verified}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=["plan","init-identity","register-identity","assemble","configure","doctor","run-engine","checkpoint","bootstrap"])
    p.add_argument("--inventory",type=Path)
    p.add_argument("--node")
    p.add_argument("--home",type=Path)
    p.add_argument("--registrations",type=Path,nargs="+")
    p.add_argument("--output",type=Path)
    p.add_argument("--bundle",type=Path)
    p.add_argument("--faucet-address")
    p.add_argument("--home-roots",type=Path,help="explicit node-to-home-root map for lightweight home-contained services")
    p.add_argument("--manifest-sha256",help="node manifest hash approved over an authenticated operator channel")
    p.add_argument("--checkpoint",type=Path)
    p.add_argument("--witnesses",nargs="+")
    p.add_argument("--binary",type=Path,default=WORKSPACE / ".tools/bin/cometbft")
    args=p.parse_args()
    def require(*fields):
        if any(getattr(args,f) is None for f in fields): p.error("required: "+", ".join("--"+f.replace("_","-") for f in fields))
    if args.command=="plan":
        require("inventory"); result=topology(read(args.inventory))
    elif args.command in ("init-identity","register-identity"):
        require("inventory","node","home")
        result=(init_identity if args.command=="init-identity" else register_identity)(read(args.inventory),args.node,args.home,args.binary)
    elif args.command=="assemble":
        require("inventory","registrations","output","faucet_address")
        result=assemble(read(args.inventory),[read(f) for f in args.registrations],args.output,args.faucet_address,args.binary,read(args.home_roots) if args.home_roots else None)
    elif args.command=="configure":
        require("home","bundle","manifest_sha256"); result=configure(args.home,args.bundle,args.manifest_sha256)
    elif args.command in ("checkpoint","bootstrap"):
        require("home","checkpoint","witnesses")
        result=fleet_checkpoint(args.home,args.checkpoint,args.witnesses) if args.command=="checkpoint" else bootstrap(args.home,args.checkpoint,args.witnesses)
    else:
        require("home"); result=doctor(args.home,args.binary)
        if args.command=="run-engine":
            m=read(args.home/'node.json')
            if 'bootstrap_profile' in m:
                # Native Go uses system roots and proxy environment. Pin only the
                # approved CA for this process; never mutate host trust/proxies.
                os.environ['SSL_CERT_FILE']=str(args.home.resolve()/'bootstrap-ca.pem')
                os.environ['SSL_CERT_DIR']=str(args.home.resolve()/'empty-trust-directory')
                os.environ['NO_PROXY']='*'; os.environ['no_proxy']='*'
                for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
                    os.environ.pop(key,None)
            os.execv(str(args.binary),[str(args.binary),"start","--home",str(args.home.resolve())])
    print(json.dumps(result,indent=2))


if __name__=="__main__": main()
