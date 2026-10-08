"""Explicit LOCAL DEVNET trust anchors; native CometBFT still verifies light blocks.

RPC agreement is not a source of trust. Import anchors via an authenticated operator
channel; export is only for nodes the local operator already controls/trusts.
"""
from __future__ import annotations

import calendar
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from computechain.blockchain.comet.economics import VERSION, EVIDENCE_SECONDS, UNBOND_SECONDS
from computechain.blockchain.comet.transaction import canonical

FORMAT = 1
TRUST_SECONDS = EVIDENCE_SECONDS  # fixed v3 local policy, never enlarged to accept an old anchor
STARTUP_BUDGET_SECONDS = 10
MAX_FILE_BYTES = 8192
FIELDS = {"format", "app_version", "chain_id", "genesis_sha256", "height",
          "block_hash", "block_time_ns", "trust_period_seconds"}


def block_time_ns(value):
    """Parse Comet's UTC RFC3339 timestamps without float/microsecond truncation."""
    if not isinstance(value, str):
        raise ValueError("invalid checkpoint block time")
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise ValueError("invalid checkpoint block time")
    date = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(date.timetuple()) * 10**9 + int((match[2] or "").ljust(9, "0"))


def validate(checkpoint, config, *, now_ns=None):
    if not isinstance(checkpoint, dict) or set(checkpoint) != FIELDS:
        raise ValueError("invalid checkpoint fields")
    for key in ("format", "app_version", "height", "block_time_ns", "trust_period_seconds"):
        if type(checkpoint[key]) is not int:
            raise ValueError("invalid checkpoint integer")
    if checkpoint["format"] != FORMAT or checkpoint["app_version"] != VERSION or config.get("schema") != VERSION:
        raise ValueError("unsupported checkpoint/application version")
    if checkpoint["chain_id"] != config["chain_id"] or checkpoint["genesis_sha256"] != config["genesis_sha256"]:
        raise ValueError("checkpoint belongs to another chain/genesis")
    if not isinstance(checkpoint["genesis_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", checkpoint["genesis_sha256"]):
        raise ValueError("invalid checkpoint genesis identity")
    if not 0 < checkpoint["height"] < 2**63 or not isinstance(checkpoint["block_hash"], str) or not re.fullmatch(r"[0-9A-F]{64}", checkpoint["block_hash"]):
        raise ValueError("invalid checkpoint height/hash")
    if checkpoint["trust_period_seconds"] != TRUST_SECONDS or not 0 < TRUST_SECONDS <= UNBOND_SECONDS // 2:
        raise ValueError("unsupported trust period; never extend an expired checkpoint")
    now_ns = time.time_ns() if now_ns is None else now_ns
    age = now_ns - checkpoint["block_time_ns"]
    if checkpoint["block_time_ns"] <= 0 or age < 0:
        raise ValueError("checkpoint is in the future; check the operator clock")
    if age >= TRUST_SECONDS * 10**9:
        raise ValueError("checkpoint expired; obtain a fresh trusted anchor")
    return (TRUST_SECONDS * 10**9 - age) / 10**9


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint field")
        result[key] = value
    return result


def load(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("checkpoint file too large")
    return json.loads(raw, object_pairs_hook=_unique_pairs)


def export(path, checkpoint):
    """Atomically publish a complete anchor without overwriting any existing file."""
    path = Path(path)
    raw = canonical(checkpoint) + b"\n"
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("checkpoint file too large")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".checkpoint-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(temporary, path)  # atomic O_EXCL-equivalent; symlink/existing target fails
        finally:
            temporary.unlink()


def witnesses(config, indexes):
    indexes = tuple(indexes)
    if not 2 <= len(indexes) <= 6 or len(set(indexes)) != len(indexes):
        raise ValueError("choose at least two distinct witness nodes (maximum six)")
    if any(type(i) is not int or not 0 <= i < len(config["nodes"]) for i in indexes):
        raise ValueError("invalid witness node index")
    return indexes


def local_genesis(config):
    path = Path(config["genesis_file"]) if "genesis_file" in config else Path(config["nodes"][0]) / "config/genesis.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config["genesis_sha256"]:
        raise ValueError("local genesis differs from the pinned network identity")
    value = json.loads(raw)
    if value["chain_id"] != config["chain_id"] or value["app_state"].get("schema") != VERSION:
        raise ValueError("local genesis domain/version mismatch")
    return value


def _genesis_identity(value):
    """Compare RPC genesis without treating RFC3339 trailing zeros as a fork.

    Native Comet reserializes genesis_time using RFC3339Nano. Only that timestamp
    is normalized, to exact integer nanoseconds; every other field remains exact.
    The original local file's SHA256 is still checked by local_genesis separately.
    """
    if not isinstance(value, dict):
        raise ValueError("invalid witness genesis")
    normalized = dict(value)
    if "genesis_time" in normalized:
        normalized["genesis_time"] = block_time_ns(normalized["genesis_time"])
    return canonical(normalized)


def _identity(reply, config, h):
    try:
        header = reply["block"]["header"]
        digest = reply["block_id"]["hash"]
        if header["chain_id"] != config["chain_id"] or int(header["height"]) != h:
            raise ValueError("witness block domain/height mismatch")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9A-F]{64}", digest):
            raise ValueError("invalid witness block hash")
        return digest, block_time_ns(header["time"])
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed witness block") from exc


def check_witnesses(checkpoint, config, call, indexes, *, now_ns=None):
    validate(checkpoint, config, now_ns=now_ns)
    expected_genesis = _genesis_identity(local_genesis(config))
    healthy, unavailable, ids = [], [], set()
    for i in witnesses(config, indexes):
        # Transport/RPC availability is recoverable; contradictory data is not.
        try:
            status = call(i, "status", timeout=2)
            genesis_reply = call(i, "genesis", timeout=2)
            block = call(i, "block", timeout=2, height=checkpoint["height"])
        except (OSError, RuntimeError) as exc:
            unavailable.append({"node": i, "reason": type(exc).__name__})
            continue
        try:
            genesis = genesis_reply["genesis"]
            node = status["node_info"]
            if node["network"] != config["chain_id"] or _genesis_identity(genesis) != expected_genesis:
                raise ValueError("witness belongs to another chain/genesis")
            if not isinstance(node["id"], str) or not re.fullmatch(r"[0-9a-f]{40}", node["id"]) or node["id"] in ids:
                raise ValueError("witness node identity is invalid or duplicated")
            if "expected_node_ids" in config and node["id"] != config["expected_node_ids"][i]:
                raise ValueError("witness does not match the approved node identity")
            if int(status["sync_info"]["latest_block_height"]) < checkpoint["height"]:
                raise ValueError("witness is behind the checkpoint")
            if _identity(block, config, checkpoint["height"]) != (checkpoint["block_hash"], checkpoint["block_time_ns"]):
                raise ValueError("witness conflicts with the trusted checkpoint")
            ids.add(node["id"])
            healthy.append(i)
        except (KeyError, TypeError) as exc:
            raise ValueError("malformed witness response") from exc
    if len(healthy) < 2:
        raise ValueError("fewer than two available matching witnesses; no bootstrap")
    remaining = validate(checkpoint, config, now_ns=now_ns)
    if remaining < STARTUP_BUDGET_SECONDS:
        raise ValueError("checkpoint near expiry; obtain a fresh trusted anchor")
    return {"witnesses": healthy, "unavailable": unavailable, "trust_remaining_seconds": remaining}


def capture(config, call, indexes=(0, 1), *, now_ns=None):
    """Capture ONLY from controlled local nodes, never unauthenticated public RPC."""
    indexes = witnesses(config, indexes)
    local_genesis(config)
    for i in indexes:
        try:
            latest = int(call(i, "status", timeout=2)["sync_info"]["latest_block_height"])
            h = latest - 3
            if h < 1:
                raise ValueError("wait for at least four finalized blocks before capture")
            digest, stamp = _identity(call(i, "block", timeout=2, height=h), config, h)
            break
        except (OSError, RuntimeError):
            continue
    else:
        raise ValueError("no witness available to capture a local checkpoint")
    value = {"format": FORMAT, "app_version": VERSION, "chain_id": config["chain_id"],
        "genesis_sha256": config["genesis_sha256"], "height": h, "block_hash": digest,
        "block_time_ns": stamp, "trust_period_seconds": TRUST_SECONDS}
    check_witnesses(value, config, call, indexes, now_ns=now_ns)
    return value
