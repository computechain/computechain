#!/usr/bin/env python3
"""Initialize, run and verify a private loopback CometBFT/CPC devnet."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import tempfile
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
sys.path.insert(0, str(WORKSPACE))
from computechain.blockchain.comet.transaction import canonical, sign_transfer, sign_stake, sign_transaction
from computechain.blockchain.comet.economics import VERSION, UNIT, EVIDENCE_BLOCKS, EVIDENCE_SECONDS
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private

CHAIN_ID = "cpc-comet-staking-devnet-1"
COUNT = 6  # four validators, full-sync follower, state-sync follower


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".metadata-", delete=False) as temporary:
        json.dump(value, temporary, indent=2)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        name = temporary.name
    os.replace(name, path)


def rpc(config, index, endpoint, *, timeout=15, **params):
    url = f"http://127.0.0.1:{config['base_port'] + index * 10 + 1}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        value = json.load(response)
    if value.get("error"):
        raise RuntimeError(str(value["error"]))
    return value["result"]


@contextmanager
def transaction_writer(root):
    """Serialize faucet/load writers; keys/nonces must not race across tools."""
    descriptor = os.open(Path(root) / ".transaction-writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("transaction writer busy; stop the existing load generator first") from exc
        yield


@contextmanager
def operator_lock(root):
    """Prevent two CLI invocations from replacing each other's process registry."""
    descriptor = os.open(Path(root) / ".operator.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another devnet control command is running; retry after it finishes") from exc
        yield


def height(config, index):
    return int(rpc(config, index, "status")["sync_info"]["latest_block_height"])


def wait_for(description, predicate, timeout=60):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"timeout: {description}; last={last}")


def set_toml(path, section, changes):
    text = Path(path).read_text()
    if section:
        pattern = rf"(?ms)(^\[{re.escape(section)}\]\s*\n)(.*?)(?=^\[|\Z)"
    else:
        pattern = r"(?ms)(\A)(.*?)(?=^\[|\Z)"
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"missing config section {section}")
    body = match.group(2)
    for key, value in changes.items():
        replacement = key + " = " + value
        body, count = re.subn(rf"(?m)^{re.escape(key)}\s*=.*$", lambda _: replacement, body)
        if not count:
            body += replacement + "\n"
    Path(path).write_text(text[:match.start(2)] + body + text[match.end(2):])


