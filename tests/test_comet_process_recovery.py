"""Actual SIGKILL/restart recovery over privileged loopback ABCI in scratch storage.

No consensus signing keys, existing host node directories or process registry used.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import grpc
import pytest

from computechain.blockchain.comet import node
from computechain.blockchain.comet.proto.tendermint.abci import types_pb2 as pb
from computechain.blockchain.comet.proto.tendermint.abci import types_pb2_grpc as service
from computechain.blockchain.comet.storage import Store,state_hash,CHUNK_SIZE
from computechain.blockchain.comet.transaction import canonical,sign_transfer
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.tests.comet_fixtures import genesis

WORKSPACE=Path(__file__).resolve().parents[2]
CHAIN="process-recovery-test"
PRIVATE=hashlib.sha256(b'public-process-recovery-fixture').digest()
OWNER=address_from_pubkey(public_key_from_private(PRIVATE))
RECIPIENT=address_from_pubkey(public_key_from_private(hashlib.sha256(b'public-recovery-recipient').digest()))


class Context:
    def abort(self,status,message):
        raise RuntimeError(message)


class Server:
    def __init__(self,directory):
        self.directory=directory
        self.process=self.channel=None
        self.start()

    def start(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0))
            port=reservation.getsockname()[1]
        self.process=subprocess.Popen([sys.executable,'-m','computechain.blockchain.comet.node',
            '--datadir',str(self.directory),'--chain-id',CHAIN,'--listen',f'127.0.0.1:{port}','--snapshot-interval','1'],
            env={**os.environ,'PYTHONPATH':str(WORKSPACE)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.channel=grpc.insecure_channel(f'127.0.0.1:{port}')
        try:
            grpc.channel_ready_future(self.channel).result(timeout=10)
            self.stub=service.ABCIStub(self.channel)
        except Exception:
            self.close()
            raise

    def crash(self):
        self.channel.close()
        self.process.kill()  # exact Popen child only; no PID lookup/broad host signalling
        self.process.wait(timeout=10)
        self.process=self.channel=None

    def close(self):
        if self.channel:
            self.channel.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process=self.channel=None


@pytest.fixture
def server(tmp_path):
    instance=Server(tmp_path / "follower")
    try:
        yield instance
    finally:
        instance.close()


def init(stub):
    value=genesis({OWNER:{'balance':1000*10**18,'nonce':0}})
    stub.InitChain(pb.RequestInitChain(chain_id=CHAIN,initial_height=1,app_state_bytes=canonical(value)),timeout=5)


@pytest.mark.parametrize('committed',[False,True])
def test_actual_crash_around_commit_no_partial_state_or_double_transfer(server,committed):
    init(server.stub)
    raw=sign_transfer(PRIVATE,CHAIN,RECIPIENT,10**18,0)
    request=pb.RequestFinalizeBlock(height=1,hash=b'x'*32,txs=[raw])
    expected=server.stub.FinalizeBlock(request,timeout=5)
    assert expected.tx_results[0].code==0
    if committed:
        server.stub.Commit(pb.RequestCommit(),timeout=5)
    server.crash()
    server.start()
    info=server.stub.Info(pb.RequestInfo(),timeout=5)
    assert info.last_block_height==int(committed)
    if not committed:
        assert server.stub.FinalizeBlock(request,timeout=5)==expected
        server.stub.Commit(pb.RequestCommit(),timeout=5)
    assert server.stub.Info(pb.RequestInfo(),timeout=5).last_block_app_hash==expected.app_hash
    state=json.loads(server.stub.Query(pb.RequestQuery(path='/state'),timeout=5).value)
    assert state['accounts'][RECIPIENT]['balance']==10**18
    assert state['accounts'][OWNER]['nonce']==1
    assert state['burned']==21_000_000
    assert server.stub.CheckTx(pb.RequestCheckTx(tx=raw),timeout=5).code!=0


def test_actual_crash_mid_snapshot_does_not_publish_partial_state(server,tmp_path):
    # Large valid public-fixture state produces multiple real 256KiB chunks.
    # Addresses derived directly from fixture bytes avoid thousands of EC operations.
    accounts={OWNER:{'balance':1000*10**18,'nonce':0}}
    for i in range(4200):
        public=b'\x02'+hashlib.sha256(f'public-snapshot-account-{i}'.encode()).digest()
        accounts[address_from_pubkey(public)]={'balance':0,'nonce':0}
    with_store=Store(tmp_path / 'source',CHAIN,snapshot_interval=1)
    application=node.Application(with_store)
    try:
        application.InitChain(pb.RequestInitChain(chain_id=CHAIN,initial_height=1,app_state_bytes=canonical(genesis(accounts))),Context())
        application.FinalizeBlock(pb.RequestFinalizeBlock(height=1,hash=b'y'*32),Context())
        application.Commit(pb.RequestCommit(),None)
        snapshot=application.ListSnapshots(pb.RequestListSnapshots(),None).snapshots[0]
        assert snapshot.chunks>=2
        chunks=[application.LoadSnapshotChunk(pb.RequestLoadSnapshotChunk(height=1,format=3,chunk=i),None).chunk for i in range(snapshot.chunks)]
        offer=pb.RequestOfferSnapshot(snapshot=snapshot,app_hash=state_hash(with_store.state))
        assert server.stub.OfferSnapshot(offer,timeout=5).result==pb.ResponseOfferSnapshot.ACCEPT
        assert server.stub.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=0,chunk=chunks[0]),timeout=5).result==pb.ResponseApplySnapshotChunk.ACCEPT
        server.crash()
        server.start()
        assert server.stub.Info(pb.RequestInfo(),timeout=5).last_block_height==0
        assert (server.directory / 'restore-staging.sqlite').is_file()
        assert not list(server.directory.glob('.restore-*'))
        assert server.stub.Query(pb.RequestQuery(path='/state'),timeout=5).code!=0
        # Old volatile restore is not assumed durable; re-offer verified metadata.
        assert server.stub.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=1,chunk=chunks[1]),timeout=5).result==pb.ResponseApplySnapshotChunk.ABORT
        assert server.stub.OfferSnapshot(offer,timeout=5).result==pb.ResponseOfferSnapshot.ACCEPT
        # Pre-crash chunk0 is discarded; chunk1 alone must not publish state.
        assert server.stub.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=1,chunk=chunks[1]),timeout=5).result==pb.ResponseApplySnapshotChunk.ACCEPT
        assert server.stub.Info(pb.RequestInfo(),timeout=5).last_block_height==0
        for i in reversed(range(snapshot.chunks)):
            assert server.stub.ApplySnapshotChunk(pb.RequestApplySnapshotChunk(index=i,chunk=chunks[i]),timeout=5).result==pb.ResponseApplySnapshotChunk.ACCEPT
        assert server.stub.Info(pb.RequestInfo(),timeout=5).last_block_app_hash==offer.app_hash
        server.crash()
        server.start()
        assert server.stub.Info(pb.RequestInfo(),timeout=5).last_block_app_hash==offer.app_hash
    finally:
        application._clear_restore()
        with_store.close()
