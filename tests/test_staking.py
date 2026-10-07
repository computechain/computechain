"""v3 economics, ownership, liability, scheduling and native ABCI update contracts."""
from copy import deepcopy
import hashlib
import json
import pytest

from computechain.tests.comet_fixtures import genesis, OWNERS, SEEDS, ADDRESSES, PUBS, UNIT
from computechain.blockchain.comet.economics import *
from computechain.blockchain.comet.staking import initial_state, begin_block, finish_block, historical_powers, consensus_key
from computechain.blockchain.comet.transaction import apply, decode, sign_stake, sign_transaction, canonical
from computechain.blockchain.comet.storage import validate_state, Store, state_hash
from computechain.blockchain.comet.node import Application
from computechain.blockchain.comet.proto.tendermint.abci import types_pb2 as pb

CHAIN = "staking-regression-v3"


def transaction(state, kind, i, validator=0, amount=10*UNIT, commission=1000):
    nonce = state["accounts"][ADDRESSES[i]]["nonce"]
    if kind == "STAKE":
        return sign_stake(OWNERS[i], CHAIN, SEEDS[validator], amount, nonce, commission)
    payload = {"validator": PUBS[validator]}
    if kind == "UPDATE_VALIDATOR":
        payload["commission_bps"] = commission
        amount = 0
    return sign_transaction(OWNERS[i], CHAIN, kind, amount, nonce, payload=payload)


def block(state, operations=(), seconds=None, evidence=()):
    h = state["height"]+1
    begin_block(state, h, h*10**9 if seconds is None else seconds*10**9, evidence)
    for operation in operations:
        apply(state, decode(transaction(state, **operation), CHAIN))
    updates = finish_block(state)
    validate_state(state, CHAIN)
    return updates


@pytest.fixture
def state():
    return initial_state(CHAIN, genesis())


def join(state):
    block(state, [{"kind": "STAKE", "i": 4, "validator": 4, "amount": 6000*UNIT},
                  {"kind": "STAKE", "i": 5, "validator": 5, "amount": 6000*UNIT}])


def test_genesis_and_weak_keys_fail_closed():
    with pytest.raises(ValueError, match="v3"):
        initial_state(CHAIN, {"accounts": {}})
    for raw in ("00"*32, "01"+"00"*31, "ff"*32):
        with pytest.raises(ValueError):
            consensus_key(raw)


def test_exact_conservation_above_float_precision(state):
    before = state["supply"]
    delta = 2**80+19
    state["accounts"][ADDRESSES[6]]["balance"] += delta
    state["supply"] += delta
    join(state)
    block(state, [{"kind": "DELEGATE", "i": 6, "amount": 10*UNIT+19}])
    assert state["supply"] == before+delta
    assert state["validators"][PUBS[0]]["delegations"][ADDRESSES[6]]["amount"] == 10*UNIT+19
    assert state["burned"] == (2*GAS["STAKE"]+GAS["DELEGATE"])*MIN_GAS_PRICE


def test_native_addition_removal_and_h_plus_two(state):
    changes = block(state, [{"kind": "STAKE", "i": 4, "validator": 4, "amount": 1000*UNIT}])
    assert changes == [(PUBS[4], 1000)]
    assert PUBS[4] not in historical_powers(state, 2)
    assert historical_powers(state, 3)[PUBS[4]] == 1000
    changes = block(state, [{"kind": "UNSTAKE", "i": 4, "validator": 4, "amount": 1000*UNIT}])
    assert changes == [(PUBS[4], 0)]
    assert PUBS[4] in historical_powers(state, 3)
    assert PUBS[4] not in historical_powers(state, 4)


@pytest.mark.parametrize("kind,i,validator,amount", [
    ("UNSTAKE", 6, 0, UNIT), ("UNDELEGATE", 7, 0, UNIT),
    ("DELEGATE", 0, 0, 10*UNIT), ("DELEGATE", 6, 0, UNIT),
    ("STAKE", 6, 0, 1000*UNIT), ("STAKE", 4, 4, UNIT),
    ("DELEGATE", 6, 0, 10*UNIT)])
def test_failure_preserves_nonce_balance_and_all_stake(state, kind, i, validator, amount):
    begin_block(state, 1, 10**9)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply(state, decode(transaction(state, kind, i, validator, amount), CHAIN))
    assert state == before


