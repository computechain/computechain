import asyncio
import json
import logging
import time
import base64
from enum import Enum, auto
from typing import List, Dict, Callable, Optional, Set
from .protocol import (
    P2PMessage, P2PMessageType, 
    HandshakePayload, GetBlocksPayload, BlocksResponsePayload,
    GetHeadersPayload, HeadersResponsePayload,
    StatusPayload, PeersPayload, PingPayload, PongPayload,
    GetSnapshotPayload, SnapshotChunkPayload
)
from ...protocol.types.block import Block, BlockHeader
from ...protocol.types.tx import Transaction

logger = logging.getLogger(__name__)

class SyncState(Enum):
    IDLE = auto()
    SYNCING = auto()
    SYNCED = auto()

class Peer:
    def __init__(self, writer, node_id: str, p2p_port: int, best_height: int, best_hash: str, genesis_hash: str):
        self.writer = writer
        self.node_id = node_id # This is host:port as reported by peer
        self.p2p_port = p2p_port
        self.best_height = best_height
        self.best_hash = best_hash
        self.genesis_hash = genesis_hash
        self.latest_snapshot_height: Optional[int] = None
        self.latest_snapshot_hash: Optional[str] = None
        self.last_seen_at: float = time.time()
        
        # Store actual connection info
        self.real_host, self.real_port = writer.get_extra_info('peername')
        
        # Determine persistable address (for peers.json)
        # If node_id is 0.0.0.0, use real_host
        host, port_str = node_id.split(":")
        if host == "0.0.0.0":
            self.persist_addr = f"{self.real_host}:{port_str}"
        else:
            self.persist_addr = node_id

