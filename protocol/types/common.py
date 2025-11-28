from enum import Enum, IntEnum

class TxType(str, Enum):
    TRANSFER = "TRANSFER"
    STAKE = "STAKE"
    UNSTAKE = "UNSTAKE"
    POC_REWARD = "POC_REWARD"   # System transaction
    SUBMIT_RESULT = "SUBMIT_RESULT" # Proof-of-Compute result submission

class MessageType(IntEnum):
    HANDSHAKE = 1
    NEW_BLOCK = 2
    NEW_TX = 3
    GET_BLOCKS = 4
    BLOCKS_RANGE = 5

class ProtocolError(Exception):
    pass

class ValidationError(ProtocolError):
    pass