def test_possession_binds_chain_owner_and_account_signature(state):
    raw = transaction(state, "STAKE", 4, 4, 1000*UNIT)
    tx = json.loads(raw)
    # Attacker can sign the outer envelope but cannot reuse another owner's proof.
    payload = tx["payload"]
    forged = sign_transaction
    with pytest.raises(ValueError, match="possession"):
        forged(OWNERS[6], CHAIN, "STAKE", 1000*UNIT, 0, payload=payload)
    with pytest.raises(ValueError, match="domain"):
        decode(raw, "other-chain")


def test_delegator_cannot_take_self_stake_and_both_unbond_gates(state):
    join(state)
    block(state, [{"kind": "DELEGATE", "i": 6, "amount": 100*UNIT}])
    block(state, [{"kind": "UNDELEGATE", "i": 6, "amount": 100*UNIT}], seconds=3)
    q = state["unbondings"][0]
    assert q["owner"] == ADDRESSES[6] and q["amount"] == 100*UNIT
    balance = state["accounts"][ADDRESSES[6]]["balance"]
    # Height is sufficient but consensus time has not elapsed.
    while state["height"] < q["release_height"]:
        block(state, seconds=3)
    assert state["unbondings"] and state["accounts"][ADDRESSES[6]]["balance"] == balance
    block(state, seconds=63)
    assert not state["unbondings"]
    assert state["accounts"][ADDRESSES[6]]["balance"] == balance+100*UNIT
    assert state["validators"][PUBS[0]]["self_stake"] == 10_000*UNIT


def test_time_alone_cannot_release_principal(state):
    block(state, [{"kind": "UNSTAKE", "i": 0, "amount": UNIT}])
    block(state, seconds=1000)
    assert state["unbondings"]


def test_last_validator_cannot_exit():
    state = initial_state(CHAIN, genesis(count=1))
    begin_block(state, 1, 10**9)
    before = deepcopy(state)
    with pytest.raises(ValueError, match="empty"):
        apply(state, decode(transaction(state, "UNSTAKE", 0, 0, 10_000*UNIT), CHAIN))
    assert state == before


def test_commission_owner_cooldown_announcement_and_increment(state):
    for _ in range(100):
        block(state)
    block(state, [{"kind": "UPDATE_VALIDATOR", "i": 0, "commission": 1500}])
    val = state["validators"][PUBS[0]]
    assert val["commission_bps"] == 1000 and val["commission_change"]["height"] == 121
    begin_block(state, 102, 102*10**9)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply(state, decode(transaction(state, "UPDATE_VALIDATOR", 0, commission=1500), CHAIN))
    assert state == before
    finish_block(state)
    while state["height"] < 121:
        block(state)
    assert state["validators"][PUBS[0]]["commission_bps"] == 1500
    assert state["validators"][PUBS[0]]["commission_change"] is None


def evidence(state, height=1, validator=0, kind=1, seconds=1):
    old = historical_powers(state, height)
    item = pb.Misbehavior(type=kind, height=height, total_voting_power=sum(old.values()))
    item.time.seconds = seconds
    item.validator.address = hashlib.sha256(bytes.fromhex(PUBS[validator])).digest()[:20]
    item.validator.power = old[PUBS[validator]]
    return item


def test_evidence_slashes_queued_but_not_new_cohorts_and_is_deduplicated(state):
    join(state)
    item = evidence(state)
    block(state, [{"kind": "UNSTAKE", "i": 0, "amount": 1000*UNIT}])
    # Six validators leave room below the concentration limit for a new cohort.
    block(state, [{"kind": "STAKE", "i": 0, "amount": 1000*UNIT}])
    block(state, evidence=[item])
    val = state["validators"][PUBS[0]]
    assert val["tombstoned"] and val["self_stake"] == 9550*UNIT
    assert state["unbondings"][0]["amount"] == 950*UNIT
    assert val["penalties"] == 500*UNIT
    assert PUBS[0] not in state["engine_powers"]
    burned = state["burned"]
    block(state, evidence=[item])
    assert state["burned"] == burned
    with pytest.raises(ValueError, match="tombstoned"):
        apply(state, decode(transaction(state, "STAKE", 0, amount=UNIT), CHAIN))


def test_invalid_evidence_historical_power_and_expiry(state):
    block(state)
    item = evidence(state)
    item.validator.power += 1
    with pytest.raises(ValueError, match="historical"):
        block(deepcopy(state), evidence=[item])
    item = evidence(state)
    while state["height"] < 22:
        block(state)
    # Height window elapsed, time not elapsed: still liable.
    block(deepcopy(state), evidence=[item])
    # Advancing time alone in the proposed block must not reject evidence that
    # native consensus accepted using previous committed time.
    block(deepcopy(state), seconds=40, evidence=[item])
    block(state, seconds=40)
    with pytest.raises(ValueError, match="expired"):
        block(deepcopy(state), seconds=41, evidence=[item])


