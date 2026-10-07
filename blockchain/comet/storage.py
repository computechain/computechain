"""Durable application state, receipts and bounded snapshot retention."""
from __future__ import annotations

from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from .transaction import canonical, valid_address, MAX_AMOUNT, MIN_GAS_PRICE
from .economics import VERSION

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
CHUNK_SIZE = 256 * 1024
STATE_KEYS = {"schema", "chain_id", "initial_height", "height", "last_block_hash", "accounts", "burned", "supply", "gas_price_min"}
STATE_KEYS |= {"time_ns", "policy", "validators", "unbondings", "engine_powers", "validator_history", "seen_evidence"}


def state_hash(state: dict) -> bytes:
    return hashlib.sha256(canonical(state)).digest()


def validate_state(state: dict, chain_id: str) -> None:
    if not isinstance(state, dict) or set(state) != STATE_KEYS or type(state["schema"]) is not int or state["schema"] != VERSION or state["chain_id"] != chain_id:
        raise ValueError("wrong application schema or chain")
    for key in ("initial_height", "height", "burned", "supply", "gas_price_min"):
        if type(state[key]) is not int or state[key] < 0:
            raise ValueError("invalid state metadata")
    if state["initial_height"] != 1 or state["gas_price_min"] != MIN_GAS_PRICE:
        raise ValueError("unsupported application parameters")
    if state["height"] >= 2**63:
        raise ValueError("height overflow")
    if not isinstance(state["last_block_hash"], str) or len(state["last_block_hash"]) != 64:
        raise ValueError("invalid state block hash")
    if bytes.fromhex(state["last_block_hash"]).hex() != state["last_block_hash"]:
        raise ValueError("noncanonical state block hash")
    if not isinstance(state["accounts"], dict):
        raise ValueError("invalid accounts")
    from .staking import validate_staking
    total = state["burned"] + validate_staking(state)
    for address, account in state["accounts"].items():
        if not valid_address(address) or not isinstance(account, dict) or set(account) != {"balance", "nonce"}:
            raise ValueError("invalid account")
        for key in ("balance", "nonce"):
            if type(account[key]) is not int or not 0 <= account[key] <= MAX_AMOUNT:
                raise ValueError("invalid account value")
        if account["nonce"] >= 2**63:
            raise ValueError("nonce overflow")
        total += account["balance"]
    if total != state["supply"] or total > MAX_AMOUNT:
        raise ValueError("supply conservation failed")


class Store:
    def __init__(self, directory: Path, chain_id: str, snapshot_interval: int = 10):
        if type(snapshot_interval) is not int or snapshot_interval < 1:
            raise ValueError("snapshot interval must be positive")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.chain_id = chain_id
        self.snapshot_interval = snapshot_interval
        self.lock = threading.RLock()
        self._writer_lock = (self.directory / ".writer.lock").open("a+b")
        try:
            fcntl.flock(self._writer_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._writer_lock.close()
            raise RuntimeError("application directory already has a writer") from exc
        self.conn = None
        try:
            self.conn = sqlite3.connect(self.directory / "application.sqlite", check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS committed(id INTEGER PRIMARY KEY CHECK(id=1), state BLOB NOT NULL, hash BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(hash TEXT PRIMARY KEY, height INTEGER NOT NULL, result BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(height INTEGER PRIMARY KEY, hash BLOB NOT NULL, data BLOB NOT NULL);
            """)
            row = self.conn.execute("SELECT state, hash FROM committed WHERE id=1").fetchone()
            self.state = json.loads(row[0]) if row else None
            if self.state is not None:
                validate_state(self.state, chain_id)
                if state_hash(self.state) != row[1]:
                    raise ValueError("durable application hash mismatch")
        except Exception:
            self.close()
            raise

    def clone(self) -> dict:
        with self.lock:
            if self.state is None:
                raise ValueError("application not initialized")
            return deepcopy(self.state)

    def commit(self, state: dict, receipts: list[tuple[str, int, dict]] = (), *, restoring: bool = False):
        with self.lock:
            self._commit(state, receipts, restoring=restoring)

    def _commit(self, state: dict, receipts, *, restoring: bool):
        validate_state(state, self.chain_id)
        if restoring:
            if self.state is not None and self.state["height"] > 0:
                raise ValueError("restoring over a live application prohibited")
        elif self.state is None:
            if state["height"] != 0:
                raise ValueError("application must initialize at genesis")
        elif state["height"] == self.state["height"]:
            if state != self.state or receipts:
                raise ValueError("conflicting application commit at the same height")
            return
        elif state["height"] != self.state["height"] + 1:
            raise ValueError("application height must advance by one; rollback prohibited")
        raw = canonical(state)
        digest = hashlib.sha256(raw).digest()
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO committed VALUES (1, ?, ?)", (raw, digest))
            if restoring:
                self.conn.execute("DELETE FROM receipts")
            for tx_hash, height, result in receipts:
                self.conn.execute("INSERT OR REPLACE INTO receipts VALUES (?, ?, ?)", (tx_hash, height, canonical(result)))
            if state["height"] > 0 and state["height"] % self.snapshot_interval == 0 and len(raw) <= MAX_SNAPSHOT_BYTES:
                self.conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)", (state["height"], digest, raw))
                self.conn.execute("DELETE FROM snapshots WHERE height NOT IN (SELECT height FROM snapshots ORDER BY height DESC LIMIT 10)")
        self.state = deepcopy(state)  # Publish only after durable commit.

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self._writer_lock is not None:
            self._writer_lock.close()
            self._writer_lock = None
