"""Negative regressions for the reviewed legacy defects and ABCI trust boundaries.

Keys are deterministic public test fixtures only. All storage uses pytest tmp_path.
The legacy engine remains a quarantined prototype, not a production BFT network.
"""
from copy import deepcopy
import hashlib
import json
import os
import sqlite3
import asyncio
import gzip
from types import SimpleNamespace

import pytest
from ecdsa import SECP256k1

from computechain.blockchain.core.chain import Blockchain
from computechain.blockchain.core.state import AccountState
from computechain.blockchain.core.accounts import Account
from computechain.blockchain.storage.db import StorageDB
from computechain.blockchain.snapshot.snapshot_manager import SnapshotManager
from computechain.blockchain.snapshot.types import Snapshot
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.types.block import Block, BlockHeader
from computechain.protocol.types.validator import Validator, Delegation, UndelegationEntry
from computechain.protocol.config.params import GAS_PER_TYPE
from computechain.protocol.crypto.keys import public_key_from_private, verify, sign
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.protocol.crypto.hash import merkle_root
from computechain.protocol.crypto import pq
from computechain.cli.keystore import KeyStore
from computechain.blockchain.comet.storage import Store, state_hash, validate_state
from computechain.blockchain.comet.node import Application, validate_listen
from computechain.blockchain.comet.transaction import canonical
from computechain.blockchain.comet.proto.tendermint.abci import types_pb2 as pb

UNIT = 10**18
OWNER_KEY = hashlib.sha256(b"security-regression-owner-only").digest()
OTHER_KEY = hashlib.sha256(b"security-regression-attacker-only").digest()
OWNER_PUB = public_key_from_private(OWNER_KEY).hex()
OTHER_PUB = public_key_from_private(OTHER_KEY).hex()
OWNER = address_from_pubkey(bytes.fromhex(OWNER_PUB))
OTHER = address_from_pubkey(bytes.fromhex(OTHER_PUB))
VAL = address_from_pubkey(bytes.fromhex(OWNER_PUB), prefix="cpcvalcons")


def tx(kind=TxType.TRANSFER, *, attacker=False, amount=1, to=OTHER, payload=None, **changes):
    gas = GAS_PER_TYPE[kind]
    value = Transaction(tx_type=kind, from_address=OTHER if attacker else OWNER,
        to_address=to, amount=amount, nonce=0, gas_price=1000, gas_limit=gas,
        fee=gas * 1000, pub_key=OTHER_PUB if attacker else OWNER_PUB, payload=payload or {})
    for key, val in changes.items():
        setattr(value, key, val)
    value.sign(OTHER_KEY if attacker else OWNER_KEY)
    return value


def validator():
    return Validator(address=VAL, pq_pub_key=OWNER_PUB, power=100 * UNIT,
                     self_stake=100 * UNIT, reward_address=OWNER, is_active=True)


@pytest.fixture
def state():
    db = StorageDB(":memory:")
    state = AccountState(db)
    for address in (OWNER, OTHER):
        state.set_account(Account(address=address, balance=1000 * UNIT))
    state.set_validator(validator())
    yield state
    db.conn.close()


@pytest.fixture
def chain(tmp_path):
    (tmp_path / "genesis.json").write_text(json.dumps({"genesis_time": 1700000000,
        "alloc": {OWNER: 1000 * UNIT, OTHER: 1000 * UNIT}, "validators": [validator().model_dump()]}))
    chain = Blockchain(str(tmp_path / "chain.sqlite"), enable_snapshots=False)
    yield chain
    chain.db.conn.close()


