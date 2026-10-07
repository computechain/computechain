#!/usr/bin/env python3
"""Bounded signed TRANSFER load with distinct admission/commit statistics."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent))
from computechain.scripts.comet_devnet import Network, read, transaction_writer, rpc
from computechain.blockchain.comet.transaction import sign_transfer, GAS, MIN_GAS_PRICE
from computechain.cli.keystore import KeyStore
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

MODES = {"low": 3, "medium": 25, "high": 100}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class Generator:
    def __init__(self, root, *, tps=3, duration=60, accounts=16, window=8, amount=10**15):
        if not 0 < tps <= 500 or not 0 < duration <= 7 * 86400 or not 2 <= accounts <= 64 or not 1 <= window <= 16 or amount <= 0:
            raise ValueError("invalid load limits (TPS<=500, duration<=7d, accounts=2..64, window=1..16)")
        self.net = Network(Path(root))
        self.tps, self.duration, self.count, self.window, self.amount = tps, duration, accounts, window, amount
        self.stopping = False
        self.pending = {}
        self.latencies = deque(maxlen=10000)
        self.latency_sum = 0.0
        self.started = None
        self.run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.time_ns() % 1000000:06d}"
        self.report = {"run_id": self.run_id, "chain_id": self.net.config["chain_id"], "status": "preparing",
            "target_tps": tps, "duration_seconds": duration, "accounts": accounts, "window": window,
            "amount_base_units": amount, "submitted": 0, "checktx_rejected": 0, "broadcast_errors": 0,
            "confirmed": 0, "execution_failed": 0, "unresolved": 0, "elapsed_seconds": 0}

    def account(self, address):
        import base64
        response = rpc(self.net.config, 0, "abci_query", path=json.dumps("/account/" + address))["response"]
        if int(response.get("code", 0)):
            raise RuntimeError("account query rejected")
        return json.loads(base64.b64decode(response["value"]))

    def prepare(self):
        config = self.net.config
        status = rpc(config, 0, "status")
        if status["node_info"]["network"] != config["chain_id"] or status["sync_info"]["catching_up"]:
            raise RuntimeError("node is on the wrong chain or still syncing")
        genesis = rpc(config, 0, "genesis")["genesis"]
        local = read(Path(config["nodes"][0]) / "config/genesis.json")
        if genesis["app_state"] != local["app_state"] or genesis["validators"] != local["validators"]:
            raise RuntimeError("RPC genesis does not match this devnet")
        key = bytes.fromhex((self.net.root / "faucet-private.hex").read_text().strip())
        if address_from_pubkey(public_key_from_private(key)) != config["faucet"]:
            raise RuntimeError("faucet key does not match the network")
        keys = KeyStore(str(self.net.root / "load-wallets"))
        self.wallets = []
        for i in range(self.count):
            name = f"load-{i:03d}"
            self.wallets.append(keys.get_key(name) or keys.create_key(name))
        # Ring transfers recycle principal; fees alone consume supply. No global wallet touched.
        funding = max(100 * 10**18, self.amount * self.window * 4)
        needs = [(w, max(0, funding - self.account(w["address"])["balance"])) for w in self.wallets]
        source = self.account(config["faucet"])
        fees = sum(GAS * MIN_GAS_PRICE for _, need in needs if need)
        if source["balance"] < sum(need for _, need in needs) + fees:
            raise RuntimeError("devnet faucet cannot fund the requested load")
        for i, (wallet, need) in enumerate(needs):
            if self.stopping:
                return
            if need:
                raw = sign_transfer(key, config["chain_id"], wallet["address"], need, source["nonce"])
                result = rpc(config, 0, "broadcast_tx_commit", tx="0x" + raw.hex())
                if int(result["check_tx"].get("code", 0)) or int(result.get("tx_result", result.get("deliver_tx", {})).get("code", 0)):
                    raise RuntimeError("funding transaction failed")
                source["nonce"] += 1
            wallet["next_nonce"] = self.account(wallet["address"])["nonce"]
            wallet["inflight"] = 0
            self.save()
            print(f"wallet {i+1}/{self.count} ready", flush=True)

    def submit(self, index):
        wallet = self.wallets[index]
        if wallet["inflight"] >= self.window:
            return False
        raw = sign_transfer(bytes.fromhex(wallet["private_key"]), self.net.config["chain_id"],
            self.wallets[(index + 1) % self.count]["address"], self.amount, wallet["next_nonce"])
        digest = hashlib.sha256(raw).hexdigest().upper()
        now = time.monotonic()
        self.report["submitted"] += 1
        try:
            response = rpc(self.net.config, 0, "broadcast_tx_sync", timeout=2, tx="0x" + raw.hex())
            if int(response.get("code", 0)):
                self.report["checktx_rejected"] += 1
                raise RuntimeError("CheckTx rejected load transaction: " + str(response.get("log", "")))
        except OSError:
            # The RPC may have received the transaction before losing its reply.
            # Keep its exact bytes/hash/nonce; never allocate a replacement meaning.
            self.report["broadcast_errors"] += 1
        self.pending[digest] = {"wallet": index, "raw": raw, "sent": now, "retry": now}
        wallet["next_nonce"] += 1
        wallet["inflight"] += 1
        return True

    def track(self):
        now = time.monotonic()
        round_started = now
        for digest, record in list(self.pending.items()):
            if time.monotonic() - round_started > 1:
                break  # Bound tracker work even while RPC is slow/unavailable.
            try:
                result = rpc(self.net.config, 0, "tx", timeout=2, hash="0x" + digest, prove="false")
            except (OSError, RuntimeError):
                if now - record["sent"] > 60:
                    raise RuntimeError("accepted/uncertain transaction did not commit within 60 seconds")
                if now - record["retry"] > 5:
                    try:
                        rpc(self.net.config, 0, "broadcast_tx_sync", timeout=2, tx="0x" + record["raw"].hex())
                    except (OSError, RuntimeError):
                        pass
                    record["retry"] = now
                self.pending.pop(digest)
                self.pending[digest] = record  # Fairness: don't let one missing TX starve others.
                continue
            del self.pending[digest]
            self.wallets[record["wallet"]]["inflight"] -= 1
            if int(result["tx_result"].get("code", 0)):
                self.report["execution_failed"] += 1
                raise RuntimeError("committed load transaction failed execution; stopping before nonce gaps")
            self.report["confirmed"] += 1
            latency = time.monotonic() - record["sent"]
            self.latencies.append(latency)
            self.latency_sum += latency

    def save(self):
        elapsed = time.monotonic() - self.started if self.started is not None else 0
        self.report.update(elapsed_seconds=round(elapsed, 3), unresolved=len(self.pending),
            observed_confirmed_tps=round(self.report["confirmed"] / elapsed, 3) if elapsed else 0,
            updated_at=time.time(), latency_count=self.report["confirmed"], latency_sum_seconds=self.latency_sum)
        if self.latencies:
            values = sorted(self.latencies)
            self.report["latency_seconds"] = {str(q): values[min(len(values)-1, int((len(values)-1)*q))] for q in (0.5, 0.95, 0.99)}
        atomic_json(self.net.root / "load-latest.json", self.report)
        atomic_json(self.net.root / f"load-{self.run_id}.json", self.report)

    def run(self):
        with transaction_writer(self.net.root):
            try:
                self.save()
                self.prepare()
                self.started = time.monotonic()
                self.report["status"] = "running"
                next_send = self.started
                next_track = next_report = self.started
                index = 0
                while not self.stopping and time.monotonic() - self.started < self.duration:
                    now = time.monotonic()
                    if now >= next_track:
                        self.track()
                        next_track = time.monotonic() + 0.25
                    if now >= next_report:
                        self.save()
                        print(json.dumps({k: self.report[k] for k in ("status", "submitted", "confirmed", "unresolved", "observed_confirmed_tps")}), flush=True)
                        next_report = now + 5
                    if now >= next_send:
                        for _ in range(self.count):
                            chosen = index % self.count
                            index += 1
                            if self.submit(chosen):
                                break
                        # Avoid catch-up bursts when the signer/RPC cannot meet target TPS.
                        next_send = max(next_send + 1 / self.tps, time.monotonic())
                    else:
                        time.sleep(min(0.02, next_send - now))
                self.report["status"] = "draining"
                self.save()
                deadline = time.monotonic() + 30
                while self.pending and time.monotonic() < deadline:
                    self.track()
                    self.save()
                    time.sleep(0.25)
                if self.pending:
                    raise RuntimeError("unresolved transactions after drain; see report, do not assume they failed")
                self.report["status"] = "stopped" if self.stopping else "completed"
            except Exception as exc:
                self.report.update(status="failed", error=str(exc))
                raise
            finally:
                self.save()
                print(json.dumps(self.report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=REPO.parent / ".runtime/comet-staking-devnet")
    parser.add_argument("--mode", choices=MODES, default="low")
    parser.add_argument("--tps", type=float)
    parser.add_argument("--duration", type=float, default=60, help="sending duration in seconds, plus funding/drain")
    parser.add_argument("--accounts", type=int, default=16)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--amount", type=int, default=10**15, help="base units; default 0.001 CPC")
    args = parser.parse_args()
    generator = Generator(args.dir.resolve(), tps=args.tps if args.tps is not None else MODES[args.mode], duration=args.duration,
                          accounts=args.accounts, window=args.window, amount=args.amount)
    signal.signal(signal.SIGTERM, lambda *_: setattr(generator, "stopping", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(generator, "stopping", True))
    generator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
