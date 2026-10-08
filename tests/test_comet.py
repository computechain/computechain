"""Consensus application, durable recovery and adversarial snapshot regression tests."""
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from computechain.blockchain.comet.node import Application
from computechain.blockchain.comet.proto.tendermint.abci import types_pb2 as pb
from computechain.blockchain.comet.storage import Store, state_hash, CHUNK_SIZE
from computechain.blockchain.comet.transaction import canonical, decode, sign_transfer, GAS, MIN_GAS_PRICE
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.tests.comet_fixtures import genesis as stake_genesis

CHAIN = "cpc-comet-test-1"
KEY = hashlib.sha256(b"comet-unit-test-only").digest()
SENDER = address_from_pubkey(public_key_from_private(KEY))
RECIPIENT = address_from_pubkey(public_key_from_private(hashlib.sha256(b"comet-unit-recipient").digest()))


class Context:
    def abort(self, status, message):
        raise RuntimeError(message)


@pytest.fixture
def app(tmp_path):
    store = Store(tmp_path / "app", CHAIN, snapshot_interval=1)
    app = Application(store)
    genesis = stake_genesis({SENDER: {"balance": 1000 * 10**18, "nonce": 0}})
    app.InitChain(pb.RequestInitChain(chain_id=CHAIN, initial_height=1, app_state_bytes=canonical(genesis)), Context())
    yield app
    app._clear_restore()
    store.close()


def tx(nonce=0, amount=10**18, chain=CHAIN):
    return sign_transfer(KEY, chain, RECIPIENT, amount, nonce)


def finalize(app, txs=()):
    height = app.store.state["height"] + 1
    return app.FinalizeBlock(pb.RequestFinalizeBlock(height=height, hash=hashlib.sha256(str(height).encode()).digest(), txs=list(txs)), Context())


def test_canonical_domain_and_signature():
    signed = tx()
    assert decode(signed, CHAIN)["from"] == SENDER
    with pytest.raises(ValueError, match="domain"):
        decode(signed, "other-chain")
    changed = json.loads(signed)
    changed["amount"] = "12"
    with pytest.raises(ValueError, match="signature"):
        decode(canonical(changed), CHAIN)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra="unexpected"), lambda d: d.update(amount="01"),
    lambda d: d.update(amount="-1"), lambda d: d.update(amount="0"),
    lambda d: d.update(amount="9" * 100), lambda d: d.update(gas_price="1"),
    lambda d: d.update(nonce=True), lambda d: d.update(nonce=-1),
    lambda d: d.update(gas_limit=1), lambda d: d.update(signature="00" * 64),
    lambda d: d.update(type="UNSTAKE"), lambda d: d.update(pub_key="00" * 33),
    lambda d: d.update(to="cpc1invalid"), lambda d: d.update(version=True),
])
def test_invalid_envelopes(mutate):
    value = json.loads(tx())
    mutate(value)
    with pytest.raises(ValueError):
        decode(canonical(value), CHAIN)


def test_wire_noncanonical_duplicate_or_oversized():
    with pytest.raises(ValueError):
        decode(json.dumps(json.loads(tx()), indent=2).encode(), CHAIN)
    with pytest.raises(ValueError):
        decode(b'{"amount":"1","amount":"2"}', CHAIN)
    with pytest.raises(ValueError):
        decode(b" " * 4097, CHAIN)


def test_checktx_and_proposal_never_change_committed_state(app):
    original = deepcopy(app.store.state)
    assert app.CheckTx(pb.RequestCheckTx(tx=tx()), None).code == 0
    proposal = app.PrepareProposal(pb.RequestPrepareProposal(height=1, txs=[b"invalid", tx()], max_tx_bytes=10000), None)
    assert list(proposal.txs) == [tx()]
    assert app.ProcessProposal(pb.RequestProcessProposal(height=1, txs=[tx()]), None).status == pb.ResponseProcessProposal.ACCEPT
    assert app.store.state == original


def test_prepare_filters_invalid_without_poisoning_next_tx(app):
    proposal = app.PrepareProposal(pb.RequestPrepareProposal(height=1, txs=[tx(amount=10**27), tx()], max_tx_bytes=10000), None)
    assert list(proposal.txs) == [tx()]
    assert app.ProcessProposal(pb.RequestProcessProposal(height=1, txs=[tx(), tx()]), None).status == pb.ResponseProcessProposal.REJECT


def test_future_nonce_and_insufficient_balance(app):
    assert app.CheckTx(pb.RequestCheckTx(tx=tx(1)), None).code == 0
    assert app.CheckTx(pb.RequestCheckTx(tx=tx(65)), None).code != 0
    assert app.CheckTx(pb.RequestCheckTx(tx=tx(amount=10**27)), None).code != 0
    assert app.store.state["accounts"][SENDER]["nonce"] == 0