def test_light_attack_individual_power_may_come_from_conflicting_height(state):
    block(state)
    item = evidence(state, kind=2)
    item.validator.power = 9000
    block(state, evidence=[item])
    assert state["validators"][PUBS[0]]["penalties"] == 500*UNIT
    assert state["validators"][PUBS[0]]["tombstoned"]


def test_history_pruning_requires_both_windows(state):
    join(state)
    for _ in range(30):
        block(state, seconds=1)
    assert "1" in state["validator_history"]  # height alone cannot expire evidence
    block(state, seconds=40)
    assert "1" not in state["validator_history"]
    assert historical_powers(state, state["height"])[PUBS[4]] == 6000


@pytest.mark.parametrize("mutate", [
    lambda s: s["policy"].update(unbond_blocks=0),
    lambda s: s["engine_powers"].update({PUBS[0]: 999}),
    lambda s: s["validators"][PUBS[0]].update(self_stake=True),
    lambda s: s["validators"][PUBS[0]].update(owner=ADDRESSES[1]),
    lambda s: s["validators"][PUBS[0]].update(commission_bps=2001),
])
def test_snapshot_ledger_invariants(state, mutate):
    mutate(state)
    with pytest.raises(ValueError):
        validate_state(state, CHAIN)


def test_abci_update_commit_replay_and_snapshot_contains_liabilities(tmp_path):
    class Context:
        def abort(self, code, text):
            raise RuntimeError(text)
    store = Store(tmp_path / "app", CHAIN, snapshot_interval=1)
    app = Application(store)
    try:
        app.InitChain(pb.RequestInitChain(chain_id=CHAIN, app_state_bytes=canonical(genesis())), Context())
        raw = transaction(store.state, "STAKE", 4, 4, 1000*UNIT)
        req = pb.RequestFinalizeBlock(height=1, hash=b"a"*32, txs=[raw])
        response = app.FinalizeBlock(req, Context())
        assert [(v.pub_key.ed25519.hex(), v.power) for v in response.validator_updates] == [(PUBS[4], 1000)]
        assert PUBS[4] not in store.state["validators"]
        assert app.FinalizeBlock(req, Context()) == response
        app.Commit(pb.RequestCommit(), Context())
        root = state_hash(store.state)
        snap = app.ListSnapshots(pb.RequestListSnapshots(), None).snapshots[0]
        assert snap.format == 3 and snap.hash == root
        store.close()
        store = Store(tmp_path / "app", CHAIN)
        assert state_hash(store.state) == root and store.state["validator_history"]["3"]["powers"][PUBS[4]] == 1000
    finally:
        store.close()


def test_crash_before_stake_commit_replays_identical_update(tmp_path):
    class Context:
        def abort(self, code, text):
            raise RuntimeError(text)
    directory = tmp_path / "app"
    store = Store(directory, CHAIN)
    app = Application(store)
    app.InitChain(pb.RequestInitChain(chain_id=CHAIN, app_state_bytes=canonical(genesis())), Context())
    before = deepcopy(store.state)
    raw = transaction(store.state, "STAKE", 4, 4, 1000*UNIT)
    request = pb.RequestFinalizeBlock(height=1, hash=b"b"*32, txs=[raw])
    response = app.FinalizeBlock(request, Context())
    store.close()  # prepared update must not leak into durable state
    recovered = Store(directory, CHAIN)
    try:
        assert recovered.state == before
        replay = Application(recovered)
        assert replay.FinalizeBlock(request, Context()) == response
        replay.Commit(pb.RequestCommit(), Context())
        assert recovered.state["engine_powers"][PUBS[4]] == 1000
        assert state_hash(recovered.state) == response.app_hash
    finally:
        recovered.close()


@pytest.mark.parametrize("amount", [10**18+19, 2**160+7, 2**250+1])
def test_legacy_decimal_adapter_is_exact_and_conserves_pools(amount):
    from computechain.protocol.config.economic_model import fraction_amount, DEVNET
    assert fraction_amount(amount, 0.7) == amount*7//10
    assert sum(DEVNET.distribute_block_reward(amount).values()) == amount
    fees = DEVNET.distribute_fees(amount)
    assert sum(fees.values()) == amount
