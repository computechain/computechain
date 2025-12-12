from enum import Enum, IntEnum

class TxType(str, Enum):
    TRANSFER = "TRANSFER"
    STAKE = "STAKE"
    UNSTAKE = "UNSTAKE"
    POC_REWARD = "POC_REWARD"   # System transaction
    SUBMIT_RESULT = "SUBMIT_RESULT" # Proof-of-Compute result submission

    # Phase 1: Validator Metadata
    UPDATE_VALIDATOR = "UPDATE_VALIDATOR"  # Update validator metadata

    # Phase 2: Delegation
    DELEGATE = "DELEGATE"       # Delegate tokens to validator
    UNDELEGATE = "UNDELEGATE"   # Undelegate tokens from validator

    # Phase 3: Governance
    UNJAIL = "UNJAIL"           # Request early release from jail

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