def block(chain, txs=()):
    height = chain.height + 1
    header = BlockHeader(height=height, prev_hash=chain.last_hash,
        timestamp=chain.genesis_time + height * chain.config.block_time_sec,
        chain_id=chain.config.chain_id, proposer_address=VAL,
        tx_root=merkle_root([bytes.fromhex(t.hash()) for t in txs]).hex(), state_root="",
        compute_root=chain.compute_poc_root(txs), gas_used=sum(GAS_PER_TYPE[t.tx_type] for t in txs),
        gas_limit=chain.config.block_gas_limit)
    value = Block(header=header, txs=list(txs))
    candidate = chain.state.clone()
    for t in txs:
        candidate.apply_transaction(t, current_height=height)
    chain.finalize_state(value, candidate)
    header.state_root = candidate.compute_state_root()
    resign(value)
    return value


def resign(value):
    value.pq_signature = pq.sign(bytes.fromhex(value.header.hash()), OWNER_KEY).hex()


def test_f01_attacker_cannot_unstake_and_failed_operation_is_atomic(state):
    before = state.compute_state_root()
    with pytest.raises(ValueError, match="Only validator owner"):
        state.apply_transaction(tx(TxType.UNSTAKE, attacker=True, amount=10 * UNIT, payload={"pub_key": OWNER_PUB}))
    assert state.compute_state_root() == before


def test_owner_cannot_withdraw_delegators_stake(state):
    val = state.get_validator(VAL)
    val.total_delegated = 90 * UNIT
    val.self_stake = 10 * UNIT
    val.delegations = [Delegation(delegator=OTHER, validator=VAL, amount=90 * UNIT, created_height=0)]
    before = state.compute_state_root()
    with pytest.raises(ValueError, match="Insufficient stake"):
        state.apply_transaction(tx(TxType.UNSTAKE, amount=11 * UNIT, payload={"pub_key": OWNER_PUB}))
    assert state.compute_state_root() == before
    state.apply_transaction(tx(TxType.UNSTAKE, amount=10 * UNIT, payload={"pub_key": OWNER_PUB}))
    val = state.get_validator(VAL)
    assert val.self_stake == 0 and val.power == val.total_delegated == 90 * UNIT


def test_other_account_cannot_gain_ownership_by_staking(state):
    before = state.compute_state_root()
    with pytest.raises(ValueError, match="Only validator owner"):
        state.apply_transaction(tx(TxType.STAKE, attacker=True, amount=UNIT, payload={"pub_key": OWNER_PUB}))
    assert state.compute_state_root() == before


def test_f02_amount_fee_collision_no_longer_validates(state):
    original = tx(amount=1, fee=234567890)
    altered = original.model_copy(update={"amount": 12, "fee": 34567890})
    assert original.hash() != altered.hash()
    assert not verify(bytes.fromhex(altered.hash()), bytes.fromhex(altered.signature), bytes.fromhex(OWNER_PUB))
    before = state.compute_state_root()
    with pytest.raises(ValueError, match="signature"):
        state.apply_transaction(altered)
    assert state.compute_state_root() == before


def test_signature_cannot_replay_across_chains_or_versions(state):
    original = tx()
    for changes in ({"chain_id": "other-chain"}, {"version": 1}):
        altered = original.model_copy(update=changes)
        assert altered.hash() != original.hash()
        with pytest.raises(ValueError, match="version or chain_id"):
            state.apply_transaction(altered)


def test_signature_length_and_high_s_are_rejected():
    digest = hashlib.sha256(b"canonical-signature-regression").digest()
    signature = sign(digest, OWNER_KEY)
    assert signature == sign(digest, OWNER_KEY)
    assert verify(digest, signature, bytes.fromhex(OWNER_PUB))
    high_s = signature[:32] + (SECP256k1.order - int.from_bytes(signature[32:], "big")).to_bytes(32, "big")
    for bad in (signature[:-1], signature + b"\x00", high_s):
        assert not verify(digest, bad, bytes.fromhex(OWNER_PUB))