def initialize(root, binary, base):
    if root.exists():
        raise RuntimeError("devnet directory already exists; choose a new --dir; no automatic reset")
    if not binary.is_file():
        raise RuntimeError("CometBFT binary missing; see COMETBFT.md")
    root.parent.mkdir(parents=True, exist_ok=True)
    # Reserve/check every address used by this network before writing node data.
    sockets = []
    try:
        ports = {base + i * 10 + k for i in range(COUNT) for k in range(4)} | {base + 99} | {base + 100 + i * 8 + j for i in range(COUNT) for j in range(COUNT) if i != j}
        for port in ports:
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
    finally:
        for sock in sockets:
            sock.close()
    subprocess.run([str(binary), "testnet", "--v", "4", "--n", "2", "--o", str(root), "--populate-persistent-peers=false", "--initial-height", "1"], check=True, stdout=subprocess.DEVNULL)
    root.chmod(0o700)
    nodes = [root / f"node{i}" for i in range(COUNT)]
    ids = [subprocess.check_output([str(binary), "show-node-id", "--home", str(node)], text=True).strip() for node in nodes]
    private = generate_private_key()
    faucet = address_from_pubkey(public_key_from_private(private))
    recipient = address_from_pubkey(public_key_from_private(generate_private_key()))
    keyfile = root / "faucet-private.hex"
    descriptor = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(private.hex())
    genesis = read(nodes[0] / "config/genesis.json")
    genesis["chain_id"] = CHAIN_ID
    genesis["initial_height"] = "1"
    owners, consensus_keys = [], []
    for i, node in enumerate(nodes):
        owner_key = generate_private_key()
        owners.append(address_from_pubkey(public_key_from_private(owner_key)))
        descriptor = os.open(root / f"owner-{i}.hex", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(owner_key.hex())
        consensus_keys.append(base64.b64decode(read(node / "config/priv_validator_key.json")["pub_key"]["value"]).hex())
    accounts = {faucet: {"balance": 956_000*UNIT, "nonce": 0}}
    accounts.update({owner: {"balance": 1000*UNIT, "nonce": 0} for owner in owners[:4]})
    genesis["app_state"] = {"schema": VERSION, "accounts": accounts, "validators": [
        {"pub_key": consensus_keys[i], "owner": owners[i], "self_stake": 10_000*UNIT, "commission_bps": 1000}
        for i in range(4)]}
    for val in genesis["validators"]:
        val["power"] = "10000"
    genesis["consensus_params"]["block"]["max_bytes"] = "2097152"
    genesis["consensus_params"]["block"]["max_gas"] = "10500000"
    genesis["consensus_params"]["evidence"]["max_age_num_blocks"] = str(EVIDENCE_BLOCKS)
    genesis["consensus_params"]["evidence"]["max_age_duration"] = str(EVIDENCE_SECONDS*10**9)
    genesis["consensus_params"]["version"]["app"] = str(VERSION)
    for i, node in enumerate(nodes):
        write(node / "config/genesis.json", genesis)
        for name in ("node_key.json", "priv_validator_key.json"):
            (node / "config" / name).chmod(0o600)
        peers = ",".join(f"{ids[j]}@127.0.0.1:{base + 100 + i * 8 + j}" for j in range(COUNT) if j != i)
        config = node / "config/config.toml"
        set_toml(config, "", {"proxy_app": json.dumps(f"127.0.0.1:{base + i * 10 + 2}"), "abci": '"grpc"', "log_level": '"error"', "moniker": json.dumps(f"cpc-node-{i}")})
        set_toml(config, "rpc", {"laddr": json.dumps(f"tcp://127.0.0.1:{base + i * 10 + 1}"), "unsafe": "false"})
        set_toml(config, "p2p", {"laddr": json.dumps(f"tcp://127.0.0.1:{base + i * 10}"), "persistent_peers": json.dumps(peers),
                                "addr_book_strict": "false", "allow_duplicate_ip": "true", "pex": "false", "persistent_peers_max_dial_period": '"1s"'})
        set_toml(config, "consensus", {"timeout_commit": '"500ms"', "timeout_propose": '"1s"', "timeout_prevote": '"500ms"', "timeout_precommit": '"500ms"'})
        set_toml(config, "instrumentation", {"prometheus": "true", "prometheus_listen_addr": json.dumps(f"127.0.0.1:{base + i * 10 + 3}")})
        set_toml(config, "statesync", {"enable": "false"})
    config = {"schema": VERSION, "owners": owners, "consensus_keys": consensus_keys,
              "chain_id": CHAIN_ID, "base_port": base, "binary": str(binary), "nodes": [str(n) for n in nodes],
              "faucet": faucet, "recipient": recipient, "genesis_sha256": hashlib.sha256((nodes[0] / "config/genesis.json").read_bytes()).hexdigest()}
    write(root / "network.json", config)
    write(root / "processes.json", {})
    print(f"Initialized isolated devnet at {root}; no legacy data used.", flush=True)


class Network:
    def __init__(self, root):
        self.root = root.resolve()
        self.config = read(root / "network.json")
        self.registry_path = root / "processes.json"

    def spawn(self, name, args):
        registry = read(self.registry_path)
        if name in registry and self.owned(registry[name]):
            raise RuntimeError(f"process already running: {name}")
        with (self.root / f"{name}.log").open("ab") as log:
            env = {**os.environ, "PYTHONPATH": str(WORKSPACE), "PYTHONHASHSEED": "0"}
            proc = subprocess.Popen(args, cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        registry[name] = {"pid": proc.pid, "args": args, "root": str(self.root)}
        write(self.registry_path, registry)
        return proc

    @staticmethod
    def owned(entry):
        try:
            cmd = Path(f"/proc/{entry['pid']}/cmdline").read_bytes().split(b"\0")
            actual = [a.decode() for a in cmd if a]
            # PIDs are revalidated before signalling: never kill a reused/unrelated PID.
            return actual == entry["args"]
        except (OSError, UnicodeError):
            return False

    def stop(self, name, timeout=8):
        registry = read(self.registry_path)
        entry = registry.get(name)
        if entry and self.owned(entry):
            os.kill(entry["pid"], signal.SIGCONT)  # paused test processes must receive termination.
            os.kill(entry["pid"], signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while self.owned(entry) and time.monotonic() < deadline:
                time.sleep(0.05)
            if self.owned(entry):
                os.kill(entry["pid"], signal.SIGKILL)
        registry.pop(name, None)
        write(self.registry_path, registry)

    def start_proxy(self):
        self.spawn("proxy", [sys.executable, str(REPO / "scripts/comet_proxy.py"), "--network", str(self.root / "network.json")])
        wait_for("link proxy startup", lambda: self.partition(None), 10)

    def start_node(self, i):
        if self.config.get("schema") != VERSION:
            raise RuntimeError("old devnet schema; choose a fresh v3 directory, no automatic migration")
        node = Path(self.config["nodes"][i])
        self.spawn(f"app{i}", [sys.executable, "-m", "computechain.blockchain.comet.node", "--datadir", str(node / "application"),
                   "--chain-id", self.config["chain_id"], "--listen", f"127.0.0.1:{self.config['base_port'] + i * 10 + 2}", "--snapshot-interval", "5"])
        def app_ready():
            with socket.create_connection(("127.0.0.1", self.config["base_port"] + i * 10 + 2), timeout=1):
                return True
        wait_for("ABCI startup", app_ready, 10)
        engine = self.spawn(f"engine{i}", [self.config["binary"], "start", "--home", str(node)])
        def engine_ready():
            if engine.poll() is not None:
                raise RuntimeError(f"engine {i} exited: " + (self.root / f"engine{i}.log").read_text(errors="replace")[-2000:])
            return rpc(self.config, i, "status")
        wait_for(f"node {i} RPC startup", engine_ready, 30)

    def stop_node(self, i):
        self.stop(f"engine{i}")
        self.stop(f"app{i}")

    def down(self):
        self.stop("load", timeout=40)
        self.stop("exporter")
        for i in range(COUNT):
            self.stop_node(i)
        self.stop("proxy")

    def partition(self, groups):
        req = urllib.request.Request(f"http://127.0.0.1:{self.config['base_port'] + 99}/", data=canonical({"groups": groups}), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)["ok"]

    def agree(self, indexes, at_height):
        ids = [rpc(self.config, i, "block", height=at_height)["block_id"]["hash"] for i in indexes]
        roots = [rpc(self.config, i, "block", height=at_height + 1)["block"]["header"]["app_hash"] for i in indexes]
        if len(set(ids)) != 1 or len(set(roots)) != 1:
            raise RuntimeError("conflicting block hashes or application commitments")
        return {"height": at_height, "block_hash": ids[0], "app_hash": roots[0], "nodes": indexes}

    def state(self, i):
        value = rpc(self.config, i, "abci_query", path=json.dumps("/state"))["response"]
        if int(value.get("code", 0)):
            raise RuntimeError(str(value))
        return json.loads(base64.b64decode(value["value"]))

    def validator_powers(self, h):
        vals = rpc(self.config, 0, "validators", height=h, per_page=100)["validators"]
        return {base64.b64decode(v["pub_key"]["value"]).hex(): int(v["voting_power"]) for v in vals}

    def transfer(self, amount):
        with transaction_writer(self.root):
            return self._transfer(amount)

    def _transfer(self, amount):
        state = self.state(0)
        raw = sign_transfer(bytes.fromhex((self.root / "faucet-private.hex").read_text()), self.config["chain_id"],
                            self.config["recipient"], amount, state["accounts"][self.config["faucet"]]["nonce"])
        return self.submit(raw, amount)

    def submit(self, raw, amount):
        result = rpc(self.config, 0, "broadcast_tx_commit", tx="0x" + raw.hex())
        if int(result["check_tx"].get("code", 0)) or int(result.get("tx_result", result.get("deliver_tx", {})).get("code", 0)):
            raise RuntimeError(str(result))
        return {"hash": result["hash"], "height": result["height"], "amount": amount}

    def staking(self, kind, index, amount, commission=1000):
        if self.config.get("schema") != VERSION or not 0 <= index < COUNT:
            raise ValueError("v3 network and validator index 0..5 required")
        with transaction_writer(self.root):
            state = self.state(0)
            owner_operation = kind in ("STAKE", "UNSTAKE", "UPDATE_VALIDATOR")
            owner = self.config["owners"][index] if owner_operation else self.config["faucet"]
            keypath = self.root / (f"owner-{index}.hex" if owner_operation else "faucet-private.hex")
            private = bytes.fromhex(keypath.read_text())
            nonce = state["accounts"].get(owner, {"nonce": 0})["nonce"]
            if kind == "STAKE":
                # Local stand funding only, never a user's personal wallet.
                balance = state["accounts"].get(owner, {"balance": 0})["balance"]
                if balance < amount + UNIT:
                    faucet = bytes.fromhex((self.root / "faucet-private.hex").read_text())
                    self.submit(sign_transfer(faucet, self.config["chain_id"], owner, amount+UNIT-balance,
                        state["accounts"][self.config["faucet"]]["nonce"]), amount+UNIT-balance)
                seed = base64.b64decode(read(Path(self.config["nodes"][index]) / "config/priv_validator_key.json")["priv_key"]["value"])[:32]
                raw = sign_stake(private, self.config["chain_id"], seed, amount, nonce, commission)
            else:
                payload = {"validator": self.config["consensus_keys"][index]}
                if kind == "UPDATE_VALIDATOR":
                    payload["commission_bps"] = commission
                    amount = 0
                raw = sign_transaction(private, self.config["chain_id"], kind, amount, nonce, payload=payload)
            return self.submit(raw, amount)

    def state_sync(self, i):
        checkpoint = max(1, height(self.config, 0) - 3)
        digest = rpc(self.config, 0, "block", height=checkpoint)["block_id"]["hash"]
        config = Path(self.config["nodes"][i]) / "config/config.toml"
        set_toml(config, "statesync", {"enable": "true", "rpc_servers": json.dumps(",".join(f"http://127.0.0.1:{self.config['base_port'] + j * 10 + 1}" for j in (0, 1))),
                  "trust_height": str(checkpoint), "trust_hash": json.dumps(digest), "trust_period": '"30s"', "discovery_time": '"5s"',
                  "chunk_request_timeout": '"5s"', "chunk_fetchers": "2", "max_snapshot_chunks": "64"})
        self.start_node(i)
        target = height(self.config, 0)
        wait_for("verified state sync", lambda: height(self.config, i) >= target, 90)
        # Actual restore log is mandatory; do not pass if it silently used full block sync.
        def restored():
            return "Snapshot restored" in (self.root / f"engine{i}.log").read_text(errors="replace")
        return {"trusted_height": checkpoint, "trusted_hash": digest, "target_height": target, "snapshot_restored": restored()}

    def verify(self):
        report = {"chain_id": self.config["chain_id"], "genesis_sha256": self.config["genesis_sha256"], "scenarios": {}}
        scenarios = report["scenarios"]
        def record(name, value):
            scenarios[name] = value
            write(self.root / "verification.json", report)
            print(name + ": " + json.dumps(value), flush=True)
        try:
            self.start_proxy()
            for i in range(4):
                self.start_node(i)
            wait_for("four validators producing", lambda: min(height(self.config, i) for i in range(4)) >= 12, 60)
            baseline = min(height(self.config, i) for i in range(4)) - 1
            record("four_validator_finality", self.agree(list(range(4)), baseline))
            record("signed_cpc_transfer", self.transfer(10**18))
            print("Starting new full-sync node", flush=True)
            self.start_node(4)
            wait_for("full node catching up", lambda: height(self.config, 4) >= baseline + 2, 60)
            record("new_node_full_sync", self.agree(list(range(5)), baseline))
            offline_height = height(self.config, 4)
            self.stop_node(4)
            wait_for("chain advancing while follower offline", lambda: height(self.config, 0) >= offline_height + 8, 30)
            self.start_node(4)
            wait_for("restarted follower catch-up", lambda: height(self.config, 4) >= offline_height + 8, 60)
            record("offline_restart_catchup", self.agree(list(range(5)), offline_height + 5))
            self.stop_node(3)
            quorum_height = height(self.config, 0)
            wait_for("3/4 voting power progress", lambda: min(height(self.config, i) for i in range(3)) >= quorum_height + 4, 30)
            record("one_validator_offline", {"from": quorum_height, "to": height(self.config, 0)})
            self.start_node(3)
            wait_for("validator rejoining", lambda: height(self.config, 3) >= quorum_height + 4, 60)
            self.partition([[0, 1, 4], [2, 3, 5]])
            time.sleep(2)  # settle in-flight proposals/votes before measuring the split.
            split_heights = [height(self.config, i) for i in range(4)]
            time.sleep(5)
            after = [height(self.config, i) for i in range(4)]
            if after != split_heights:
                raise RuntimeError(f"finalization advanced in 2+2 partition: {split_heights} -> {after}")
            record("two_by_two_partition", {"before": split_heights, "after": after, "both_halves_stopped": True})
            self.partition(None)
            wait_for("recovery after healing partition", lambda: min(height(self.config, i) for i in range(5)) >= max(after) + 3, 60)
            record("partition_healed", self.agree(list(range(5)), max(after) + 1))
            joined = self.staking("STAKE", 4, 6000*UNIT)
            activation = int(joined["height"])+2
            wait_for("first dynamic validator activation", lambda: min(height(self.config, j) for j in range(5)) >= activation+1, 30)
            key = self.config["consensus_keys"][4]
            if key in self.validator_powers(activation-1) or self.validator_powers(activation).get(key) != 6000:
                raise RuntimeError("wrong native validator activation height/power")
            record("validator_4_joined_h_plus_two", {**joined, "activation_height": activation})
            record("pre_snapshot_delegation", self.staking("DELEGATE", 4, 100*UNIT))
            record("pre_snapshot_undelegation", self.staking("UNDELEGATE", 4, 100*UNIT))
            print("Starting fresh state-sync node with trusted checkpoint", flush=True)
            # Enable info logging only for the restoring node so we can prove the restore path.
            set_toml(Path(self.config["nodes"][5]) / "config/config.toml", "", {"log_level": '"info"'})
            restored = self.state_sync(5)
            if not restored["snapshot_restored"]:
                raise RuntimeError("state sync did not restore a snapshot")
            record("verified_snapshot_state_sync", restored)
            if not self.state(5)["unbondings"] or len(self.state(5)["engine_powers"]) != 5:
                raise RuntimeError("state sync did not restore stake/withdrawal liabilities")
            record("snapshot_restored_staking_liabilities", {"unbondings": len(self.state(5)["unbondings"]), "scheduled_validators": 5})
            target = height(self.config, 5) - 1
            wait_for("all nodes at verification height", lambda: min(height(self.config, i) for i in range(6)) >= target + 1, 30)
            record("six_node_agreement", self.agree(list(range(6)), target))
            expected = 10**18
            balances = [self.state(i)["accounts"].get(self.config["recipient"], {}).get("balance", 0) for i in range(6)]
            if balances != [expected] * 6:
                raise RuntimeError(f"recipient balances differ: {balances}")
            record("same_cpc_balance", {"recipient": self.config["recipient"], "balances": balances})
            for i in (5,):
                joined = self.staking("STAKE", i, 6000*UNIT)
                activation = int(joined["height"])+2
                wait_for("validator activation", lambda: min(height(self.config, j) for j in range(6)) >= activation+1, 30)
                key = self.config["consensus_keys"][i]
                if key in self.validator_powers(activation-1) or self.validator_powers(activation).get(key) != 6000:
                    raise RuntimeError("wrong native validator activation height/power")
                record(f"validator_{i}_joined_h_plus_two", {**joined, "activation_height": activation})
            record("delegation", self.staking("DELEGATE", 0, 100*UNIT))
            record("undelegation", self.staking("UNDELEGATE", 0, 100*UNIT))
            exited = self.staking("UNSTAKE", 4, 6000*UNIT)
            activation = int(exited["height"])+2
            wait_for("native validator exit", lambda: height(self.config, 0) >= activation+1, 30)
            if self.config["consensus_keys"][4] in self.validator_powers(activation):
                raise RuntimeError("native validator removal missing")
            record("validator_exit", {**exited, "activation_height": activation})
            self.stop_node(5)
            before = height(self.config, 0)
            wait_for("dynamic set progress with one validator offline", lambda: height(self.config, 0) >= before+4, 30)
            self.start_node(5)
            wait_for("dynamic validator catch-up", lambda: height(self.config, 5) >= before+4, 60)
            record("dynamic_validator_offline_restart", self.agree(list(range(6)), before+2))
            self.partition([[0, 1, 4], [2, 3, 5]])
            time.sleep(2)
            before = [height(self.config, i) for i in range(6)]
            time.sleep(5)
            after = [height(self.config, i) for i in range(6)]
            if before != after:
                raise RuntimeError("dynamic partition finalized without quorum")
            record("dynamic_power_partition_halt", {"before": before, "after": after, "power_split": [20000, 26000]})
            self.partition(None)
            wait_for("dynamic partition healed", lambda: min(height(self.config, i) for i in range(6)) >= max(after)+3, 60)
            record("dynamic_partition_healed", self.agree(list(range(6)), max(after)+1))
            wait_for("both unbond gates and liquid release", lambda: not self.state(0)["unbondings"], 150)
            target = height(self.config, 0)-1
            wait_for("post-staking agreement", lambda: min(height(self.config, i) for i in range(6)) >= target+1, 30)
            record("unbonded_six_node_agreement", self.agree(list(range(6)), target))
            owner = self.config["owners"][4]
            if self.state(0)["accounts"][owner]["balance"] < 6000*UNIT:
                raise RuntimeError("unbond did not return principal")
            report["passed"] = True
        except Exception as exc:
            report["passed"] = False
            report["error"] = str(exc)
            raise
        finally:
            self.down()
            report["processes_stopped"] = not read(self.registry_path)
            write(self.root / "verification.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "up", "down", "status", "transfer", "verify", "stake", "unstake", "delegate", "undelegate", "update-validator"])
    parser.add_argument("--dir", type=Path, default=WORKSPACE / ".runtime/comet-staking-devnet")
    parser.add_argument("--binary", type=Path, default=WORKSPACE / ".tools/bin/cometbft")
    parser.add_argument("--base-port", type=int, default=28600)
    parser.add_argument("--amount", type=int, default=10**18)
    parser.add_argument("--validator-node", type=int, choices=range(COUNT), default=4)
    parser.add_argument("--commission-bps", type=int, default=1000)
    args = parser.parse_args()
    root = args.dir.resolve()
    if args.command == "init":
        initialize(root, args.binary.resolve(), args.base_port)
        return
    if args.command == "verify" and not root.exists():
        initialize(root, args.binary.resolve(), args.base_port)
    net = Network(root)
    if args.command == "up":
        if any(net.owned(entry) for entry in read(net.registry_path).values()):
            raise RuntimeError("devnet already running; existing processes preserved")
        try:
            net.start_proxy()
            for i in range(5):
                net.start_node(i)
        except Exception:
            net.down()
            raise
    elif args.command == "down":
        net.down()
    elif args.command == "verify":
        if any(net.owned(entry) for entry in read(net.registry_path).values()):
            raise RuntimeError("verification needs stopped nodes")
        if any((Path(n) / "application/application.sqlite").exists() for n in net.config["nodes"]):
            raise RuntimeError("verification needs a new --dir; existing state is preserved")
        net.verify()
    elif args.command == "transfer":
        print(json.dumps(net.transfer(args.amount)))
    elif args.command in ("stake", "unstake", "delegate", "undelegate", "update-validator"):
        print(json.dumps(net.staking(args.command.upper().replace("-", "_"), args.validator_node, args.amount, args.commission_bps)))
    else:
        for i in range(COUNT):
            try:
                result = rpc(net.config, i, "status")["sync_info"]
                print(f"node{i}: height={result['latest_block_height']} catching_up={result['catching_up']}")
            except (OSError, RuntimeError):
                print(f"node{i}: stopped")


if __name__ == "__main__":
    main()
