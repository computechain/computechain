"""Deterministic v3 stake ledger, consensus-key binding and evidence liabilities."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import re

from ecdsa import Ed25519, SigningKey, VerifyingKey
from ecdsa.ellipticcurve import PointEdwards, INFINITY

from .economics import *
from .transaction import canonical, valid_address, MAX_AMOUNT

VAL_KEYS = {"owner", "self_stake", "self_bonds", "delegations", "commission_bps", "commission_change",
            "last_commission_height", "tombstoned", "penalties"}
QUEUE_KEYS = {"owner", "validator", "amount", "bond_height", "created_height", "release_height", "release_time_ns"}


def number(value, maximum=MAX_AMOUNT):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid bounded integer in staking state")
    return value


@lru_cache(maxsize=256)
def consensus_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid Ed25519 consensus key encoding")
    raw = bytes.fromhex(value)
    try:
        point = PointEdwards.from_bytes(Ed25519.curve, raw, order=None)
        if point.to_bytes() != raw or point * 8 == INFINITY or point * Ed25519.order != INFINITY:
            raise ValueError("weak or non-prime-subgroup Ed25519 consensus key")
    except (ValueError, AssertionError) as exc:
        raise ValueError("invalid/weak Ed25519 consensus key") from exc
    return raw


def proof_message(chain, owner, key):
    return b"ComputeChain/validator-key/v3\0" + canonical({"chain_id": chain, "owner": owner, "pub_key": key})


def possession(seed, chain, owner):
    signer = SigningKey.from_string(seed, curve=Ed25519)
    key = signer.verifying_key.to_string().hex()
    return key, signer.sign(proof_message(chain, owner, key)).hex()


def verify_possession(chain, owner, key, signature):
    raw = consensus_key(key)
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        raise ValueError("invalid consensus proof encoding")
    try:
        if not VerifyingKey.from_string(raw, curve=Ed25519).verify(bytes.fromhex(signature), proof_message(chain, owner, key)):
            raise ValueError("invalid consensus key possession")
    except Exception as exc:
        raise ValueError("invalid consensus key possession") from exc


def bonded(validator):
    return validator["self_stake"] + sum(d["amount"] for d in validator["delegations"].values())


def powers(state):
    result = {key: bonded(val) // POWER_UNIT for key, val in state["validators"].items()
              if not val["tombstoned"] and val["self_stake"] >= MIN_SELF_STAKE}
    if not result or sum(result.values()) > MAX_TOTAL_POWER:
        raise ValueError("empty or overflowing validator set")
    return result


def initial_state(chain, genesis, time_ns=0):
    if not isinstance(genesis, dict) or set(genesis) != {"schema", "accounts", "validators"} or type(genesis["schema"]) is not int or genesis["schema"] != VERSION:
        raise ValueError("genesis requires explicit v3 schema/accounts/validators; v2 is not migrated")
    if not isinstance(genesis["accounts"], dict) or not isinstance(genesis["validators"], list):
        raise ValueError("invalid genesis collections")
    state = {"schema": VERSION, "chain_id": chain, "initial_height": 1, "height": 0, "time_ns": number(time_ns, 2**63-1),
        "last_block_hash": "0"*64, "accounts": deepcopy(genesis["accounts"]), "burned": 0, "supply": 0,
        "gas_price_min": MIN_GAS_PRICE, "policy": policy(), "validators": {}, "unbondings": [],
        "engine_powers": {}, "validator_history": {}, "seen_evidence": {}}
    for item in genesis["validators"]:
        if not isinstance(item, dict) or set(item) != {"pub_key", "owner", "self_stake", "commission_bps"}:
            raise ValueError("invalid genesis validator")
        key, owner, amount = item["pub_key"], item["owner"], item["self_stake"]
        consensus_key(key)
        if key in state["validators"] or not valid_address(owner) or number(amount) < MIN_SELF_STAKE:
            raise ValueError("invalid/duplicate genesis validator")
        state["validators"][key] = new_validator(owner, amount, 1, item["commission_bps"])
    state["engine_powers"] = powers(state)
    state["validator_history"] = {"1": {"powers": state["engine_powers"].copy(), "time_ns": time_ns}}
    state["supply"] = sum(a["balance"] for a in state["accounts"].values()) + sum(bonded(v) for v in state["validators"].values())
    from .storage import validate_state
    validate_state(state, chain)
    return state


def new_validator(owner, amount, height, commission):
    number(commission, MAX_COMMISSION_BPS)
    return {"owner": owner, "self_stake": amount, "self_bonds": [{"amount": amount, "height": height}],
        "delegations": {}, "commission_bps": commission, "commission_change": None,
        "last_commission_height": 0, "tombstoned": False, "penalties": 0}


def append_bond(bonds, amount, height):
    if bonds and bonds[-1]["height"] == height:
        bonds[-1]["amount"] += amount
    else:
        if len(bonds) >= MAX_BONDS:
            raise ValueError("deposit cohort limit")
        bonds.append({"amount": amount, "height": height})


def withdraw(state, key, owner, bonds, amount):
    remaining = amount
    # Newest-first, retaining the exact liability start of each portion.
    for bond in reversed(bonds):
        take = min(bond["amount"], remaining)
        if take:
            if sum(q["owner"] == owner for q in state["unbondings"]) >= MAX_UNBONDINGS:
                raise ValueError("unbonding queue limit")
            state["unbondings"].append({"owner": owner, "validator": key, "amount": take,
                "bond_height": bond["height"], "created_height": state["height"],
                "release_height": state["height"] + UPDATE_DELAY + UNBOND_BLOCKS,
                "release_time_ns": state["time_ns"] + UNBOND_SECONDS*10**9})
            bond["amount"] -= take
            remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise ValueError("insufficient bonded principal")
    bonds[:] = [b for b in bonds if b["amount"]]


def enforce_increase(before, after, key):
    previous, current = powers(before), powers(after)
    new_share = current.get(key, 0)
    if new_share * BPS > sum(current.values()) * MAX_POWER_SHARE_BPS:
        if new_share * sum(previous.values()) > previous.get(key, 0) * sum(current.values()):
            raise ValueError("validator power concentration limit")


def execute(state, tx, before):
    kind, owner, amount, data = tx["type"], tx["from"], int(tx["amount"]), tx["payload"]
    key = data["validator"]
    consensus_key(key)
    val = state["validators"].get(key)
    if kind == "STAKE":
        verify_possession(state["chain_id"], owner, key, data["proof"])
        if val is None:
            if len(state["validators"]) >= MAX_VALIDATORS or any(v["owner"] == owner for v in state["validators"].values()):
                raise ValueError("validator/owner registration limit")
            if amount < MIN_SELF_STAKE:
                raise ValueError("minimum self stake")
            val = new_validator(owner, amount, state["height"] + UPDATE_DELAY, data["commission_bps"])
            state["validators"][key] = val
        else:
            if val["owner"] != owner or val["tombstoned"] or data["commission_bps"] != val["commission_bps"]:
                raise ValueError("owner/key/commission mismatch or tombstoned validator")
            val["self_stake"] += amount
            append_bond(val["self_bonds"], amount, state["height"] + UPDATE_DELAY)
        enforce_increase(before, state, key)
        return
    if val is None:
        raise ValueError("unknown validator")
    if kind == "UNSTAKE":
        if val["owner"] != owner or amount > val["self_stake"]:
            raise ValueError("owner mismatch or insufficient self stake")
        withdraw(state, key, owner, val["self_bonds"], amount)
        val["self_stake"] -= amount
    elif kind == "DELEGATE":
        if owner == val["owner"] or val["tombstoned"] or val["self_stake"] < MIN_SELF_STAKE or amount < MIN_DELEGATION:
            raise ValueError("ineligible validator or delegation amount")
        relationships = {k for k, v in state["validators"].items() if owner in v["delegations"]}
        relationships.update(q["validator"] for q in state["unbondings"] if q["owner"] == owner)
        if key not in relationships and len(relationships) >= MAX_DELEGATIONS:
            raise ValueError("delegation relationship limit")
        delegation = val["delegations"].setdefault(owner, {"amount": 0, "bonds": []})
        delegation["amount"] += amount
        append_bond(delegation["bonds"], amount, state["height"] + UPDATE_DELAY)
        enforce_increase(before, state, key)
    elif kind == "UNDELEGATE":
        delegation = val["delegations"].get(owner)
        if delegation is None or amount > delegation["amount"]:
            raise ValueError("insufficient own delegation")
        withdraw(state, key, owner, delegation["bonds"], amount)
        delegation["amount"] -= amount
        if not delegation["amount"]:
            del val["delegations"][owner]
    elif kind == "UPDATE_VALIDATOR":
        rate = number(data["commission_bps"], MAX_COMMISSION_BPS)
        if val["owner"] != owner or val["tombstoned"] or val["commission_change"] is not None:
            raise ValueError("only owner can schedule one commission change")
        if state["height"] < val["last_commission_height"] + COMMISSION_COOLDOWN_BLOCKS:
            raise ValueError("commission cooldown")
        if rate - val["commission_bps"] > MAX_COMMISSION_INCREASE_BPS:
            raise ValueError("commission increase limit")
        val["commission_change"] = {"bps": rate, "height": state["height"] + COMMISSION_ANNOUNCE_BLOCKS}
        val["last_commission_height"] = state["height"]
    else:
        raise ValueError("unsupported stake operation")
    powers(state)  # Reject the transaction, not an entire block, if the last voter exits.


def historical_powers(state, height):
    keys = [int(h) for h in state["validator_history"] if int(h) <= height]
    if not keys:
        raise ValueError("historical validator set unavailable")
    return state["validator_history"][str(max(keys))]["powers"]


def slash(state, item, previous_height, previous_time):
    height, timestamp = item.height, item.time.seconds*10**9 + item.time.nanos
    if item.type not in (1, 2) or not 1 <= height <= previous_height or not 0 <= timestamp <= previous_time:
        raise ValueError("invalid verified evidence metadata")
    # Comet validates proposed evidence against the PREVIOUS committed block.
    # Using the new block time/height rejects genuine boundary evidence.
    if previous_height - height > EVIDENCE_BLOCKS and previous_time - timestamp > EVIDENCE_SECONDS*10**9:
        raise ValueError("expired verified evidence")
    identifier = f"{item.validator.address.hex()}:{item.type}:{height}"
    if identifier in state["seen_evidence"]:
        return
    old = historical_powers(state, height)
    # LIGHT_CLIENT_ATTACK uses common height/total power, but its individual
    # validator power can come from the conflicting height (upstream evidence.go).
    # ABCI does not carry that latter height. Rely on native cryptographic
    # verification; do not reject genuine evidence by conflating the two sets.
    candidates = old if item.type == 1 else state["validators"]
    keys = [k for k in candidates if hashlib.sha256(bytes.fromhex(k)).digest()[:20] == item.validator.address]
    if (len(keys) != 1 or not 0 < item.validator.power <= MAX_TOTAL_POWER
            or (item.type == 1 and old[keys[0]] != item.validator.power)
            or sum(old.values()) != item.total_voting_power):
        raise ValueError("evidence differs from historical validator power")
    key = keys[0]
    val = state["validators"][key]
    penalty = 0
    for bonds in [val["self_bonds"], *(d["bonds"] for d in val["delegations"].values())]:
        for bond in bonds:
            if bond["height"] <= height:
                loss = bond["amount"] * SLASH_BPS // BPS
                bond["amount"] -= loss
                penalty += loss
    val["self_stake"] = sum(b["amount"] for b in val["self_bonds"])
    for delegation in val["delegations"].values():
        delegation["amount"] = sum(b["amount"] for b in delegation["bonds"])
    for entry in state["unbondings"]:
        if entry["validator"] == key and entry["bond_height"] <= height < entry["created_height"] + UPDATE_DELAY:
            loss = entry["amount"] * SLASH_BPS // BPS
            entry["amount"] -= loss
            penalty += loss
    val["penalties"] += penalty
    val["tombstoned"] = True
    state["burned"] += penalty
    state["seen_evidence"][identifier] = {"height": height, "time_ns": timestamp}


def begin_block(state, height, time_ns, evidence=()):
    if height != state["height"] + 1 or time_ns < state["time_ns"]:
        raise ValueError("nonsequential height or consensus time")
    previous_height, previous_time = state["height"], state["time_ns"]
    state["height"], state["time_ns"] = height, number(time_ns, 2**63-1)
    if str(height) in state["validator_history"]:
        state["validator_history"][str(height)]["time_ns"] = time_ns
    for item in evidence:
        slash(state, item, previous_height, previous_time)
    kept = []
    for entry in state["unbondings"]:
        if height >= entry["release_height"] and time_ns >= entry["release_time_ns"]:
            account = state["accounts"].setdefault(entry["owner"], {"balance": 0, "nonce": 0})
            account["balance"] += entry["amount"]
        else:
            kept.append(entry)
    state["unbondings"] = kept
    for val in state["validators"].values():
        change = val["commission_change"]
        if change and height >= change["height"]:
            val["commission_bps"], val["commission_change"] = change["bps"], None
    # Native evidence expires only when BOTH time and height windows have passed.
    history = sorted(int(h) for h in state["validator_history"])
    while len(history) > 1:
        successor = state["validator_history"][str(history[1])]
        if successor["time_ns"] is None or height-history[1] <= EVIDENCE_BLOCKS or time_ns-successor["time_ns"] <= EVIDENCE_SECONDS*10**9:
            break
        del state["validator_history"][str(history.pop(0))]
    state["seen_evidence"] = {k: v for k, v in state["seen_evidence"].items()
        if height-v["height"] <= EVIDENCE_BLOCKS or time_ns-v["time_ns"] <= EVIDENCE_SECONDS*10**9}


def finish_block(state):
    desired = powers(state)
    old = state["engine_powers"]
    changes = [(key, desired.get(key, 0)) for key in sorted(set(old) | set(desired)) if old.get(key, 0) != desired.get(key, 0)]
    if changes:
        state["validator_history"][str(state["height"] + UPDATE_DELAY)] = {"powers": desired.copy(), "time_ns": None}
    state["engine_powers"] = desired
    return changes


def validate_staking(state):
    if canonical(state["policy"]) != canonical(policy()) or type(state["time_ns"]) is not int or not 0 <= state["time_ns"] < 2**63:
        raise ValueError("unsupported monetary policy/consensus time")
    if not isinstance(state["validators"], dict) or not 0 < len(state["validators"]) <= MAX_VALIDATORS:
        raise ValueError("invalid validator collection")
    total, owners = 0, set()
    def bonds(entries):
        if not isinstance(entries, list) or len(entries) > MAX_BONDS:
            raise ValueError("invalid bond cohorts")
        result, previous = 0, 0
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"amount", "height"} or not 1 <= number(entry["height"]) <= state["height"]+UPDATE_DELAY:
                raise ValueError("invalid bond cohort")
            if not number(entry["amount"]) or entry["height"] <= previous:
                raise ValueError("invalid cohort ordering/amount")
            previous = entry["height"]
            result += entry["amount"]
        return result
    for key, val in state["validators"].items():
        consensus_key(key)
        if not isinstance(val, dict) or set(val) != VAL_KEYS or not valid_address(val["owner"]) or val["owner"] in owners:
            raise ValueError("invalid validator identity")
        owners.add(val["owner"])
        if number(val["self_stake"]) != bonds(val["self_bonds"]) or type(val["tombstoned"]) is not bool:
            raise ValueError("self stake accounting mismatch")
        number(val["commission_bps"], MAX_COMMISSION_BPS)
        number(val["penalties"])
        number(val["last_commission_height"], state["height"])
        change = val["commission_change"]
        if change is not None:
            if not isinstance(change, dict) or set(change) != {"bps", "height"}:
                raise ValueError("invalid commission schedule")
            number(change["bps"], MAX_COMMISSION_BPS)
            number(change["height"])
            if change["height"] != val["last_commission_height"]+COMMISSION_ANNOUNCE_BLOCKS or change["height"] <= state["height"]:
                raise ValueError("invalid commission effective height")
        if not isinstance(val["delegations"], dict):
            raise ValueError("invalid delegations")
        for address, delegation in val["delegations"].items():
            if not valid_address(address) or address == val["owner"] or not isinstance(delegation, dict) or set(delegation) != {"amount", "bonds"}:
                raise ValueError("invalid delegator")
            if not number(delegation["amount"]) or delegation["amount"] != bonds(delegation["bonds"]):
                raise ValueError("delegation accounting mismatch")
        total += bonded(val)
    if not isinstance(state["unbondings"], list):
        raise ValueError("invalid unbonding queue")
    counts = {}
    relationships = {}
    for key, val in state["validators"].items():
        for owner in val["delegations"]:
            relationships.setdefault(owner, set()).add(key)
    for entry in state["unbondings"]:
        if not isinstance(entry, dict) or set(entry) != QUEUE_KEYS or not valid_address(entry["owner"]) or entry["validator"] not in state["validators"]:
            raise ValueError("invalid withdrawal identity")
        if not number(entry["amount"]) or not 1 <= number(entry["bond_height"]) <= state["height"]+UPDATE_DELAY:
            raise ValueError("invalid withdrawal amount/cohort")
        if not 1 <= number(entry["created_height"]) <= state["height"] or entry["release_height"] != entry["created_height"]+UPDATE_DELAY+UNBOND_BLOCKS:
            raise ValueError("invalid withdrawal height")
        number(entry["release_height"])
        if entry["bond_height"] > entry["created_height"]+UPDATE_DELAY:
            raise ValueError("withdrawal cohort starts after withdrawal")
        if number(entry["release_time_ns"], 2**63-1) < UNBOND_SECONDS*10**9:
            raise ValueError("invalid withdrawal time")
        counts[entry["owner"]] = counts.get(entry["owner"], 0)+1
        if counts[entry["owner"]] > MAX_UNBONDINGS:
            raise ValueError("withdrawal queue limit")
        if entry["owner"] != state["validators"][entry["validator"]]["owner"]:
            relationships.setdefault(entry["owner"], set()).add(entry["validator"])
        total += entry["amount"]
    if any(len(keys) > MAX_DELEGATIONS for keys in relationships.values()):
        raise ValueError("delegation relationship limit")
    def valid_powers(value):
        if not isinstance(value, dict) or not value or any(key not in state["validators"] for key in value):
            raise ValueError("invalid consensus validator set")
        if any(not number(v, MAX_TOTAL_POWER) for v in value.values()) or sum(value.values()) > MAX_TOTAL_POWER:
            raise ValueError("invalid consensus voting power")
    valid_powers(state["engine_powers"])
    if not isinstance(state["validator_history"], dict) or not state["validator_history"]:
        raise ValueError("missing validator history")
    for height, record in state["validator_history"].items():
        if not isinstance(height, str) or not re.fullmatch(r"[1-9][0-9]*", height) or int(height) > state["height"]+UPDATE_DELAY:
            raise ValueError("invalid validator activation height")
        if not isinstance(record, dict) or set(record) != {"powers", "time_ns"}:
            raise ValueError("invalid historical validator record")
        valid_powers(record["powers"])
        if record["time_ns"] is None:
            if int(height) <= state["height"]:
                raise ValueError("missing historical consensus time")
        else:
            number(record["time_ns"], state["time_ns"])
    if state["engine_powers"] != state["validator_history"][str(max(map(int, state["validator_history"])))]["powers"]:
        raise ValueError("latest consensus set mismatch")
    if state["engine_powers"] != powers(state):
        raise ValueError("stake/consensus power mismatch")
    if not isinstance(state["seen_evidence"], dict):
        raise ValueError("invalid evidence deduplication state")
    for identifier, record in state["seen_evidence"].items():
        if not re.fullmatch(r"[0-9a-f]{40}:[12]:[1-9][0-9]*", identifier) or not isinstance(record, dict) or set(record) != {"height", "time_ns"}:
            raise ValueError("invalid evidence identity")
        if not 1 <= number(record["height"]) <= state["height"] or number(record["time_ns"]) > state["time_ns"]:
            raise ValueError("invalid evidence timing")
    return total