class P2PNode:
    def __init__(self, host: str, port: int, initial_peers: List[str], network_id: str):
        self.host = host
        self.port = port
        self.initial_peers = initial_peers
        self.network_id = network_id

        # Callbacks (set by higher level)
        self.on_new_block: Optional[Callable[[Block], None]] = None
        self.on_new_tx: Optional[Callable[[Transaction], None]] = None
        self.get_current_height: Optional[Callable[[], int]] = None
        self.get_last_hash: Optional[Callable[[], str]] = None
        self.get_genesis_hash: Optional[Callable[[], str]] = None
        self.get_blocks_range: Optional[Callable[[int, int], List[Block]]] = None
        self.get_headers_range: Optional[Callable[[int, int], List[BlockHeader]]] = None
        self.get_block_by_height: Optional[Callable[[int], Optional[Block]]] = None
        self.rollback_to_height: Optional[Callable[[int], None]] = None
        self.get_latest_snapshot_height: Optional[Callable[[], Optional[int]]] = None
        self.get_snapshot_bytes: Optional[Callable[[int], Optional[bytes]]] = None
        self.apply_snapshot_bytes: Optional[Callable[[int, bytes], bool]] = None

        self.active_peers: Dict[asyncio.StreamWriter, Peer] = {}
        self.known_peers: Set[str] = set(initial_peers) # Persistable set of "addr:port"
        self.writers: List[asyncio.StreamWriter] = []
        self.server = None
        self.node_id = f"{host}:{port}"

        # Start in SYNCING state to prevent mining before checking peers
        self.sync_state: SyncState = SyncState.SYNCING if initial_peers else SyncState.SYNCED
        self.MAX_BLOCKS_PER_MESSAGE = 500
        self.MAX_HEADERS_PER_MESSAGE = 500
        self.HEADER_SYNC_WINDOW = 200
        self.SNAPSHOT_SYNC_THRESHOLD = 500
        self.MAX_SNAPSHOT_CHUNK_BYTES = 256 * 1024
        self.STATUS_INTERVAL_SECONDS = 10
        self.PING_INTERVAL_SECONDS = 15
        self.PEER_TIMEOUT_SECONDS = 45
        self._sync_phase: Optional[str] = None
        self._header_sync_from: int = 0
        self._header_sync_to: int = 0
        self._initial_sync_done = False
        self._block_cache: Dict[int, Block] = {}
        self._snapshot_buffers: Dict[str, Dict[str, int | Dict[int, bytes]]] = {}
        self._background_tasks: List[asyncio.Task] = []

        # Sync tracking (Phase 1.5: prevent stuck sync states)
        self._syncing_with_peer: Optional[asyncio.StreamWriter] = None
        self._sync_started_at: float = 0
        self.SYNC_TIMEOUT_SECONDS = 30  # Max time to wait for sync response

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_connection, self.host, self.port
        )
        logger.info(f"P2P Server listening on {self.host}:{self.port}")

        # Background tasks for status/ping/peer cleanup
        self._background_tasks = [
            asyncio.create_task(self._status_loop()),
            asyncio.create_task(self._ping_loop()),
            asyncio.create_task(self._peer_cleanup_loop()),
        ]

        # Connect to known peers
        for peer in list(self.known_peers):
            asyncio.create_task(self.connect_to_peer(peer))

        # Give peers a moment to connect and start handshake/sync
        # This prevents BlockProposer from immediately mining before we know peer heights
        if self.known_peers:
            await asyncio.sleep(2.0) # 2 second grace period for initial connections
            
            # P1.2 FIX: If no active peers connected, we should exit SYNCING state
            # to allow mining (if we are a validator). Otherwise we deadlock.
            if not self.active_peers and self.sync_state == SyncState.SYNCING:
                logger.info("No active peers found after wait. Switching to SYNCED.")
                self.sync_state = SyncState.SYNCED
            
            # After this, if we're still SYNCING, that's fine - proposer will wait
            # If we've synced or no peers ahead, we'll be SYNCED

        async with self.server:
            await self.server.serve_forever()
    
    @property
    def peers(self) -> List[str]:
        """Returns a list of known peer addresses for persistence."""
        return list(self.known_peers)

    async def connect_to_peer(self, peer_address: str):
        if peer_address == self.node_id or peer_address == f"127.0.0.1:{self.port}" or peer_address == f"0.0.0.0:{self.port}":
             return

        try:
            host, port = peer_address.split(":")
            reader, writer = await asyncio.open_connection(host, int(port))
            logger.info(f"Connected to peer {peer_address}")
            
            self.writers.append(writer)
            await self.send_handshake(writer)
            await self.read_loop(reader, writer)
        except Exception as e:
            logger.warning(f"Failed to connect to {peer_address}: {e}")

    async def handle_connection(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logger.info(f"Incoming connection from {addr}")
        self.writers.append(writer)
        await self.read_loop(reader, writer)

    async def read_loop(self, reader, writer):
        buffer = b""
        try:
            while True:
                data = await reader.read(10*1024) # 10KB chunks
                if not data:
                    break

                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    await self.process_message(line, writer)
        except ConnectionResetError:
            pass
        except Exception as e:
            logger.error(f"Error in read loop: {e}")
        finally:
            # Phase 1.5: Reset sync state if we were syncing with this peer
            if self._syncing_with_peer == writer and self.sync_state == SyncState.SYNCING:
                logger.warning(f"Sync peer disconnected! Resetting sync state to allow recovery.")
                self.sync_state = SyncState.IDLE
                self._syncing_with_peer = None
                self._sync_started_at = 0
                self._sync_phase = None

            if writer in self.active_peers:
                del self.active_peers[writer]
            if writer in self.writers:
                self.writers.remove(writer)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def process_message(self, data: bytes, writer):
        try:
            msg_dict = json.loads(data.decode())
            msg = P2PMessage(**msg_dict)
            
            if msg.type == P2PMessageType.HANDSHAKE:
                await self.handle_handshake(writer, msg.payload)
                
            elif msg.type == P2PMessageType.STATUS:
                await self.handle_status(writer, msg.payload)
            
            elif msg.type == P2PMessageType.PING:
                await self.handle_ping(writer, msg.payload)
            
            elif msg.type == P2PMessageType.PONG:
                await self.handle_pong(writer, msg.payload)
                
            elif msg.type == P2PMessageType.NEW_BLOCK:
                await self.handle_new_block(writer, msg.payload)
                    
            elif msg.type == P2PMessageType.NEW_TX:
                await self.handle_new_tx(msg.payload)
            
            elif msg.type == P2PMessageType.GET_BLOCKS:
                await self.handle_get_blocks(writer, msg.payload)
                
            elif msg.type == P2PMessageType.BLOCKS_RESPONSE:
                await self.handle_blocks_response(writer, msg.payload)
            
            elif msg.type == P2PMessageType.GET_HEADERS:
                await self.handle_get_headers(writer, msg.payload)

            elif msg.type == P2PMessageType.HEADERS_RESPONSE:
                await self.handle_headers_response(writer, msg.payload)
            
            elif msg.type == P2PMessageType.PEERS:
                await self.handle_peers(writer, msg.payload)
            
            elif msg.type == P2PMessageType.GET_SNAPSHOT:
                await self.handle_get_snapshot(writer, msg.payload)
            
            elif msg.type == P2PMessageType.SNAPSHOT_CHUNK:
                await self.handle_snapshot_chunk(writer, msg.payload)
                    
        except Exception as e:
            logger.error(f"Failed to process message: {e}")

    # --- Handlers ---

    async def handle_handshake(self, writer, payload_dict):
        payload = HandshakePayload(**payload_dict)

        if writer in self.active_peers:
            # Update existing peer info
            peer = self.active_peers[writer]
            old_height = peer.best_height
            peer.best_height = payload.best_height
            peer.best_hash = payload.best_hash
            peer.latest_snapshot_height = payload.latest_snapshot_height
            peer.latest_snapshot_hash = payload.latest_snapshot_hash
            peer.last_seen_at = time.time()

            # Phase 1.5: Check if peer is ahead and we need to sync
            my_height = self.get_current_height() if self.get_current_height else -1
            if payload.best_height > my_height and self.sync_state != SyncState.SYNCING:
                logger.info(f"Peer {peer.persist_addr} is ahead (height {payload.best_height} vs our {my_height}). Triggering sync...")
                await self._trigger_catchup_sync(target_height=payload.best_height)
            return
        
        if payload.network != self.network_id:
            logger.warning(f"Wrong network: {payload.network}")
            writer.close()
            return

        my_genesis = self.get_genesis_hash() if self.get_genesis_hash else None
        if my_genesis and payload.genesis_hash and my_genesis != payload.genesis_hash:
            logger.warning(f"Genesis mismatch! Mine: {my_genesis[:8]}, Theirs: {payload.genesis_hash[:8]}")
            writer.close()
            return

        peer = Peer(
            writer, 
            payload.node_id, 
            payload.p2p_port, 
            payload.best_height, 
            payload.best_hash,
            payload.genesis_hash or ""
        )
        peer.latest_snapshot_height = payload.latest_snapshot_height
        peer.latest_snapshot_hash = payload.latest_snapshot_hash
        self.active_peers[writer] = peer
        
        # Add to known peers for persistence
        self.known_peers.add(peer.persist_addr)
        
        logger.info(f"Peer registered: {peer.persist_addr} (Height: {peer.best_height})")
        
        # Send Handshake back if not already sent
        if not hasattr(self, '_handshake_sent'):
            self._handshake_sent = set()
        
        if writer not in self._handshake_sent:
            await self.send_handshake(writer)
            self._handshake_sent.add(writer)

        # Share known peers for discovery
        await self.send_peers(writer)

        # Check Sync
        my_height = self.get_current_height() if self.get_current_height else -1
        if peer.best_height > my_height:
            await self.start_sync(peer)
        else:
            self.sync_state = SyncState.SYNCED

    async def handle_status(self, writer, payload_dict):
        payload = StatusPayload(**payload_dict)
        peer = self.active_peers.get(writer)
        if not peer:
            return

        peer.best_height = payload.best_height
        peer.best_hash = payload.best_hash
        peer.latest_snapshot_height = payload.latest_snapshot_height
        peer.latest_snapshot_hash = payload.latest_snapshot_hash
        peer.last_seen_at = time.time()

        my_height = self.get_current_height() if self.get_current_height else -1
        if peer.best_height > my_height and self.sync_state != SyncState.SYNCING:
            await self._trigger_catchup_sync(target_height=peer.best_height)

    async def handle_peers(self, writer, payload_dict):
        payload = PeersPayload(**payload_dict)
        new_peers = 0

        for addr in payload.peers:
            if addr == self.node_id:
                continue
            if addr not in self.known_peers:
                self.known_peers.add(addr)
                new_peers += 1
                asyncio.create_task(self.connect_to_peer(addr))

        if new_peers:
            logger.info(f"Discovered {new_peers} new peers via gossip")

    async def handle_ping(self, writer, payload_dict):
        payload = PingPayload(**payload_dict)
        peer = self.active_peers.get(writer)
        if peer:
            peer.last_seen_at = time.time()

        pong = P2PMessage(type=P2PMessageType.PONG, payload=PongPayload(timestamp=payload.timestamp).model_dump())
        await self.send_message(writer, pong)

    async def handle_pong(self, writer, payload_dict):
        peer = self.active_peers.get(writer)
        if peer:
            peer.last_seen_at = time.time()

    async def handle_new_block(self, writer, payload_dict):
        # Phase 1.5: Check for sync timeout before skipping
        if self.sync_state == SyncState.SYNCING:
            if self._sync_started_at > 0:
                elapsed = time.time() - self._sync_started_at
                if elapsed > self.SYNC_TIMEOUT_SECONDS:
                    logger.warning(f"Sync timed out after {elapsed:.1f}s during NEW_BLOCK. Resetting.")
                    self.sync_state = SyncState.IDLE
                    self._syncing_with_peer = None
                    self._sync_started_at = 0
                    self._sync_phase = None
            else:
                return  # Syncing without timestamp (shouldn't happen)

        block = Block.model_validate(payload_dict['block'])

        peer = self.active_peers.get(writer)
        if peer:
            peer.best_height = max(peer.best_height, block.header.height)
            peer.best_hash = block.hash()
            peer.last_seen_at = time.time()

        if self.sync_state == SyncState.SYNCING:
            # Cache blocks while syncing to apply after catchup
            if len(self._block_cache) < self.MAX_BLOCKS_PER_MESSAGE * 2:
                self._block_cache[block.header.height] = block
            return

        if self.on_new_block:
            try:
                await self.on_new_block(block)
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Rejected P2P block: {e}")

                # Check if we're behind and need catchup sync
                if "Invalid height" in error_msg and self.get_current_height:
                    my_height = self.get_current_height()
                    incoming_height = block.header.height

                    if incoming_height > my_height + 1:
                        # We're behind - trigger catchup sync
                        logger.info(f"Height gap detected: my={my_height}, incoming={incoming_height}. Starting catchup sync...")
                        await self._trigger_catchup_sync(target_height=incoming_height)
                    elif incoming_height < my_height:
                        # Phase 1.5: We received an OLD block from a behind node
                        # Broadcast our current height to help them realize they need to sync
                        logger.debug(f"Received old block {incoming_height}, we're at {my_height}. Broadcasting handshake update.")
                        await self._broadcast_handshake_update()

    async def handle_new_tx(self, payload_dict):
        if self.on_new_tx:
            tx = Transaction.model_validate(payload_dict['tx'])
            await self.on_new_tx(tx)

    async def handle_get_blocks(self, writer, payload_dict):
        if not self.get_blocks_range: return
        
        req = GetBlocksPayload(**payload_dict)
        from_h = req.from_height
        to_h = req.to_height
        
        if to_h - from_h + 1 > self.MAX_BLOCKS_PER_MESSAGE:
            to_h = from_h + self.MAX_BLOCKS_PER_MESSAGE - 1
            
        blocks = self.get_blocks_range(from_h, to_h)
        serialized_blocks = [b.model_dump() for b in blocks]
        
        resp = BlocksResponsePayload(blocks=serialized_blocks)
        msg = P2PMessage(type=P2PMessageType.BLOCKS_RESPONSE, payload=resp.model_dump())
        await self.send_message(writer, msg)

    async def handle_get_headers(self, writer, payload_dict):
        if not self.get_headers_range:
            return

        req = GetHeadersPayload(**payload_dict)
        from_h = req.from_height
        to_h = req.to_height

        if to_h - from_h + 1 > self.MAX_HEADERS_PER_MESSAGE:
            to_h = from_h + self.MAX_HEADERS_PER_MESSAGE - 1

        headers = self.get_headers_range(from_h, to_h)
        serialized_headers = [h.model_dump() for h in headers]

        resp = HeadersResponsePayload(headers=serialized_headers)
        msg = P2PMessage(type=P2PMessageType.HEADERS_RESPONSE, payload=resp.model_dump())
        await self.send_message(writer, msg)

    async def handle_blocks_response(self, writer, payload_dict):
        if self.sync_state != SyncState.SYNCING or self._sync_phase != "blocks":
            return

        resp = BlocksResponsePayload(**payload_dict)
        if not resp.blocks:
            self.sync_state = SyncState.SYNCED
            self._syncing_with_peer = None
            self._sync_started_at = 0
            self._sync_phase = None
            logger.info("Sync finished (no more blocks)")
            await self._apply_cached_blocks()
            return

        added_count = 0
        rollback_count = 0
        max_rollbacks = 50  # Prevent infinite rollback loop

        for b_data in resp.blocks:
            block = Block.model_validate(b_data)
            if self.on_new_block:
                try:
                    await self.on_new_block(block)
                    added_count += 1
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"Sync failed at block {block.header.height}: {e}")

                    # Check if this is a fork/divergence error that might have triggered rollback
                    # If on_new_block rolled back, we should re-request blocks from the new height
                    if rollback_count < max_rollbacks:
                        rollback_count += 1
                        my_height = self.get_current_height() if self.get_current_height else -1
                        peer = self.active_peers.get(writer)
                        if peer and my_height < peer.best_height:
                            logger.info(f"Retrying sync from height {my_height + 1} after rollback ({rollback_count}/{max_rollbacks})")
                            self._sync_started_at = time.time()
                            await self.request_blocks(peer, my_height + 1, peer.best_height)
                            return  # Will continue in next handle_blocks_response

                    # Too many rollbacks or no peer - give up
                    logger.error(f"Sync giving up after {rollback_count} rollbacks")
                    self.sync_state = SyncState.IDLE
                    self._syncing_with_peer = None
                    self._sync_started_at = 0
                    self._sync_phase = None
                    return

        if added_count > 0:
            logger.info(f"Synced {added_count} blocks. Last: {block.header.height}")

        peer = self.active_peers.get(writer)
        my_height = self.get_current_height()

        if peer and my_height < peer.best_height:
            # Continue syncing - refresh timeout
            self._sync_started_at = time.time()
            await self.request_blocks(peer, my_height + 1, peer.best_height)
        else:
            self.sync_state = SyncState.SYNCED
            self._syncing_with_peer = None
            self._sync_started_at = 0
            self._sync_phase = None
            logger.info("Sync finished (caught up)")
            await self._apply_cached_blocks()

    async def handle_headers_response(self, writer, payload_dict):
        if self.sync_state != SyncState.SYNCING or self._sync_phase != "headers":
            return

        resp = HeadersResponsePayload(**payload_dict)
        if not resp.headers:
            logger.warning("Header sync failed: empty response")
            self.sync_state = SyncState.IDLE
            self._syncing_with_peer = None
            self._sync_started_at = 0
            self._sync_phase = None
            return

        headers = sorted([BlockHeader.model_validate(h) for h in resp.headers], key=lambda h: h.height)
        common_height = None

        for hdr in headers:
            if not self.get_block_by_height:
                break
            local_blk = self.get_block_by_height(hdr.height)
            if local_blk and local_blk.hash() == hdr.hash():
                common_height = hdr.height

        peer = self.active_peers.get(writer)
        if peer is None:
            logger.warning("Header sync failed: peer not active")
            self.sync_state = SyncState.IDLE
            self._syncing_with_peer = None
            self._sync_started_at = 0
            self._sync_phase = None
            return

        my_height = self.get_current_height() if self.get_current_height else -1
        if common_height is None:
            if my_height < 0:
                common_height = -1
            else:
                if self._header_sync_from == 0:
                    logger.error("Header sync failed: no common ancestor found")
                    self.sync_state = SyncState.IDLE
                    self._syncing_with_peer = None
                    self._sync_started_at = 0
                    self._sync_phase = None
                    return

                new_to = self._header_sync_from - 1
                new_from = max(0, new_to - self.HEADER_SYNC_WINDOW + 1)
                self._header_sync_from = new_from
                self._header_sync_to = new_to
                self._sync_started_at = time.time()
                logger.info(f"Header sync: no match, retrying {new_from} to {new_to}")
                await self.request_headers(peer, new_from, new_to)
                return

        if my_height > common_height and self.rollback_to_height:
            logger.warning(f"Fork detected. Rolling back to common ancestor {common_height}")
            self.rollback_to_height(common_height)

        self._sync_phase = "blocks"
        self._sync_started_at = time.time()
        await self.request_blocks(peer, common_height + 1, peer.best_height)

    async def handle_get_snapshot(self, writer, payload_dict):
        if not self.get_snapshot_bytes:
            return

        req = GetSnapshotPayload(**payload_dict)
        snapshot_bytes = self.get_snapshot_bytes(req.height)
        if snapshot_bytes is None:
            logger.warning(f"Snapshot {req.height} not available for peer")
            return

        total_size = len(snapshot_bytes)
        chunk_size = self.MAX_SNAPSHOT_CHUNK_BYTES
        total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)

        for idx in range(total_chunks):
            start = idx * chunk_size
            end = min(start + chunk_size, total_size)
            chunk = snapshot_bytes[start:end]
            payload = SnapshotChunkPayload(
                height=req.height,
                chunk_index=idx,
                total_chunks=total_chunks,
                data_b64=base64.b64encode(chunk).decode("ascii")
            )
            msg = P2PMessage(type=P2PMessageType.SNAPSHOT_CHUNK, payload=payload.model_dump())
            await self.send_message(writer, msg)

    async def handle_snapshot_chunk(self, writer, payload_dict):
        if self.sync_state != SyncState.SYNCING or self._sync_phase != "snapshot":
            return

        payload = SnapshotChunkPayload(**payload_dict)
        peer = self.active_peers.get(writer)
        if peer is None:
            return

        key = f"{peer.persist_addr}:{payload.height}"
        buffer = self._snapshot_buffers.get(key)
        if buffer is None:
            buffer = {"total": payload.total_chunks, "chunks": {}}
            self._snapshot_buffers[key] = buffer

        try:
            chunk = base64.b64decode(payload.data_b64.encode("ascii"))
        except Exception:
            logger.warning("Invalid snapshot chunk encoding")
            return

        buffer["chunks"][payload.chunk_index] = chunk

        if len(buffer["chunks"]) < buffer["total"]:
            return

        assembled = b"".join(buffer["chunks"][i] for i in range(buffer["total"]))
        del self._snapshot_buffers[key]

        if not self.apply_snapshot_bytes:
            logger.warning("No snapshot apply handler configured")
            self.sync_state = SyncState.IDLE
            self._sync_phase = None
            return

        logger.info(f"Applying snapshot {payload.height} from peer {peer.persist_addr}")
        applied = self.apply_snapshot_bytes(payload.height, assembled)
        if not applied:
            logger.error("Failed to apply snapshot; falling back to block sync")

        self._sync_phase = "blocks"
        self._sync_started_at = time.time()
        await self.request_blocks(peer, payload.height + 1, peer.best_height)

    # --- Actions ---

    async def _trigger_catchup_sync(self, target_height: int = None):
        """Find best peer and start catchup sync."""
        # Phase 1.5: Check for sync timeout before refusing to start new sync
        if self.sync_state == SyncState.SYNCING:
            if self._sync_started_at > 0:
                elapsed = time.time() - self._sync_started_at
                if elapsed > self.SYNC_TIMEOUT_SECONDS:
                    logger.warning(f"Sync timed out after {elapsed:.1f}s. Resetting to allow retry.")
                    self.sync_state = SyncState.IDLE
                    self._syncing_with_peer = None
                    self._sync_started_at = 0
                    self._sync_phase = None
                else:
                    return  # Still syncing, not timed out yet
            else:
                return  # Already syncing

        my_height = self.get_current_height() if self.get_current_height else -1

        # Find best active peer to sync from
        best_peer = self._select_best_peer()

        if best_peer:
            # Update peer's best_height if we know the target is higher
            if target_height and target_height > best_peer.best_height:
                best_peer.best_height = target_height

            logger.info(f"Catchup sync: requesting blocks {my_height + 1} to {best_peer.best_height}")
            await self.start_sync(best_peer)
        else:
            logger.warning("No active peers for catchup sync!")

    async def start_sync(self, peer: Peer):
        logger.info(f"Starting sync with {peer.persist_addr}. My height: {self.get_current_height()}, Peer: {peer.best_height}")
        self.sync_state = SyncState.SYNCING
        self._syncing_with_peer = peer.writer
        self._sync_started_at = time.time()
        self._sync_phase = "headers"
        my_height = self.get_current_height()

        if (
            peer.latest_snapshot_height
            and self.apply_snapshot_bytes
            and my_height + 1 < peer.latest_snapshot_height
            and peer.best_height - my_height > self.SNAPSHOT_SYNC_THRESHOLD
        ):
            self._sync_phase = "snapshot"
            self._sync_started_at = time.time()
            await self.request_snapshot(peer, peer.latest_snapshot_height)
            return

        from_h = max(0, my_height - self.HEADER_SYNC_WINDOW)
        to_h = peer.best_height
        self._header_sync_from = from_h
        self._header_sync_to = to_h
        await self.request_headers(peer, from_h, to_h)

    async def request_blocks(self, peer: Peer, from_h: int, to_h: int):
        if to_h - from_h + 1 > self.MAX_BLOCKS_PER_MESSAGE:
            to_h = from_h + self.MAX_BLOCKS_PER_MESSAGE - 1
            
        payload = GetBlocksPayload(from_height=from_h, to_height=to_h)
        msg = P2PMessage(type=P2PMessageType.GET_BLOCKS, payload=payload.model_dump())
        await self.send_message(peer.writer, msg)

    async def request_headers(self, peer: Peer, from_h: int, to_h: int):
        if to_h - from_h + 1 > self.MAX_HEADERS_PER_MESSAGE:
            to_h = from_h + self.MAX_HEADERS_PER_MESSAGE - 1

        payload = GetHeadersPayload(from_height=from_h, to_height=to_h)
        msg = P2PMessage(type=P2PMessageType.GET_HEADERS, payload=payload.model_dump())
        await self.send_message(peer.writer, msg)

    async def request_snapshot(self, peer: Peer, height: int):
        payload = GetSnapshotPayload(height=height)
        msg = P2PMessage(type=P2PMessageType.GET_SNAPSHOT, payload=payload.model_dump())
        await self.send_message(peer.writer, msg)

    def _select_best_peer(self) -> Optional[Peer]:
        peers = list(self.active_peers.values())
        if not peers:
            return None
        peers.sort(key=lambda p: (p.best_height, p.last_seen_at), reverse=True)
        return peers[0]

    async def _apply_cached_blocks(self):
        if not self._block_cache or not self.on_new_block:
            self._block_cache.clear()
            return

        for height in sorted(self._block_cache.keys()):
            block = self._block_cache[height]
            try:
                await self.on_new_block(block)
            except Exception as e:
                logger.warning(f"Failed to apply cached block {height}: {e}")

        self._block_cache.clear()

    async def send_message(self, writer, msg: P2PMessage):
        try:
            data = msg.model_dump_json() + "\n"
            writer.write(data.encode())
            await writer.drain()
        except Exception as e:
            logger.error(f"Failed to send: {e}")
            # Clean up disconnected peer
            if writer in self.writers:
                self.writers.remove(writer)
            if writer in self.active_peers:
                del self.active_peers[writer]
            try:
                writer.close()
            except Exception:
                pass

    async def send_handshake(self, writer):
        height = self.get_current_height() if self.get_current_height else -1
        last_hash = self.get_last_hash() if self.get_last_hash else ("0"*64)
        genesis_hash = self.get_genesis_hash() if self.get_genesis_hash else None
        latest_snapshot_height = self.get_latest_snapshot_height() if self.get_latest_snapshot_height else None

        payload = HandshakePayload(
            node_id=self.node_id,
            p2p_port=self.port,
            network=self.network_id,
            best_height=height,
            best_hash=last_hash,
            genesis_hash=genesis_hash,
            latest_snapshot_height=latest_snapshot_height,
            latest_snapshot_hash=None
        )
        msg = P2PMessage(type=P2PMessageType.HANDSHAKE, payload=payload.model_dump())
        await self.send_message(writer, msg)

    async def broadcast_block(self, block: Block):
        msg = P2PMessage(
            type=P2PMessageType.NEW_BLOCK,
            payload={"block": block.model_dump()}
        )
        await self.broadcast(msg)

    async def broadcast_tx(self, tx: Transaction):
        msg = P2PMessage(
            type=P2PMessageType.NEW_TX,
            payload={"tx": tx.model_dump()}
        )
        await self.broadcast(msg)

    async def _broadcast_handshake_update(self):
        """
        Phase 1.5: Broadcast handshake to all peers with our current height.
        This helps behind nodes realize they need to sync.
        """
        for writer in self.writers:
            await self.send_handshake(writer)

    async def broadcast(self, msg: P2PMessage):
        for writer in self.writers:
            await self.send_message(writer, msg)

    async def send_status(self, writer):
        height = self.get_current_height() if self.get_current_height else -1
        last_hash = self.get_last_hash() if self.get_last_hash else ("0"*64)
        genesis_hash = self.get_genesis_hash() if self.get_genesis_hash else None
        latest_snapshot_height = self.get_latest_snapshot_height() if self.get_latest_snapshot_height else None

        payload = StatusPayload(
            node_id=self.node_id,
            best_height=height,
            best_hash=last_hash,
            genesis_hash=genesis_hash,
            latest_snapshot_height=latest_snapshot_height,
            latest_snapshot_hash=None,
        )
        msg = P2PMessage(type=P2PMessageType.STATUS, payload=payload.model_dump())
        await self.send_message(writer, msg)

    async def send_peers(self, writer):
        peers = list(self.known_peers)
        msg = P2PMessage(type=P2PMessageType.PEERS, payload=PeersPayload(peers=peers).model_dump())
        await self.send_message(writer, msg)

    async def _status_loop(self):
        while True:
            await asyncio.sleep(self.STATUS_INTERVAL_SECONDS)
            for writer in list(self.writers):
                await self.send_status(writer)

    async def _ping_loop(self):
        while True:
            await asyncio.sleep(self.PING_INTERVAL_SECONDS)
            payload = PingPayload(timestamp=time.time())
            msg = P2PMessage(type=P2PMessageType.PING, payload=payload.model_dump())
            for writer in list(self.writers):
                await self.send_message(writer, msg)

    async def _peer_cleanup_loop(self):
        while True:
            await asyncio.sleep(self.PEER_TIMEOUT_SECONDS)
            now = time.time()
            for writer, peer in list(self.active_peers.items()):
                if now - peer.last_seen_at > self.PEER_TIMEOUT_SECONDS:
                    logger.warning(f"Peer timeout: {peer.persist_addr}")
                    if writer in self.active_peers:
                        del self.active_peers[writer]
                    if writer in self.writers:
                        self.writers.remove(writer)
                    try:
                        writer.close()
                    except Exception:
                        pass

            if self.sync_state == SyncState.SYNCING and self._syncing_with_peer not in self.active_peers:
                logger.warning("Sync peer gone. Retrying sync with another peer.")
                self.sync_state = SyncState.IDLE
                self._syncing_with_peer = None
                self._sync_started_at = 0
                self._sync_phase = None
                await self._trigger_catchup_sync()