def test_finalize_then_atomic_commit_and_receipt(app):
    original = deepcopy(app.store.state)
    response = finalize(app, [tx()])
    assert app.Info(pb.RequestInfo(), None).last_block_height == 0
    assert app.store.state == original
    app.Commit(pb.RequestCommit(), None)
    assert app.store.state["height"] == 1
    assert app.store.state["accounts"][RECIPIENT]["balance"] == 10**18
    assert app.store.state["burned"] == GAS * MIN_GAS_PRICE
    assert state_hash(app.store.state) == response.app_hash
    assert app.store.conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
    app.store.close()
    reopened = Store(app.store.directory, CHAIN)
    assert reopened.state == app.store.state
    reopened.close()


def test_crash_before_commit_preserves_previous_state(app):
    previous = deepcopy(app.store.state)
    finalize(app, [tx()])
    app.store.close()
    recovered = Store(app.store.directory, CHAIN)
    assert recovered.state == previous
    replay = Application(recovered)
    replayed = finalize(replay, [tx()])
    replay.Commit(pb.RequestCommit(), None)
    assert state_hash(recovered.state) == replayed.app_hash
    recovered.close()


def test_finalize_is_idempotent_before_commit(app):
    request = pb.RequestFinalizeBlock(height=1, hash=b"a" * 32, txs=[tx()])
    first = app.FinalizeBlock(request, Context())
    assert app.FinalizeBlock(request, Context()) == first
    with pytest.raises(RuntimeError):
        app.FinalizeBlock(pb.RequestFinalizeBlock(height=1, hash=b"b" * 32), Context())


def test_failed_tx_changes_no_accounts(app):
    before = deepcopy(app.store.state["accounts"])
    response = finalize(app, [tx(amount=10**27)])
    assert response.tx_results[0].code != 0
    app.Commit(pb.RequestCommit(), None)
    assert app.store.state["accounts"] == before
    assert app.store.state["burned"] == 0


def test_restart_wrong_chain_rejected(app):
    app.store.close()
    with pytest.raises(ValueError, match="schema or chain"):
        Store(app.store.directory, "other-chain")


def snapshot_from(app):
    finalize(app, [tx()])
    app.Commit(pb.RequestCommit(), None)
    listing = app.ListSnapshots(pb.RequestListSnapshots(), None)
    snapshot = listing.snapshots[0]
    chunks = [app.LoadSnapshotChunk(pb.RequestLoadSnapshotChunk(height=snapshot.height, format=snapshot.format, chunk=i), None).chunk for i in range(snapshot.chunks)]
    return snapshot, chunks


def test_verified_snapshot_matches_full_execution(app, tmp_path):
    snap, chunks = snapshot_from(app)
    target = Store(tmp_path / "follower", CHAIN)
    follower = Application(target)
    try:
        assert follower.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap, app_hash=state_hash(app.store.state)), None).result == pb.ResponseOfferSnapshot.ACCEPT
        for i, chunk in enumerate(chunks):
            assert follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=i, chunk=chunk, sender="peer"), None).result == pb.ResponseApplySnapshotChunk.ACCEPT
        assert target.state == app.store.state
        assert follower.Info(pb.RequestInfo(), None).last_block_app_hash == state_hash(app.store.state)
        target.close()
        reopened = Store(target.directory, CHAIN)
        assert reopened.state == target.state
        reopened.close()
    finally:
        follower._clear_restore()
        target.close()


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_snapshot_tamper_or_wrong_trusted_root_cannot_replace_state(app, tmp_path, wrong_hash):
    snap, chunks = snapshot_from(app)
    target = Store(tmp_path / "reject", CHAIN)
    follower = Application(target)
    try:
        trusted = b"0" * 32 if wrong_hash else state_hash(app.store.state)
        offered = follower.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap, app_hash=trusted), None)
        if wrong_hash:
            assert offered.result == pb.ResponseOfferSnapshot.REJECT
            assert follower.restore is None and target.state is None
            return
        assert offered.result == pb.ResponseOfferSnapshot.ACCEPT
        if not wrong_hash:
            chunks[0] = chunks[0].replace(b'"burned":21000000', b'"burned":21000001')
        for i, chunk in enumerate(chunks):
            result = follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=i, chunk=chunk), None)
        assert result.result == pb.ResponseApplySnapshotChunk.REJECT_SNAPSHOT
        assert target.state is None
    finally:
        follower._clear_restore()
        target.close()


def test_snapshot_limits_and_no_live_rollback(app):
    snap, chunks = snapshot_from(app)
    assert app.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap, app_hash=state_hash(app.store.state)), None).result == pb.ResponseOfferSnapshot.REJECT
    bad = pb.Snapshot(height=1, format=3, chunks=10000, hash=b"a" * 32)
    # even an empty app rejects the unbounded chunk count.
    app.store.state = None
    assert app.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=bad, app_hash=b"b" * 32), None).result == pb.ResponseOfferSnapshot.REJECT


