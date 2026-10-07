"""Legacy monetary invariants with real signed blocks and integer CPC units."""
import json
import hashlib

import pytest
from computechain.blockchain.core.chain import Blockchain
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.types.validator import Validator
from computechain.protocol.config.params import GAS_PER_TYPE
from computechain.protocol.config.economic_model import ECONOMIC_CONFIG
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

UNIT = 10**18
KEY = hashlib.sha256(b"economic-invariants-public-fixture").digest()
PUB = public_key_from_private(KEY)
ADDRESS = address_from_pubkey(PUB)
VAL = address_from_pubkey(PUB, prefix="cpcvalcons")
GENESIS_SUPPLY = 10000 * UNIT


@pytest.fixture
def chain(tmp_path):
    validator = Validator(address=VAL, pq_pub_key=PUB.hex(), power=1000 * UNIT,
                          self_stake=1000 * UNIT, reward_address=ADDRESS, is_active=True)
    (tmp_path / "genesis.json").write_text(json.dumps({"genesis_time": 1700000000,
        "alloc": {ADDRESS: GENESIS_SUPPLY - validator.self_stake}, "validators": [validator.model_dump()]}))
    chain = Blockchain(str(tmp_path / "chain.sqlite"), enable_snapshots=False)
    yield chain
    chain.db.conn.close()


def signed(kind, amount, nonce=0, payload=None):
    gas = GAS_PER_TYPE[kind]
    tx = Transaction(tx_type=kind, from_address=ADDRESS, amount=amount, nonce=nonce,
                     gas_limit=gas, gas_price=1000, fee=gas*1000,
                     pub_key=PUB.hex(), payload=payload or {})
    tx.sign(KEY)
    return tx


def propose(chain, transactions=()):
    # Build a signed block whose root includes the complete monetary transition.
    from computechain.protocol.types.block import Block, BlockHeader
    from computechain.protocol.crypto.hash import merkle_root
    from computechain.protocol.crypto import pq
    h = chain.height + 1
    value = Block(header=BlockHeader(height=h, prev_hash=chain.last_hash,
        timestamp=chain.genesis_time + h*chain.config.block_time_sec, chain_id=chain.config.chain_id,
        proposer_address=VAL, tx_root=merkle_root([bytes.fromhex(t.hash()) for t in transactions]).hex(),
        state_root="", compute_root=chain.compute_poc_root(transactions),
        gas_used=sum(GAS_PER_TYPE[t.tx_type] for t in transactions), gas_limit=chain.config.block_gas_limit), txs=list(transactions))
    candidate = chain.state.clone()
    for tx in transactions:
        candidate.apply_transaction(tx, current_height=h)
    chain.finalize_state(value, candidate)
    value.header.state_root = candidate.compute_state_root()
    value.pq_signature = pq.sign(bytes.fromhex(value.hash()), KEY).hex()
    return value


def test_supply_conservation(chain):
    stake = signed(TxType.STAKE, 1000 * UNIT, payload={"pub_key": PUB.hex()})
    for i in range(5):
        chain.add_block(propose(chain, [stake] if i == 0 else []))
        state = chain.state
        accounts = state.db.get_state_by_prefix("acc:")
        from computechain.blockchain.core.accounts import Account
        balances = sum(Account.model_validate_json(v).balance for v in accounts.values())
        locked = sum(v.self_stake + v.total_delegated for v in state.get_all_validators())
        unbonding = sum(sum(e.amount for e in Account.model_validate_json(v).unbonding_delegations) for v in accounts.values())
        assert state.get_total_supply(GENESIS_SUPPLY) == balances + locked + unbonding


def test_non_negative_balances(chain):
    for _ in range(3):
        chain.add_block(propose(chain))
    before = chain.state.compute_state_root()
    with pytest.raises(ValueError):
        chain.state.apply_transaction(signed(TxType.STAKE, -1, payload={"pub_key": PUB.hex()}))
    assert chain.state.compute_state_root() == before
    assert all(a.balance >= 0 for a in chain.state._accounts.values())
    assert all(v.self_stake >= 0 and v.total_delegated >= 0 for v in chain.state.get_all_validators())


def test_staking_limits_enforced(chain):
    # A one-validator genesis already exceeds the configured cap: a delegation
    # must be rejected, not special-cased to pass a broken fixture.
    before = chain.state.compute_state_root()
    with pytest.raises(ValueError, match="voting power"):
        chain.state.apply_transaction(signed(TxType.DELEGATE, 100 * UNIT, payload={"validator": VAL}))
    assert chain.state.compute_state_root() == before
    assert ECONOMIC_CONFIG.max_validators_per_delegator == 10
    assert ECONOMIC_CONFIG.max_validator_power_share == 0.20
