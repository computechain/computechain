"""Public deterministic test keys only; never use these identities on a real network."""
import hashlib
from ecdsa import Ed25519, SigningKey
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

UNIT = 10**18
OWNERS = [hashlib.sha256(f"test-stake-owner-{i}".encode()).digest() for i in range(8)]
SEEDS = [hashlib.sha256(f"test-ed-validator-{i}".encode()).digest() for i in range(8)]
ADDRESSES = [address_from_pubkey(public_key_from_private(key)) for key in OWNERS]
PUBS = [SigningKey.from_string(seed, curve=Ed25519).verifying_key.to_string().hex() for seed in SEEDS]


def genesis(accounts=None, count=4):
    liquid = {owner: {"balance": 100_000*UNIT, "nonce": 0} for owner in ADDRESSES}
    liquid.update(accounts or {})
    return {"schema": 3, "accounts": liquid, "validators": [
        {"pub_key": PUBS[i], "owner": ADDRESSES[i], "self_stake": 10_000*UNIT, "commission_bps": 1000}
        for i in range(count)]}
