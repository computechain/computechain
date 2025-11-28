import asyncio
import json
import logging
from enum import Enum, auto
from typing import List, Dict, Callable, Optional, Set
from .protocol import (
    P2PMessage, P2PMessageType, 
    HandshakePayload, GetBlocksPayload, BlocksResponsePayload
)
from ...protocol.types.block import Block
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
        
        self.active_peers: Dict[asyncio.StreamWriter, Peer] = {}
        self.known_peers: Set[str] = set(initial_peers) # Persistable set of "addr:port"
        self.writers: List[asyncio.StreamWriter] = [] 
        self.server = None
        self.node_id = f"{host}:{port}" 
        
        # Start in SYNCING state to prevent mining before checking peers
        self.sync_state: SyncState = SyncState.SYNCING if initial_peers else SyncState.SYNCED
        self.MAX_BLOCKS_PER_MESSAGE = 500
        self._initial_sync_done = False

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_connection, self.host, self.port
        )
        logger.info(f"P2P Server listening on {self.host}:{self.port}")

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
            # logger.info("Connection closed") # Duplicate log usually
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
                
            elif msg.type == P2PMessageType.NEW_BLOCK:
                await self.handle_new_block(msg.payload)
                    
            elif msg.type == P2PMessageType.NEW_TX:
                await self.handle_new_tx(msg.payload)
            
            elif msg.type == P2PMessageType.GET_BLOCKS:
                await self.handle_get_blocks(writer, msg.payload)
                
            elif msg.type == P2PMessageType.BLOCKS_RESPONSE:
                await self.handle_blocks_response(writer, msg.payload)
                    
        except Exception as e:
            logger.error(f"Failed to process message: {e}")

    # --- Handlers ---

    async def handle_handshake(self, writer, payload_dict):
        payload = HandshakePayload(**payload_dict)
        
        if writer in self.active_peers:
            # Update existing
            peer = self.active_peers[writer]
            peer.best_height = payload.best_height
            peer.best_hash = payload.best_hash
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

        # Check Sync
        my_height = self.get_current_height() if self.get_current_height else -1
        if peer.best_height > my_height:
            await self.start_sync(peer)
        else:
            self.sync_state = SyncState.SYNCED

    async def handle_new_block(self, payload_dict):
        if self.sync_state == SyncState.SYNCING:
            return

        if self.on_new_block:
            block = Block.model_validate(payload_dict['block'])
            try:
                await self.on_new_block(block)
            except Exception as e:
                logger.warning(f"Rejected P2P block: {e}")

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

    async def handle_blocks_response(self, writer, payload_dict):
        if self.sync_state != SyncState.SYNCING:
            return
            
        resp = BlocksResponsePayload(**payload_dict)
        if not resp.blocks:
            self.sync_state = SyncState.SYNCED
            logger.info("Sync finished (no more blocks)")
            return

        added_count = 0
        for b_data in resp.blocks:
            block = Block.model_validate(b_data)
            if self.on_new_block:
                try:
                    await self.on_new_block(block)
                    added_count += 1
                except Exception as e:
                    logger.error(f"Sync failed at block {block.header.height}: {e}")
                    self.sync_state = SyncState.IDLE 
                    return

        logger.info(f"Synced {added_count} blocks. Last: {block.header.height}")
        
        peer = self.active_peers.get(writer)
        my_height = self.get_current_height()
        
        if peer and my_height < peer.best_height:
            await self.request_blocks(peer, my_height + 1, peer.best_height)
        else:
            self.sync_state = SyncState.SYNCED
            logger.info("Sync finished (caught up)")

    # --- Actions ---

    async def start_sync(self, peer: Peer):
        logger.info(f"Starting sync with {peer.persist_addr}. My height: {self.get_current_height()}, Peer: {peer.best_height}")
        self.sync_state = SyncState.SYNCING
        my_height = self.get_current_height()
        await self.request_blocks(peer, my_height + 1, peer.best_height)

    async def request_blocks(self, peer: Peer, from_h: int, to_h: int):
        if to_h - from_h + 1 > self.MAX_BLOCKS_PER_MESSAGE:
            to_h = from_h + self.MAX_BLOCKS_PER_MESSAGE - 1
            
        payload = GetBlocksPayload(from_height=from_h, to_height=to_h)
        msg = P2PMessage(type=P2PMessageType.GET_BLOCKS, payload=payload.model_dump())
        await self.send_message(peer.writer, msg)

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

        payload = HandshakePayload(
            node_id=self.node_id,
            p2p_port=self.port,
            network=self.network_id,
            best_height=height,
            best_hash=last_hash,
            genesis_hash=genesis_hash
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

    async def broadcast(self, msg: P2PMessage):
        for writer in self.writers:
            await self.send_message(writer, msg)
