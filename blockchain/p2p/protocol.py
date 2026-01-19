from enum import Enum
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class P2PMessageType(str, Enum):
    HANDSHAKE = "handshake"
    STATUS = "status"
    PING = "ping"
    PONG = "pong"
    NEW_BLOCK = "new_block"
    NEW_TX = "new_tx"
    GET_BLOCKS = "get_blocks" # Sync request
    BLOCKS_RESPONSE = "blocks_response" # Sync response
    GET_HEADERS = "get_headers"
    HEADERS_RESPONSE = "headers_response"
    PEERS = "peers"
    GET_SNAPSHOT = "get_snapshot"
    SNAPSHOT_CHUNK = "snapshot_chunk"

class P2PMessage(BaseModel):
    type: P2PMessageType
    payload: Dict[str, Any]

class HandshakePayload(BaseModel):
    node_id: str
    p2p_port: int
    protocol_version: int = 1
    network: str
    best_height: int
    best_hash: Optional[str] = None
    genesis_hash: Optional[str] = None
    latest_snapshot_height: Optional[int] = None
    latest_snapshot_hash: Optional[str] = None

class GetBlocksPayload(BaseModel):
    from_height: int
    to_height: int

class BlocksResponsePayload(BaseModel):
    blocks: List[Dict[str, Any]] # Serialized blocks

class GetHeadersPayload(BaseModel):
    from_height: int
    to_height: int

class HeadersResponsePayload(BaseModel):
    headers: List[Dict[str, Any]] # Serialized block headers

class StatusPayload(BaseModel):
    node_id: str
    best_height: int
    best_hash: Optional[str] = None
    genesis_hash: Optional[str] = None
    latest_snapshot_height: Optional[int] = None
    latest_snapshot_hash: Optional[str] = None

class PeersPayload(BaseModel):
    peers: List[str]

class PingPayload(BaseModel):
    timestamp: float

class PongPayload(BaseModel):
    timestamp: float

class GetSnapshotPayload(BaseModel):
    height: int

class SnapshotChunkPayload(BaseModel):
    height: int
    chunk_index: int
    total_chunks: int
    data_b64: str

class NewBlockPayload(BaseModel):
    block: Dict[str, Any] 

class NewTxPayload(BaseModel):
    tx: Dict[str, Any]