def test_f03_clones_isolate_delegations_rewards_and_queues(state):
    val = state.get_validator(VAL)
    val.delegations.append(Delegation(delegator=OTHER, validator=VAL, amount=10, created_height=0))
    account = state.get_account(OWNER)
    account.reward_history[0] = 100
    account.unbonding_delegations.append(UndelegationEntry(amount=10, completion_height=100, validator=VAL))
    clone = state.clone()
    clone.get_validator(VAL).delegations[0].amount = 1
    clone.get_account(OWNER).reward_history[0] = 1
    clone.get_account(OWNER).unbonding_delegations[0].amount = 1
    assert val.delegations[0].amount == 10 and account.reward_history[0] == 100
    assert account.unbonding_delegations[0].amount == 10


@pytest.mark.parametrize("kind,payload,to", [(TxType.TRANSFER, {}, None),
    (TxType.STAKE, {}, OTHER), (TxType.DELEGATE, {"validator": "missing"}, OTHER),
    (TxType.UNDELEGATE, {"validator": VAL}, OTHER),
    (TxType.UPDATE_VALIDATOR, {"pub_key": OWNER_PUB, "name": "x" * 100}, OTHER)])
def test_f04_routing_failures_do_not_change_state(state, kind, payload, to):
    before = state.compute_state_root()
    with pytest.raises(ValueError):
        state.apply_transaction(tx(kind, payload=payload, to=to))
    assert state.compute_state_root() == before


@pytest.mark.parametrize("field,value,error", [("tx_root", "f" * 64, "tx_root"),
    ("chain_id", "other-network", "chain_id"), ("state_root", "0" * 64, "State root"),
    ("version", 1, "version")])
def test_f05_f06_reject_signed_bad_commitments_without_changes(chain, field, value, error):
    proposed = block(chain)
    setattr(proposed.header, field, value)
    resign(proposed)
    root = chain.state.compute_state_root()
    with pytest.raises(ValueError, match=error):
        chain.add_block(proposed)
    assert chain.height == -1 and chain.db.get_last_block() is None
    assert chain.state.compute_state_root() == root


def test_unsigned_bootstrap_is_not_a_consensus_rule(chain):
    proposed = block(chain)
    chain.consensus.update_validator_set([])
    with pytest.raises(ValueError, match="unsigned bootstrap"):
        chain.add_block(proposed)
    assert chain.height == -1


def test_block_header_signature_commits_optional_proof_fields():
    a = BlockHeader(height=0, prev_hash="0" * 64, timestamp=0, chain_id="test",
                    proposer_address=VAL, tx_root="0" * 64, state_root="0" * 64)
    assert a.hash() != a.model_copy(update={"zk_state_proof_hash": "f" * 64}).hash()


def test_f07_header_matches_final_durable_state_and_strict_replay(chain):
    for _ in range(3):
        proposed = block(chain)
        chain.add_block(proposed)
        assert proposed.header.state_root == chain.state.compute_state_root()
    root = chain.state.compute_state_root()
    chain.rebuild_state_from_blocks()
    assert chain.height == 2 and chain.state.compute_state_root() == root


def test_epoch_transition_is_in_final_root_and_replay(chain):
    chain.config = chain.config.model_copy() if hasattr(chain.config, "model_copy") else deepcopy(chain.config)
    chain.config.epoch_length_blocks = 2
    for _ in range(4):
        proposed = block(chain)
        chain.add_block(proposed)
        assert proposed.header.state_root == chain.state.compute_state_root()
    assert chain.state.epoch_index == 2
    root = chain.state.compute_state_root()
    chain.rebuild_state_from_blocks()
    assert chain.state.compute_state_root() == root


@pytest.mark.parametrize("field", ["epoch_index", "total_burned", "total_minted"])
def test_f08_economic_metadata_is_committed(state, field):
    root = state.compute_state_root()
    setattr(state, field, getattr(state, field) + 1)
    assert root != state.compute_state_root()


def test_performance_fields_are_committed(state):
    root = state.compute_state_root()
    state.get_validator(VAL).blocks_expected += 1
    assert state.compute_state_root() != root


