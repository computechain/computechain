"""Canonical v3 CPC envelopes; account authorization and consensus-key possession."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import re
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import sigencode_string_canonize

from ...protocol.crypto.addresses import address_from_pubkey, decode_address
from ...protocol.crypto.keys import public_key_from_private, verify
from .economics import VERSION, GAS as GAS_BY_TYPE, MIN_GAS_PRICE, MAX_COMMISSION_BPS

GAS = GAS_BY_TYPE["TRANSFER"]  # compatibility for transfer-only tooling
MAX_TX_BYTES = 4096
MAX_AMOUNT = 2**256 - 1
FIELDS = {"version", "chain_id", "type", "from", "to", "amount", "nonce", "gas_price", "gas_limit", "pub_key", "signature", "payload"}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def integer(value: object, name: str, maximum: int = MAX_AMOUNT) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,77}", value):
        raise ValueError(f"invalid {name} encoding")
    parsed = int(value)
    if parsed > maximum:
        raise ValueError(f"{name} overflow")
    return parsed


def signing_hash(tx: dict) -> bytes:
    return hashlib.sha256(b"ComputeChain/tx/v3\0" + canonical({k: v for k, v in tx.items() if k != "signature"})).digest()


def valid_address(address: object) -> bool:
    if not isinstance(address, str):
        return False
    try:
        prefix, data = decode_address(address)
        return prefix == "cpc" and len(data) == 20 and address == address.lower()
    except ValueError:
        return False


def decode(raw: bytes, chain_id: str) -> dict:
    if not raw or len(raw) > MAX_TX_BYTES:
        raise ValueError("transaction size limit")
    try:
        tx = json.loads(raw)
        normalized = canonical(tx)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid transaction JSON") from exc
    if not isinstance(tx, dict) or set(tx) != FIELDS or normalized != raw:
        raise ValueError("noncanonical transaction or unknown fields")
    if type(tx["version"]) is not int or tx["version"] != VERSION or tx["chain_id"] != chain_id:
        raise ValueError("wrong transaction domain")
    kind = tx["type"]
    if not isinstance(kind, str) or kind not in GAS_BY_TYPE:
        raise ValueError("unsupported transaction type")
    if type(tx["nonce"]) is not int or not 0 <= tx["nonce"] < 2**63:
        raise ValueError("invalid nonce")
    gas = GAS_BY_TYPE[kind]
    if type(tx["gas_limit"]) is not int or tx["gas_limit"] != gas:
        raise ValueError("invalid gas limit")
    amount = integer(tx["amount"], "amount")
    price = integer(tx["gas_price"], "gas_price", 2**64 - 1)
    if (amount == 0) != (kind == "UPDATE_VALIDATOR") or price < MIN_GAS_PRICE or amount + gas*price > MAX_AMOUNT:
        raise ValueError("invalid amount or gas price")
    if not valid_address(tx["from"]):
        raise ValueError("invalid account address")
    if not isinstance(tx["payload"], dict):
        raise ValueError("invalid payload")
    data = tx["payload"]
    if kind == "TRANSFER":
        if not valid_address(tx["to"]) or data:
            raise ValueError("invalid transfer recipient/payload")
    else:
        fields = {"validator"}
        if kind == "STAKE":
            fields |= {"proof", "commission_bps"}
        elif kind == "UPDATE_VALIDATOR":
            fields.add("commission_bps")
        if tx["to"] is not None or set(data) != fields:
            raise ValueError("invalid staking fields")
        if not isinstance(data["validator"], str):
            raise ValueError("invalid consensus key")
        from .staking import consensus_key
        consensus_key(data["validator"])
        if "commission_bps" in data and (type(data["commission_bps"]) is not int or not 0 <= data["commission_bps"] <= MAX_COMMISSION_BPS):
            raise ValueError("invalid integer commission")
    if not isinstance(tx["pub_key"], str) or not re.fullmatch(r"0[23][0-9a-f]{64}", tx["pub_key"]):
        raise ValueError("invalid compressed public key")
    if not isinstance(tx["signature"], str) or not re.fullmatch(r"[0-9a-f]{128}", tx["signature"]):
        raise ValueError("invalid signature encoding")
    pub, sig = bytes.fromhex(tx["pub_key"]), bytes.fromhex(tx["signature"])
    if int.from_bytes(sig[32:], "big") > SECP256k1.order//2:
        raise ValueError("noncanonical high-S signature")
    if address_from_pubkey(pub) != tx["from"] or not verify(signing_hash(tx), sig, pub):
        raise ValueError("invalid transaction signature")
    if kind == "STAKE":
        from .staking import verify_possession
        verify_possession(chain_id, tx["from"], data["validator"], data["proof"])
    return tx


def apply(state: dict, tx: dict, *, future_nonce=False):
    candidate = deepcopy(state)
    sender = candidate["accounts"].get(tx["from"], {"balance": 0, "nonce": 0})
    nonce = sender["nonce"]
    if nonce >= 2**63 - 1:
        raise ValueError("nonce exhausted")
    if tx["nonce"] != nonce and not (future_nonce and nonce <= tx["nonce"] <= nonce+64):
        raise ValueError("invalid nonce")
    amount = integer(tx["amount"], "amount")
    fee = GAS_BY_TYPE[tx["type"]] * integer(tx["gas_price"], "gas_price")
    spends = tx["type"] in ("TRANSFER", "STAKE", "DELEGATE")
    cost = fee + (amount if spends else 0)
    if sender["balance"] < cost:
        raise ValueError("insufficient balance")
    candidate["accounts"][tx["from"]] = {"balance": sender["balance"]-cost, "nonce": tx["nonce"]+1}
    candidate["burned"] += fee
    if tx["type"] == "TRANSFER":
        recipient = candidate["accounts"].get(tx["to"], {"balance": 0, "nonce": 0})
        if recipient["balance"] + amount > MAX_AMOUNT:
            raise ValueError("recipient balance overflow")
        candidate["accounts"][tx["to"]] = {"balance": recipient["balance"]+amount, "nonce": recipient["nonce"]}
    else:
        from .staking import execute
        execute(candidate, tx, state)
    if not future_nonce:
        state.clear()
        state.update(candidate)


def sign_transaction(private_key: bytes, chain_id: str, kind: str, amount: int, nonce: int, *, to=None, payload=None, gas_price=MIN_GAS_PRICE):
    pub = public_key_from_private(private_key)
    tx = {"version": VERSION, "chain_id": chain_id, "type": kind, "from": address_from_pubkey(pub),
          "to": to, "amount": str(amount), "nonce": nonce, "gas_price": str(gas_price),
          "gas_limit": GAS_BY_TYPE[kind], "pub_key": pub.hex(), "signature": "", "payload": payload or {}}
    tx["signature"] = SigningKey.from_string(private_key, curve=SECP256k1).sign_digest_deterministic(
        signing_hash(tx), hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize).hex()
    raw = canonical(tx)
    decode(raw, chain_id)
    return raw


def sign_transfer(private_key: bytes, chain_id: str, to: str, amount: int, nonce: int, gas_price=MIN_GAS_PRICE):
    return sign_transaction(private_key, chain_id, "TRANSFER", amount, nonce, to=to, gas_price=gas_price)


def sign_stake(private_key: bytes, chain_id: str, consensus_seed: bytes, amount: int, nonce: int, commission_bps=1000):
    from .staking import possession
    owner = address_from_pubkey(public_key_from_private(private_key))
    key, proof = possession(consensus_seed, chain_id, owner)
    return sign_transaction(private_key, chain_id, "STAKE", amount, nonce,
                            payload={"validator": key, "proof": proof, "commission_bps": commission_bps})
