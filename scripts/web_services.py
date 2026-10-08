#!/usr/bin/env python3
"""Isolated LAN website/explorer lifecycle; no chain restart or key mounts."""
import argparse
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent


def read(path):
    return json.loads(path.read_text())


def port(value):
    if type(value) is not int or not 1024 <= value <= 65535:
        raise ValueError("web port must be 1024..65535")
    return value


def private_host(value):
    ip = ipaddress.IPv4Address(value)
    if not any(ip in ipaddress.IPv4Network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","127.0.0.0/8")):
        raise ValueError("web UIs require private LAN or loopback IPv4")
    return str(ip)


def settings(root, name, host=None, public_port=None, trusted_proxy=None):
    path = root / name / "settings.json"
    saved = read(path) if path.exists() else {}
    monitor = root / "monitoring/monitoring.env"
    env = dict(line.split("=",1) for line in monitor.read_text().splitlines() if "=" in line) if monitor.exists() else {}
    base = read(root / "network.json")["base_port"] if (root / "network.json").exists() else 28600
    result = {"host": private_host(host or saved.get("host") or env.get("MONITORING_HOST","127.0.0.1")),
        "port": port(public_port if public_port is not None else saved.get("port",4000 if name == "explorer" else 8080)),
        "api_port": port(saved.get("api_port",base+200)), "frontend_port": port(saved.get("frontend_port",base+201))}
    proxy = trusted_proxy or saved.get("trusted_proxy")
    if proxy:
        result["trusted_proxy"] = private_host(proxy)
    return result


def nginx(config, name):
    # Accept HTTPS forwarding only from the configured edge peer, not LAN clients.
    proxy = private_host(config["trusted_proxy"]) if config.get("trusted_proxy") else None
    scheme = f'map "$remote_addr:$http_x_forwarded_proto" $web_scheme {{ default $scheme; "{proxy}:https" https; }}' if proxy else 'map $scheme $web_scheme { default $scheme; }'
    if name == "website":
        locations = f'''root /usr/share/nginx/html;
        index index.html;
        autoindex off;
        disable_symlinks on;
        location = /api/stats {{ proxy_pass http://127.0.0.1:{config["api_port"]}; }}
        location /api/ {{ return 404; }}
        location / {{ try_files $uri $uri/ =404; }}'''
    else:
        locations = f'''location /api/ {{ proxy_pass http://127.0.0.1:{config["api_port"]}; limit_req zone=api burst=30 nodelay; }}
        location / {{ proxy_pass http://127.0.0.1:{config["frontend_port"]}; }}'''
    return f'''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 128; }}
http {{
  {scheme}
  include /etc/nginx/mime.types;
  default_type application/octet-stream;
  access_log /dev/stdout;
  server_tokens off;
  client_body_temp_path /tmp/body;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  keepalive_timeout 10;
  client_header_timeout 5s;
  client_body_timeout 5s;
  send_timeout 10s;
  client_max_body_size 1k;
  proxy_connect_timeout 2s;
  proxy_read_timeout 10s;
  proxy_set_header Host $http_host;
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header X-Forwarded-Proto $web_scheme;
  limit_req_zone $binary_remote_addr zone=api:1m rate=30r/s;
  server {{
    listen {config["host"]}:{config["port"]};
    server_name _;
    absolute_redirect off;
    if ($request_method !~ ^(GET|HEAD)$) {{ return 405; }}
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;
    add_header Cache-Control no-cache always;
    location = /healthz {{ default_type text/plain; return 200 "ok\\n"; }}
    location ~ (^|/)\\. {{ return 404; }}
    {locations}
  }}
}}
'''


def save(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
        name = stream.name
    os.replace(name,path)


def observer_source(root):
    """Persistent public source selection, separate from the old stand lifecycle."""
    directory=root/'explorer'
    path=directory/'observer.json'
    if not path.exists():
        network=read(root/'network.json')
        return {'chain_id':network['chain_id'],'rpc_url':f"http://127.0.0.1:{network['base_port']+1}",
                'index_dir':'index','genesis_file':'source-genesis.json','node_id':'','genesis_sha256':''}
    value=read(path)
    if set(value)!={'format','chain_id','rpc_url','node_id','genesis_sha256','index_dir','genesis_file'} or type(value['format']) is not int or value['format']!=1:
        raise ValueError('invalid saved observer selection')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',value['chain_id']) or not re.fullmatch(r'[0-9a-f]{40}',value['node_id']) or not re.fullmatch(r'[0-9a-f]{64}',value['genesis_sha256']):
        raise ValueError('invalid observer chain/node/genesis identity')
    if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{4,5}',value['rpc_url']) or not 1024<=int(value['rpc_url'].rsplit(':',1)[1])<=65535:
        raise ValueError('observer native RPC must stay literal loopback')
    expected_index='indexes/'+value['chain_id']+'/'+value['genesis_sha256']
    expected_genesis='sources/'+value['genesis_sha256']+'/genesis.json'
    if value['index_dir']!=expected_index or value['genesis_file']!=expected_genesis:
        raise ValueError('observer paths must be isolated by chain/genesis')
    genesis=directory/value['genesis_file']
    if any(p.is_symlink() for p in (path,genesis,*genesis.parents)) or hashlib.sha256(genesis.read_bytes()).hexdigest()!=value['genesis_sha256']:
        raise ValueError('public observer genesis pin changed')
    return value


def select_observer(root,home):
    from computechain.scripts import multisite
    from computechain.scripts import rpc_read_gateway as reads
    home=Path(home).resolve()
    m=multisite.checked_home(home)
    if m['node']['role']!='full':
        raise ValueError('select an approved full node, never mount a validator home')
    upstream=f"http://127.0.0.1:{m['ports']['rpc']}"
    status=reads.read_native(upstream,'status',{})['result']
    if status['node_info']['id']!=m['registration']['node_id'] or status['node_info']['network']!=m['chain_id'] or status['sync_info']['catching_up'] or int(status['sync_info']['earliest_block_height'])!=1:
        raise ValueError('observer requires matching caught-up full history from genesis')
    value={'format':1,'chain_id':m['chain_id'],'rpc_url':upstream,'node_id':m['registration']['node_id'],
           'genesis_sha256':m['genesis_sha256'],
           'index_dir':'indexes/'+m['chain_id']+'/'+m['genesis_sha256'],
           'genesis_file':'sources/'+m['genesis_sha256']+'/genesis.json'}
    raw=(home/'config/genesis.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=value['genesis_sha256']:
        raise ValueError('approved genesis bytes changed')
    directory=root/'explorer'
    directory.mkdir(mode=0o700,exist_ok=True)
    target=directory/value['genesis_file']
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.is_symlink() or target.read_bytes()!=raw:
            raise ValueError('existing public genesis copy differs; no overwrite')
    else:
        with target.open('xb') as stream: stream.write(raw)
        target.chmod(0o644)
    # Only source selection/public genesis change. No database/key copy/reset.
    save(directory/'observer.json',value)
    return observer_source(root)


def compose(root, name, config, *command):
    directory = root / name
    source = observer_source(root)
    env = {**os.environ, "WEB_HOST": config["host"], "WEB_PORT": str(config["port"]),
        "WEB_CONFIG": str(directory / "nginx.conf"), "WEB_SITE": str(directory / "site"), "WEB_INDEX": str(root/'explorer'/source['index_dir']),
        "EXPLORER_API_PORT": str(config["api_port"]), "EXPLORER_FRONTEND_PORT": str(config["frontend_port"]),
        "CPC_CHAIN_ID": source['chain_id'], "CPC_RPC_URL":source['rpc_url'],
        'CPC_EXPECTED_NODE_ID':source['node_id'],'CPC_GENESIS_SHA256':source['genesis_sha256'],
        'WEB_GENESIS':str(root/'explorer'/source['genesis_file']),
        'CPC_GENESIS_FILE':'/config/genesis.json' if source['genesis_sha256'] else ''}
    project = "cpc-"+name+"-"+hashlib.sha256(str(root).encode()).hexdigest()[:10]
    file = WORKSPACE / name / "docker-compose.yml"
    subprocess.run(["docker","compose","--project-name",project,"--file",str(file),*command],env=env,check=True)


def control(root, name, command, host=None, public_port=None, trusted_proxy=None, observer_home=None):
    root = Path(root).resolve()
    if name not in ("website","explorer") or command not in ("up","down","status","logs"):
        raise ValueError("unsupported web service operation")
    if observer_home is not None and (name!='explorer' or command!='up'):
        raise ValueError('observer selection is explicit explorer up only')
    directory = root / name
    if command != "up" and not (directory / "settings.json").exists():
        print(name+" not configured; no containers changed")
        return
    config = settings(root,name,host,public_port,trusted_proxy)
    if command == "up":
        if not (root / "network.json").is_file():
            raise ValueError("start the v3 stand first")
        directory.mkdir(mode=0o700, exist_ok=True)
        if observer_home is not None:
            select_observer(root,observer_home)
        if name == "website":
            explorer = settings(root,"explorer")
            config["api_port"] = explorer["api_port"]
            site = directory / "site"
            site.mkdir(mode=0o755, exist_ok=True)
            for filename in ("index.html","styles.css","app.js"):
                shutil.copyfile(WORKSPACE / "website" / filename, site / filename)
            docs = root / "docs-site/settings.json"
            monitor = root / "monitoring/monitoring.env"
            env = dict(line.split("=",1) for line in monitor.read_text().splitlines() if "=" in line) if monitor.exists() else {}
            links = {"docs": read(docs)["port"] if docs.exists() else 8008,
                "explorer": explorer["port"], "grafana": int(env.get("GRAFANA_PORT",3000))}
            (site / "services.js").write_text("window.COMPUTECHAIN_SERVICES="+json.dumps(links)+";\n")
        else:
            source=observer_source(root)
            index = directory / source['index_dir']
            if any(p.is_symlink() for p in (index,*index.parents)):
                raise ValueError('observer index path must not be a symlink')
            if not index.exists():
                index.mkdir(mode=0o700,parents=True)
                os.chown(index,1000,1000)  # only the newly created public explorer index
            if not source['genesis_sha256'] and not (directory/source['genesis_file']).exists():
                (directory/source['genesis_file']).write_text('{}\n')  # unused legacy placeholder, never keys
        (directory / "nginx.conf").write_text(nginx(config,name))
        save(directory / "settings.json",config)
        compose(root,name,config,"up","-d",*( ["--build"] if name == "explorer" else []),"--wait","--wait-timeout","90")
        # Compose may reuse a container when only bind-mounted config contents changed.
        service = "gateway" if name == "explorer" else "website"
        compose(root,name,config,"exec","-T",service,"nginx","-t")
        compose(root,name,config,"exec","-T",service,"nginx","-s","reload")
        print(name+": http://"+config["host"]+":"+str(config["port"])+"/",flush=True)
    else:
        compose(root,name,config,*{"down":["down"],"status":["ps"],"logs":["logs","--tail","80"]}[command])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service",choices=["website","explorer"])
    parser.add_argument("command",choices=["up","down","status","logs"])
    parser.add_argument("--dir",type=Path,default=WORKSPACE / ".runtime/comet-staking-devnet")
    parser.add_argument("--host")
    parser.add_argument("--port",type=int)
    parser.add_argument("--trusted-proxy",help="private edge peer allowed to forward HTTPS scheme")
    parser.add_argument('--observer-home',type=Path,help='explorer up only: approved caught-up full node; preserve old index and pin a new source')
    args=parser.parse_args()
    # Same operator lock as the parent launcher; direct usage also serialized.
    import sys
    sys.path.insert(0,str(WORKSPACE))
    from computechain.scripts.comet_devnet import operator_lock
    with operator_lock(args.dir):
        control(args.dir,args.service,args.command,args.host,args.port,args.trusted_proxy,args.observer_home)


if __name__ == "__main__":
    main()