def test_disk_failure_does_not_publish_partial_state_block_or_index(chain):
    proposed = block(chain, [tx()])
    root = chain.state.compute_state_root()
    durable = chain.db.get_state_by_prefix("")
    chain.db.conn.execute("CREATE TRIGGER injected BEFORE INSERT ON tx_index BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        chain.add_block(proposed)
    assert chain.height == -1 and chain.state.compute_state_root() == root
    assert chain.db.get_last_block() is None and chain.db.get_state_by_prefix("") == durable
    chain.db.conn.execute("DROP TRIGGER injected")
    assert chain.add_block(proposed)


def test_invalid_replay_preserves_original_state_and_tip(chain):
    proposed = block(chain)
    chain.add_block(proposed)
    root = chain.state.compute_state_root()
    durable = chain.db.get_state_by_prefix("")
    proposed.header.state_root = "0" * 64
    resign(proposed)
    chain.db.save_block(0, proposed.hash(), proposed.model_dump_json())
    with pytest.raises(ValueError, match="State root"):
        chain.rebuild_state_from_blocks()
    assert chain.height == 0 and chain.state.compute_state_root() == root
    assert chain.db.get_state_by_prefix("") == durable


def test_v1_history_is_not_silently_reinterpreted(chain):
    proposed = block(chain)
    data = proposed.model_dump()
    del data["header"]["version"]
    chain.db.save_block(0, "0" * 64, json.dumps(data))
    path = str(chain.db.conn.execute("PRAGMA database_list").fetchone()[2])
    with pytest.raises(RuntimeError, match="explicit migration"):
        Blockchain(path, enable_snapshots=False)
    assert chain.db.get_last_block()[2] == json.dumps(data)


def snapshot(state):
    value = Snapshot(network_id="devnet", height=10, epoch_index=state.epoch_index,
        timestamp="2026-10-07T00:00:00Z", total_burned=state.total_burned, total_minted=state.total_minted,
        accounts={OWNER: state.get_account(OWNER).model_dump_json()}, validators={})
    value.hash = value.calculate_hash()
    return value


def test_f09_snapshot_replaces_old_keys_only_after_trusted_root_check(state, tmp_path):
    state.persist()
    value = snapshot(state)
    db = StorageDB(":memory:")
    target = AccountState(db)
    target.set_account(state.get_account(OWNER).model_copy(deep=True))
    root = target.compute_state_root()
    db.conn.close()
    manager = SnapshotManager(str(tmp_path))
    with pytest.raises(ValueError, match="independently trusted"):
        manager.apply_snapshot(value, state)
    with pytest.raises(ValueError, match="trusted state root"):
        manager.apply_snapshot(value, state, trusted_state_root="0" * 64)
    assert state.get_validator(VAL) is not None
    manager.apply_snapshot(value, state, trusted_state_root=root)
    assert state.get_validator(VAL) is None and state.db.get_state("acc:" + OTHER) is None
    assert state.compute_state_root() == root


def test_unanchored_snapshot_bootstrap_is_disabled(chain):
    chain.snapshot_manager = object()
    with pytest.raises(ValueError, match="Unanchored"):
        chain.load_from_snapshot(100)


def test_unbonding_does_not_overwrite_cached_nonce_or_balance(state):
    owner = state.get_account(OWNER)
    owner.unbonding_delegations = [UndelegationEntry(amount=100, completion_height=10, validator=VAL)]
    state.persist()
    state.apply_transaction(tx())
    expected = state.get_account(OWNER).balance + 100
    state.process_unbonding_queue(10)
    assert state.get_account(OWNER).balance == expected and state.get_account(OWNER).nonce == 1
    assert not state.get_account(OWNER).unbonding_delegations
    state.process_unbonding_queue(10)
    assert state.get_account(OWNER).balance == expected


def test_slashing_burns_and_reduces_all_stake_components(chain):
    val = chain.state.get_validator(VAL)
    val.self_stake = 60 * UNIT
    val.total_delegated = 40 * UNIT
    val.delegations = [Delegation(delegator=OTHER, validator=VAL, amount=40 * UNIT, created_height=0)]
    before = val.power
    chain._jail_validator(val, chain.state, 10)
    assert before - val.power == chain.state.total_burned
    assert val.self_stake + val.total_delegated == val.power
    assert val.total_delegated == sum(d.amount for d in val.delegations)


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), 0.21, 0.15])
def test_commission_limit_and_unimplemented_schedule_fail_closed(state, rate):
    before = state.compute_state_root()
    value = tx(TxType.UPDATE_VALIDATOR, payload={"pub_key": OWNER_PUB})
    value.payload["commission_rate"] = rate
    with pytest.raises(ValueError):
        state.apply_transaction(value, skip_crypto_check=True)
    assert state.compute_state_root() == before


