#!/usr/bin/env python3
"""One local operator entrypoint for Comet nodes, metrics and signed load."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent))
from computechain.scripts.comet_devnet import Network, initialize, read, height, wait_for, rpc, operator_lock
from contextlib import nullcontext
from computechain.scripts.comet_load import MODES


def ports(root, args):
    saved = {}
    path = root / "monitoring/monitoring.env"
    if path.exists():
        saved = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return (args.prometheus_port or int(saved.get("PROMETHEUS_PORT", 9090)),
            args.grafana_port or int(saved.get("GRAFANA_PORT", 3000)))


def monitoring_host(root, args):
    path = root / "monitoring/monitoring.env"
    saved = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    return args.monitoring_host or saved.get("MONITORING_HOST", "127.0.0.1")


def monitoring(net, args, command):
    script = REPO.parent / "monitoring/stack.py"
    if not script.is_file():
        raise RuntimeError("clone the computechain/monitoring repository beside this repository, or use --no-monitoring")
    if command == "up":
        entry = read(net.registry_path).get("exporter")
        if not entry or not net.owned(entry):
            net.spawn("exporter", [sys.executable, str(script.parent / "exporter.py"), "--network", str(net.root / "network.json"),
                                   "--port", str(net.config["base_port"] + 4)])
        def ready():
            with urllib.request.urlopen(f"http://127.0.0.1:{net.config['base_port'] + 4}/health", timeout=2) as response:
                return response.status == 200
        wait_for("metrics exporter", ready, 15)
    prometheus, grafana = ports(net.root, args)
    options = ["--monitoring-host", args.monitoring_host] if args.monitoring_host else []
    subprocess.run([sys.executable, str(script), command, "--dir", str(net.root),
                    "--prometheus-port", str(prometheus), "--grafana-port", str(grafana), *options], check=True)
    if command == "down":
        net.stop("exporter")


def up(net):
    registry = read(net.registry_path)
    expected = ["proxy"] + [name + str(i) for i in range(5) for name in ("app", "engine")]
    active = [name for name, entry in registry.items() if net.owned(entry)]
    if all(name in active for name in expected):
        print("This devnet is already running; data and processes preserved.", flush=True)
    elif active:
        raise RuntimeError("partially running devnet: inspect status, then down/up; no processes were replaced")
    else:
        try:
            net.start_proxy()
            for i in range(5):
                net.start_node(i)
            wait_for("five nodes producing/syncing", lambda: min(height(net.config, i) for i in range(5)) >= 2, 45)
        except Exception:
            net.down()
            raise
    for i in range(5):
        if rpc(net.config, i, "status")["node_info"]["network"] != net.config["chain_id"]:
            raise RuntimeError("RPC chain identity mismatch")


def load(net, args):
    tps = args.tps if args.tps is not None else MODES[args.mode]
    if not 0 < tps <= 500 or not 2 <= args.accounts <= 64 or not 1 <= args.window <= 16:
        raise ValueError("invalid load TPS/accounts/window")
    duration = args.duration if args.duration is not None else (args.hours if args.hours is not None else 1) * 3600
    if not 0 < duration <= 7 * 86400:
        raise ValueError("sending duration must be positive and <=7 days")
    started_wall = time.time()
    process = net.spawn("load", [sys.executable, str(REPO / "scripts/testing/tx_generator.py"), "--dir", str(net.root),
        "--mode", args.mode, "--duration", str(duration), "--tps", str(tps),
        "--accounts", str(args.accounts), "--window", str(args.window), "--amount", str(args.amount)])
    def ready():
        if process.poll() is not None:
            raise ChildProcessError("generator exited; inspect " + str(net.root / "load.log"))
        report = net.root / "load-latest.json"
        return report.exists() and report.stat().st_mtime >= started_wall and read(report)["status"] in ("preparing", "running")
    wait_for("load generator startup", ready, 10)
    print(f"Load PID {process.pid}; target={args.tps or MODES[args.mode]} TPS, sending={duration}s, log={net.root}/load.log", flush=True)


def status(net, args):
    for i in range(5):
        try:
            response = rpc(net.config, i, "status")
            result = response["sync_info"]
            power = int(response["validator_info"]["voting_power"])
            print(f"node{i} ({'validator' if power else 'full'}, power={power}): height={result['latest_block_height']} catching_up={result['catching_up']}")
        except (OSError, RuntimeError):
            print(f"node{i}: stopped/unreachable")
    registry = read(net.registry_path)
    for name in ("load", "exporter"):
        entry = registry.get(name)
        print(f"{name}: {'running' if entry and net.owned(entry) else 'stopped'}")
    latest = net.root / "load-latest.json"
    if latest.exists():
        report = read(latest)
        print(json.dumps({key: report[key] for key in ("status", "submitted", "confirmed", "execution_failed", "unresolved", "observed_confirmed_tps")}))
    prometheus, grafana = ports(net.root, args)
    host = monitoring_host(net.root, args)
    print(f"Grafana http://{host}:{grafana}/d/computechain-v2 ; Prometheus http://{host}:{prometheus}")
    print(f"Data/logs: {net.root}; Grafana password: {net.root}/monitoring/monitoring.env (if configured)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="up", choices=["up", "down", "status", "load", "load-stop",
        "low", "medium", "high", "monitoring-up", "monitoring-down", "monitoring-status",
        "stake", "unstake", "delegate", "undelegate", "update-validator"])
    parser.add_argument("hours", nargs="?", type=float, help="legacy convenience: low 24 => 24-hour load")
    parser.add_argument("--dir", type=Path, default=REPO.parent / ".runtime/comet-staking-devnet")
    parser.add_argument("--base-port", type=int, default=28600, help="only for first initialization")
    parser.add_argument("--no-monitoring", action="store_true")
    parser.add_argument("--prometheus-port", type=int)
    parser.add_argument("--grafana-port", type=int)
    parser.add_argument("--monitoring-host", help="LAN IPv4 for Grafana/Prometheus; ABCI/RPC remain loopback")
    parser.add_argument("--mode", choices=MODES, default="low")
    parser.add_argument("--duration", type=float, help="sending duration in seconds (funding/drain additional)")
    parser.add_argument("--tps", type=float)
    parser.add_argument("--accounts", type=int, default=16)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--amount", type=int, default=10**15)
    parser.add_argument("--validator-node", type=int, choices=range(6), default=4)
    parser.add_argument("--commission-bps", type=int, default=1000)
    args = parser.parse_args()
    if args.tps is not None and not 0 < args.tps <= 500:
        parser.error("TPS must be positive and <=500")
    if args.hours is not None and not 0 < args.hours <= 168:
        parser.error("hours must be positive and <=168")
    if args.duration is not None and not 0 < args.duration <= 7 * 86400:
        parser.error("duration must be positive and <=7 days")
    if not 2 <= args.accounts <= 64 or not 1 <= args.window <= 16 or args.amount <= 0:
        parser.error("accounts=2..64, window=1..16 and positive amount required")
    root = args.dir.resolve()
    # Initialization itself refuses an existing directory; afterwards all mutations
    # share an OS lock. Read-only status can run while a long startup is in progress.
    if args.command in ("up", *MODES) and not root.exists():
        initialize(root, REPO.parent / ".tools/bin/cometbft", args.base_port)
    with operator_lock(root) if root.exists() and args.command != "status" else nullcontext():
        execute(root, args, parser)


def execute(root, args, parser):
    if args.command in ("up", *MODES):
        net = Network(root)
        up(net)
        if not args.no_monitoring:
            print("Starting isolated monitoring project...", flush=True)
            monitoring(net, args, "up")
        if args.command in MODES:
            args.mode = args.command
            load(net, args)
        status(net, args)
        return
    if not (root / "network.json").exists():
        if args.command == "down":
            print("No devnet exists at this --dir; nothing stopped or deleted.")
            return
        parser.error("devnet not initialized; run up first")
    net = Network(root)
    if args.command == "down":
        net.stop("load", timeout=40)
        if not args.no_monitoring and (root / "monitoring/monitoring.env").exists():
            monitoring(net, args, "down")
        net.down()
        print("Stopped this devnet. All keys, chain state, logs and monitoring volumes preserved.")
    elif args.command == "load":
        load(net, args)
    elif args.command == "load-stop":
        net.stop("load", timeout=40)
        print("Load stopped; nodes/monitoring are still running.")
    elif args.command in ("stake", "unstake", "delegate", "undelegate", "update-validator"):
        print(json.dumps(net.staking(args.command.upper().replace("-", "_"), args.validator_node, args.amount, args.commission_bps)))
    elif args.command.startswith("monitoring-"):
        monitoring(net, args, {"monitoring-up": "up", "monitoring-down": "down", "monitoring-status": "status"}[args.command])
    else:
        status(net, args)


if __name__ == "__main__":
    main()
