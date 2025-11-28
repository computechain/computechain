from enum import Enum
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class P2PMessageType(str, Enum):
    HANDSHAKE = "handshake"
    NEW_BLOCK = "new_block"
    NEW_TX = "new_tx"
    GET_BLOCKS = "get_blocks" # Sync request
    BLOCKS_RESPONSE = "blocks_response" # Sync response

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

class GetBlocksPayload(BaseModel):
    from_height: int
    to_height: int

class BlocksResponsePayload(BaseModel):
    blocks: List[Dict[str, Any]] # Serialized blocks

class NewBlockPayload(BaseModel):
    block: Dict[str, Any] 

class NewTxPayload(BaseModel):
    tx: Dict[str, Any]