def test_mock_zk_and_public_key_hash_signature_are_not_proofs():
    from computechain.blockchain.core.zk_verification import ZKVerifier
    verifier = ZKVerifier()
    proof = canonical({"version": verifier.config.weight_calculation_version, "public_output": 100.0})
    forged = hashlib.sha512(bytes.fromhex(OWNER_PUB) + b"100.0||" + proof).digest()
    assert not verifier.verify_miner_weight_submission(OWNER, 100.0, proof, forged, bytes.fromhex(OWNER_PUB))[0]
    assert not verifier._verify_zk_proof(100.0, proof)


def test_claimed_miner_weight_cannot_mint_unverified_payout(state):
    from computechain.blockchain.core.miner_rewards import MinerRewardDistributor, MinerSubmission
    before = state.compute_state_root()
    with pytest.raises(ValueError, match="Miner payouts disabled"):
        MinerRewardDistributor().distribute_miner_rewards(UNIT, [MinerSubmission(OTHER, 100.0)], state)
    assert before == state.compute_state_root()


def test_snapshot_decompression_is_bounded(tmp_path, monkeypatch):
    from computechain.blockchain.snapshot import snapshot_manager as module
    monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 1000)
    manager = SnapshotManager(str(tmp_path))
    manager._get_snapshot_path(10).write_bytes(gzip.compress(b"x" * 100000))
    with pytest.raises(ValueError, match="decompression limit"):
        manager.load_snapshot(10)