def test_query_refuses_unimplemented_proofs(app):
    assert app.Query(pb.RequestQuery(path="/state", prove=True), None).code != 0
    assert app.Query(pb.RequestQuery(path="/state", height=999), None).code != 0


def test_state_metadata_is_committed(app):
    first = state_hash(app.store.state)
    for key in ("burned", "supply", "height", "gas_price_min"):
        changed = deepcopy(app.store.state)
        changed[key] += 1
        assert state_hash(changed) != first


def test_two_writers_cannot_open_same_directory(app):
    with pytest.raises(RuntimeError, match="already has a writer"):
        Store(app.store.directory, CHAIN)


def test_commit_failure_rolls_back_state_and_receipts_atomically(app):
    original = deepcopy(app.store.state)
    app.store.conn.execute("CREATE TRIGGER simulate_disk_error BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT, 'injected write failure'); END")
    finalize(app, [tx()])
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        app.Commit(pb.RequestCommit(), None)
    assert app.store.state == original
    durable = json.loads(app.store.conn.execute("SELECT state FROM committed").fetchone()[0])
    assert durable == original
    assert app.store.conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
    app.store.conn.execute("DROP TRIGGER simulate_disk_error")
    app.Commit(pb.RequestCommit(), None)
    assert app.store.state["height"] == 1


def test_snapshot_multichunk_reordering_duplicates_and_bad_index(app, tmp_path, monkeypatch):
    from computechain.blockchain.comet import node
    monkeypatch.setattr(node, "CHUNK_SIZE", 100)
    snap, chunks = snapshot_from(app)
    assert len(chunks) > 1
    target = Store(tmp_path / "chunks", CHAIN)
    follower = Application(target)
    try:
        assert follower.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap, app_hash=state_hash(app.store.state)), None).result == pb.ResponseOfferSnapshot.ACCEPT
        invalid = follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=snap.chunks, chunk=b"bad", sender="bad-peer"), None)
        assert invalid.result == pb.ResponseApplySnapshotChunk.RETRY
        last = len(chunks) - 1
        assert follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=last, chunk=chunks[last]), None).result == pb.ResponseApplySnapshotChunk.ACCEPT
        assert follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=last, chunk=chunks[last]), None).result == pb.ResponseApplySnapshotChunk.ACCEPT
        conflict = follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=last, chunk=b"bad", sender="bad-peer"), None)
        assert conflict.result == pb.ResponseApplySnapshotChunk.RETRY
        assert target.state is None
        # A conflict invalidates that index: a refetch must be able to replace it.
        assert follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=last, chunk=chunks[last]), None).result == pb.ResponseApplySnapshotChunk.ACCEPT
        for i in range(last):
            assert follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=i, chunk=chunks[i]), None).result == pb.ResponseApplySnapshotChunk.ACCEPT
        assert target.state == app.store.state
    finally:
        follower._clear_restore()
        target.close()


def test_snapshot_commit_io_failure_keeps_durable_state_and_can_retry(app,tmp_path):
    snap,chunks=snapshot_from(app)
    target=Store(tmp_path / "io-recovery",CHAIN)
    follower=Application(target)
    try:
        assert follower.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap,app_hash=state_hash(app.store.state)),None).result==pb.ResponseOfferSnapshot.ACCEPT
        target.conn.execute("CREATE TRIGGER disk_full BEFORE INSERT ON committed BEGIN SELECT RAISE(ABORT,'injected disk full'); END")
        with pytest.raises(sqlite3.IntegrityError,match="disk full"):
            for i,chunk in enumerate(chunks):
                follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=i,chunk=chunk),None)
        assert target.state is None
        assert target.conn.execute("SELECT COUNT(*) FROM committed").fetchone()[0]==0
        assert follower.Info(pb.RequestInfo(),None).last_block_height==0
        target.conn.execute("DROP TRIGGER disk_full")
        last=len(chunks)-1
        result=follower.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=last,chunk=chunks[last]),None)
        assert result.result==pb.ResponseApplySnapshotChunk.ACCEPT
        assert target.state==app.store.state and follower.restore is None
    finally:
        follower._clear_restore()
        target.close()


def test_restore_never_clears_unknown_staging_database(app,tmp_path):
    snap,chunks=snapshot_from(app)
    target=Store(tmp_path / 'unknown-staging',CHAIN)
    path=target.directory / 'restore-staging.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE user_data(value TEXT)')
        db.execute("INSERT INTO user_data VALUES('preserve')")
    before=path.read_bytes()
    follower=Application(target)
    try:
        with pytest.raises(ValueError,match='unrecognized'):
            follower.OfferSnapshot(pb.RequestOfferSnapshot(snapshot=snap,app_hash=state_hash(app.store.state)),None)
        assert path.read_bytes()==before
        assert target.state is None and follower.restore is None
    finally:
        target.close()
