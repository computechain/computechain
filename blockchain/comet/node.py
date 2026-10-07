"""CometBFT v0.40 ABCI gRPC application; all listeners default to loopback."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import logging
import math
from pathlib import Path
import sqlite3
import tempfile

import grpc

from .proto.tendermint.abci import types_pb2 as pb
from .proto.tendermint.abci import types_pb2_grpc as rpc
from .storage import Store, state_hash, validate_state, MAX_SNAPSHOT_BYTES, CHUNK_SIZE
from .transaction import apply, decode, canonical, GAS, MAX_TX_BYTES, MIN_GAS_PRICE
from .economics import VERSION, GAS as TX_GAS, BLOCK_GAS_LIMIT, EVIDENCE_BLOCKS, EVIDENCE_SECONDS
from .staking import initial_state, begin_block, finish_block

log = logging.getLogger(__name__)
MAX_BLOCK_TXS = 500


def timestamp(value):
    if not 0 <= value.nanos < 10**9:
        raise ValueError("invalid consensus timestamp")
    return value.seconds * 10**9 + value.nanos


def updates(changes):
    result = []
    for key, power in changes:
        update = pb.ValidatorUpdate(power=power)
        update.pub_key.ed25519 = bytes.fromhex(key)
        result.append(update)
    return result


def validate_listen(address: str) -> str:
    """ABCI grants write access to consensus state; never expose plaintext publicly."""
    try:
        host, port = address.rsplit(":", 1)
        if not ipaddress.ip_address(host.strip("[]")).is_loopback or not 0 < int(port) < 65536:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("ABCI listener must be a literal loopback IP and valid port") from None
    return address


class Application(rpc.ABCIServicer):
    def __init__(self, store: Store):
        self.store = store
        self.pending = None
        self.pending_request = None
        self.restore = None

    def Echo(self, request, context):
        return pb.ResponseEcho(message=request.message)

    def Flush(self, request, context):
        return pb.ResponseFlush()

    def Info(self, request, context):
        with self.store.lock:
            state = self.store.state
            return pb.ResponseInfo(data="ComputeChain v3 staking devnet", version="0.3.0", app_version=VERSION,
                last_block_height=state["height"] if state else 0,
                last_block_app_hash=state_hash(state) if state else b"")

    def InitChain(self, request, context):
        with self.store.lock:
            if request.chain_id != self.store.chain_id or request.initial_height not in (0, 1):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "wrong genesis domain or initial height")
            try:
                genesis = json.loads(request.app_state_bytes or b"{}")
                state = initial_state(request.chain_id, genesis, timestamp(request.time))
                if request.validators:
                    supplied = {v.pub_key.ed25519.hex(): v.power for v in request.validators if v.pub_key.WhichOneof("sum") == "ed25519"}
                    if len(supplied) != len(request.validators) or supplied != state["engine_powers"]:
                        raise ValueError("consensus/application genesis validators differ")
                params = request.consensus_params
                if params.HasField("evidence") and (params.evidence.max_age_num_blocks != EVIDENCE_BLOCKS or timestamp(params.evidence.max_age_duration) != EVIDENCE_SECONDS*10**9):
                    raise ValueError("unsupported evidence window")
                if params.HasField("block") and params.block.max_gas != BLOCK_GAS_LIMIT:
                    raise ValueError("unsupported block gas limit")
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid application genesis")
            if self.store.state is None:
                self.store.commit(state)
            elif state_hash(self.store.state) != state_hash(state):
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "genesis differs from committed application")
            response = pb.ResponseInitChain(app_hash=state_hash(state), validators=updates(sorted(state["engine_powers"].items())))
            response.consensus_params.CopyFrom(request.consensus_params)
            response.consensus_params.block.max_bytes = 2097152
            response.consensus_params.block.max_gas = BLOCK_GAS_LIMIT
            response.consensus_params.evidence.max_age_num_blocks = EVIDENCE_BLOCKS
            response.consensus_params.evidence.max_age_duration.seconds = EVIDENCE_SECONDS
            response.consensus_params.evidence.max_age_duration.nanos = 0
            response.consensus_params.evidence.max_bytes = 1048576
            del response.consensus_params.validator.pub_key_types[:]
            response.consensus_params.validator.pub_key_types.append("ed25519")
            response.consensus_params.version.app = VERSION
            return response

    def CheckTx(self, request, context):
        with self.store.lock:
            try:
                tx = decode(request.tx, self.store.chain_id)
                apply(self.store.clone(), tx, future_nonce=True)
                return pb.ResponseCheckTx(code=0, gas_wanted=TX_GAS[tx["type"]], gas_used=TX_GAS[tx["type"]])
            except (ValueError, TypeError) as exc:
                return pb.ResponseCheckTx(code=1, log=str(exc), codespace="cpc")

    def InsertTx(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "use CometBFT flood mempool")

    def ReapTxs(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "use CometBFT flood mempool")

    def PrepareProposal(self, request, context):
        with self.store.lock:
            state = self.store.clone()
            begin_block(state, request.height, timestamp(request.time), request.misbehavior)
            selected, size, gas = [], 0, 0
            for raw in request.txs[:MAX_BLOCK_TXS * 4]:
                if len(selected) >= MAX_BLOCK_TXS or size + len(raw) > request.max_tx_bytes:
                    break
                try:
                    tx = decode(raw, self.store.chain_id)
                    if gas + TX_GAS[tx["type"]] > BLOCK_GAS_LIMIT:
                        continue
                    apply(state, tx)
                except (ValueError, TypeError):
                    continue
                selected.append(raw)
                size += len(raw)
                gas += TX_GAS[tx["type"]]
            return pb.ResponsePrepareProposal(txs=selected)

    def ProcessProposal(self, request, context):
        with self.store.lock:
            try:
                if request.height != self.store.state["height"] + 1 or len(request.txs) > MAX_BLOCK_TXS:
                    raise ValueError("unexpected height or transaction count")
                state = self.store.clone()
                begin_block(state, request.height, timestamp(request.time), request.misbehavior)
                gas = 0
                for raw in request.txs:
                    tx = decode(raw, self.store.chain_id)
                    gas += TX_GAS[tx["type"]]
                    if gas > BLOCK_GAS_LIMIT:
                        raise ValueError("block gas limit")
                    apply(state, tx)
                finish_block(state)
                validate_state(state, self.store.chain_id)
                return pb.ResponseProcessProposal(status=pb.ResponseProcessProposal.ACCEPT)
            except (ValueError, TypeError):
                return pb.ResponseProcessProposal(status=pb.ResponseProcessProposal.REJECT)

    def ExtendVote(self, request, context):
        return pb.ResponseExtendVote()

    def VerifyVoteExtension(self, request, context):
        return pb.ResponseVerifyVoteExtension(status=pb.ResponseVerifyVoteExtension.ACCEPT if not request.vote_extension else pb.ResponseVerifyVoteExtension.REJECT)

    def FinalizeBlock(self, request, context):
        with self.store.lock:
            identity = hashlib.sha256(request.SerializeToString(deterministic=True)).digest()
            if self.pending_request == identity:
                return self.pending[2]
            if self.restore is not None or self.store.state is None or self.pending is not None or request.height != self.store.state["height"] + 1 or len(request.hash) != 32 or len(request.txs) > MAX_BLOCK_TXS:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "inconsistent FinalizeBlock")
            state = self.store.clone()
            try:
                begin_block(state, request.height, timestamp(request.time), request.misbehavior)
            except (ValueError, TypeError) as exc:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            results, receipts, gas = [], [], 0
            for raw in request.txs:
                # Failed transactions have a deterministic result and no side effects.
                try:
                    tx = decode(raw, self.store.chain_id)
                    wanted = TX_GAS[tx["type"]]
                    gas += wanted
                    if gas > BLOCK_GAS_LIMIT:
                        raise ValueError("block gas limit")
                    apply(state, tx)
                    result = pb.ExecTxResult(code=0, gas_wanted=wanted, gas_used=wanted)
                except (ValueError, TypeError) as exc:
                    result = pb.ExecTxResult(code=1, log=str(exc), codespace="cpc")
                results.append(result)
                receipts.append((hashlib.sha256(raw).hexdigest(), request.height, {"code": result.code}))
            state["last_block_hash"] = request.hash.hex()
            changes = finish_block(state)
            validate_state(state, self.store.chain_id)
            response = pb.ResponseFinalizeBlock(tx_results=results, app_hash=state_hash(state), validator_updates=updates(changes))
            self.pending = (state, receipts, response)
            self.pending_request = identity
            return response

    def Commit(self, request, context):
        with self.store.lock:
            if self.pending is not None:
                self.store.commit(self.pending[0], self.pending[1])
                self.pending = self.pending_request = None
            return pb.ResponseCommit(retain_height=0)

    def Query(self, request, context):
        with self.store.lock:
            state = self.store.state
            if state is None:
                return pb.ResponseQuery(code=1, log="not initialized")
            if request.prove or request.height not in (0, state["height"]):
                return pb.ResponseQuery(code=1, log="historical queries and Merkle proofs are not implemented")
            if request.path == "/state":
                value = state
            elif request.path.startswith("/account/"):
                value = state["accounts"].get(request.path.removeprefix("/account/"), {"balance": 0, "nonce": 0})
            elif request.path == "/validators":
                value = {"validators": state["validators"], "scheduled_powers": state["engine_powers"], "history": state["validator_history"]}
            elif request.path.startswith("/unbondings/"):
                value = [q for q in state["unbondings"] if q["owner"] == request.path.removeprefix("/unbondings/")]
            else:
                return pb.ResponseQuery(code=1, log="unknown query path")
            return pb.ResponseQuery(code=0, value=canonical(value), height=state["height"])

    def ListSnapshots(self, request, context):
        with self.store.lock:
            rows = self.store.conn.execute("SELECT height, hash, length(data) FROM snapshots ORDER BY height DESC").fetchall()
            return pb.ResponseListSnapshots(snapshots=[pb.Snapshot(height=h, format=VERSION, chunks=math.ceil(size / CHUNK_SIZE), hash=digest) for h, digest, size in rows])

    def LoadSnapshotChunk(self, request, context):
        with self.store.lock:
            row = self.store.conn.execute("SELECT data FROM snapshots WHERE height=?", (request.height,)).fetchone()
            if request.format != VERSION or not row or request.chunk >= math.ceil(len(row[0]) / CHUNK_SIZE):
                return pb.ResponseLoadSnapshotChunk()
            return pb.ResponseLoadSnapshotChunk(chunk=row[0][request.chunk * CHUNK_SIZE:(request.chunk + 1) * CHUNK_SIZE])

    def OfferSnapshot(self, request, context):
        with self.store.lock:
            snap = request.snapshot
            if snap.format != VERSION:
                return pb.ResponseOfferSnapshot(result=pb.ResponseOfferSnapshot.REJECT_FORMAT)
            if (self.pending is not None or (self.store.state and self.store.state["height"] > 0)
                    or not 0 < snap.height < 2**63 or not 0 < snap.chunks <= MAX_SNAPSHOT_BYTES // CHUNK_SIZE
                    or len(snap.hash) != 32 or len(request.app_hash) != 32 or snap.hash != request.app_hash):
                return pb.ResponseOfferSnapshot(result=pb.ResponseOfferSnapshot.REJECT)
            self._clear_restore()
            directory = tempfile.TemporaryDirectory(prefix=".restore-", dir=self.store.directory)
            staging = sqlite3.connect(Path(directory.name) / "chunks.sqlite", check_same_thread=False)
            staging.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, data BLOB NOT NULL)")
            self.restore = {"directory": directory, "db": staging, "snapshot": pb.Snapshot.FromString(snap.SerializeToString()), "app_hash": bytes(request.app_hash)}
            return pb.ResponseOfferSnapshot(result=pb.ResponseOfferSnapshot.ACCEPT)

    def _clear_restore(self):
        if self.restore:
            self.restore["db"].close()
            self.restore["directory"].cleanup()
            self.restore = None

    def ApplySnapshotChunk(self, request, context):
        with self.store.lock:
            if not self.restore:
                return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.ABORT)
            restore = self.restore
            snap = restore["snapshot"]
            if request.index >= snap.chunks or not 0 < len(request.chunk) <= CHUNK_SIZE:
                return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.RETRY, refetch_chunks=[request.index], reject_senders=[request.sender])
            prior = restore["db"].execute("SELECT data FROM chunks WHERE id=?", (request.index,)).fetchone()
            if prior and prior[0] != request.chunk:
                # A poisoned first chunk must not make every refetch conflict forever.
                with restore["db"]:
                    restore["db"].execute("DELETE FROM chunks WHERE id=?", (request.index,))
                return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.RETRY, refetch_chunks=[request.index], reject_senders=[request.sender])
            with restore["db"]:
                restore["db"].execute("INSERT OR IGNORE INTO chunks VALUES (?, ?)", (request.index, request.chunk))
            chunks = restore["db"].execute("SELECT data FROM chunks ORDER BY id").fetchall()
            if len(chunks) != snap.chunks:
                return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.ACCEPT)
            raw = b"".join(row[0] for row in chunks)
            try:
                state = json.loads(raw)
                if len(raw) > MAX_SNAPSHOT_BYTES or canonical(state) != raw or hashlib.sha256(raw).digest() != snap.hash:
                    raise ValueError("invalid snapshot payload")
                validate_state(state, self.store.chain_id)
                if state["height"] != snap.height or state_hash(state) != restore["app_hash"]:
                    raise ValueError("snapshot differs from light-client verified commitment")
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self._clear_restore()
                return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.REJECT_SNAPSHOT)
            self.store.commit(state, restoring=True)
            self._clear_restore()
            return pb.ResponseApplySnapshotChunk(result=pb.ResponseApplySnapshotChunk.ACCEPT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datadir", type=Path, required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--listen", default="127.0.0.1:26658")
    parser.add_argument("--snapshot-interval", type=int, default=10)
    args = parser.parse_args()
    if args.snapshot_interval < 1:
        parser.error("snapshot interval must be positive")
    try:
        validate_listen(args.listen)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO)
    store = Store(args.datadir, args.chain_id, args.snapshot_interval)
    application = Application(store)
    server = grpc.server(ThreadPoolExecutor(max_workers=4), maximum_concurrent_rpcs=16,
                         options=[("grpc.max_receive_message_length", 4 * 1024 * 1024)])
    rpc.add_ABCIServicer_to_server(application, server)
    if not server.add_insecure_port(args.listen):
        raise RuntimeError("could not bind ABCI listener")
    server.start()
    log.info("ABCI listening at %s", args.listen)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(5).wait()
    finally:
        application._clear_restore()
        store.close()


if __name__ == "__main__":
    main()