def test_snapshot_commit_failure_rolls_back_storage_and_cache(state, tmp_path):
    state.persist()
    before = state.compute_state_root()
    durable = state.db.get_state_by_prefix("")
    value = snapshot(state)
    db = StorageDB(":memory:")
    target = AccountState(db)
    target.set_account(state.get_account(OWNER).model_copy(deep=True))
    root = target.compute_state_root()
    db.conn.close()
    state.db.conn.execute("CREATE TRIGGER injected BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT, 'snapshot write failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="snapshot write failure"):
        SnapshotManager(str(tmp_path)).apply_snapshot(value, state, trusted_state_root=root)
    assert state.compute_state_root() == before and state.db.get_state_by_prefix("") == durable


def test_legacy_node_requires_explicit_unsafe_opt_in():
    from computechain.blockchain.cli.node_cli import run_node_async
    with pytest.raises(RuntimeError, match="not BFT-safe"):
        asyncio.run(run_node_async(SimpleNamespace()))


def test_legacy_untrusted_snapshot_chunks_do_not_allocate_buffers():
    from computechain.blockchain.p2p.node import P2PNode
    node = P2PNode("127.0.0.1", 9000, [], "devnet")
    asyncio.run(node.handle_snapshot_chunk(None, {"total_chunks": 10**12, "data_b64": "junk"}))
    assert node._snapshot_buffers == {}


def test_legacy_unterminated_p2p_frame_is_bounded():
    from computechain.blockchain.p2p.node import P2PNode
    node = P2PNode("127.0.0.1", 9000, [], "devnet")

    class Reader:
        calls = 0
        async def read(self, size):
            self.calls += 1
            assert self.calls < 500
            return b"x" * size

    class Writer:
        closed = False
        def close(self):
            self.closed = True
        async def wait_closed(self):
            pass

    reader, writer = Reader(), Writer()
    asyncio.run(node.read_loop(reader, writer))
    assert writer.closed and reader.calls < 420


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", "..", "", "a/b", "a\\b", "x" * 65])
def test_keystore_path_traversal_is_rejected(tmp_path, name):
    keys = KeyStore(str(tmp_path / "keys"))
    for operation in (keys.get_key, keys.create_key, keys.delete_key):
        with pytest.raises(ValueError, match="Key name"):
            operation(name)


def test_keystore_secure_creation_and_no_symlink_overwrite(tmp_path):
    keys = KeyStore(str(tmp_path / "keys"))
    keys.create_key("safe")
    assert (tmp_path / "keys/safe.json").stat().st_mode & 0o777 == 0o600
    outside = tmp_path / "outside.json"
    outside.write_text("do not overwrite")
    (tmp_path / "keys/link.json").symlink_to(outside)
    assert keys.get_key("link") is None
    with pytest.raises(FileExistsError):
        keys.create_key("link")
    assert outside.read_text() == "do not overwrite"


def test_node_key_creation_is_private_and_does_not_overwrite(tmp_path):
    from computechain.blockchain.cli.node_cli import save_private_key
    path = tmp_path / "validator_key.hex"
    save_private_key(path, OWNER_KEY.hex())
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        save_private_key(path, OTHER_KEY.hex())
    assert path.read_text() == OWNER_KEY.hex()


@pytest.fixture
def comet(tmp_path):
    from computechain.tests.comet_fixtures import genesis
    from computechain.blockchain.comet.staking import initial_state
    store = Store(tmp_path / "app", "security-test")
    state = initial_state("security-test", genesis({OWNER: {"balance": UNIT, "nonce": 0}}))
    store.commit(state)
    yield Application(store)
    store.close()


def test_comet_same_height_conflict_and_height_jump_are_rejected(comet):
    before = comet.store.clone()
    changed = deepcopy(before)
    changed["accounts"][OWNER]["nonce"] += 1
    with pytest.raises(ValueError, match="same height"):
        comet.store.commit(changed)
    changed["height"] = 2
    with pytest.raises(ValueError, match="advance by one"):
        comet.store.commit(changed)
    assert comet.store.state == before


@pytest.mark.parametrize("changes", [{"schema": 2.0}, {"height": 2**63}, {"last_block_hash": "AB" * 32},
    {"last_block_hash": " 0" * 32}])
def test_comet_state_schema_and_hash_encoding_are_strict(comet, changes):
    changed = comet.store.clone()
    changed.update(changes)
    with pytest.raises(ValueError):
        validate_state(changed, comet.store.chain_id)


def test_comet_corrupt_json_does_not_leak_writer_lock(comet):
    directory = comet.store.directory
    comet.store.conn.execute("UPDATE committed SET state=?", (b"not json",))
    comet.store.conn.commit()
    comet.store.close()
    for _ in range(2):
        with pytest.raises(ValueError):
            Store(directory, "security-test")


@pytest.mark.parametrize("listen", ["0.0.0.0:26658", "[::]:26658", "192.0.2.1:26658", "localhost:26658", "127.0.0.1:0", "127.0.0.1:65536"])
def test_comet_abci_cannot_be_exposed_as_public_write_api(listen):
    with pytest.raises(ValueError, match="loopback"):
        validate_listen(listen)


def test_comet_loopback_listeners_are_allowed():
    assert validate_listen("127.0.0.1:26658")
    assert validate_listen("[::1]:26658")
