from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from ..crypto.hash import sha256, sha256_hex
from .common import TxType
from ..crypto.keys import sign as crypto_sign

# Note: TxType is imported from common to share with other modules

class Transaction(BaseModel):
    tx_type: TxType
    from_address: str
    to_address: Optional[str] = None # Can be None for STAKE
    amount: int          # in minimal units (10^-6 CPC)
    fee: int = 0         # fixed fee for MVP
    nonce: int
    signature: str = ""  # hex ECDSA, default empty
    pub_key: str = ""    # hex public key of sender
    payload: Dict[str, Any] = Field(default_factory=dict) # Extra data
    
    # Fields for compatibility with old/new models if any mix
    gas_price: int = 0
    gas_limit: int = 0

    def hash(self) -> str:
        # Handle optional fields safely for hashing
        to_addr = self.to_address if self.to_address else ""
        
        payload_str = (
            self.tx_type.value
            + self.from_address
            + to_addr
            + str(self.amount)
            + str(self.fee)
            + str(self.nonce)
            + self.pub_key  # Include pub_key in hash
        )
        return sha256_hex(payload_str.encode("utf-8"))

    @property
    def hash_hex(self) -> str:
        """Returns hash as hex string (for compatibility)."""
        return self.hash()

    def sign(self, priv_key_bytes: bytes):
        """Signs the transaction hash."""
        msg_hash = bytes.fromhex(self.hash())
        self.signature = crypto_sign(msg_hash, priv_key_bytes).hex()
