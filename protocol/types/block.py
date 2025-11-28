from pydantic import BaseModel
from typing import List
from .tx import Transaction
from ..crypto.hash import sha256_hex

class BlockHeader(BaseModel):
    height: int                 # block number
    prev_hash: str              # hex string of SHA256 of previous block
    timestamp: int              # unix time
    chain_id: str               # "computechain-1"
    proposer_address: str       # validator address (cpcvalcons1...)
    
    tx_root: str                # Merkle root of all txs
    state_root: str             # Merkle root of state (accounts)
    compute_root: str = ""      # Merkle root of compute results (PoC)
    
    # Gas
    gas_used: int = 0
    gas_limit: int = 0
    
    # ZK Proofs (Placeholders)
    zk_state_proof_hash: str | None = None
    zk_compute_proof_hash: str | None = None

    def hash(self) -> str:
        # Important: hash is calculated only on header, without body
        payload = (
            str(self.height)
            + self.prev_hash
            + str(self.timestamp)
            + self.chain_id
            + self.proposer_address
            + self.tx_root
            + self.state_root
            + self.compute_root
            + str(self.gas_used)
            + str(self.gas_limit)
        )
        return sha256_hex(payload.encode("utf-8"))

class Block(BaseModel):
    header: BlockHeader
    txs: List[Transaction]
    
    # PQ Signature
    pq_signature: str = ""       # hex
    pq_sig_scheme_id: int = 1    # 1 = Dilithium3

    def hash(self) -> str:
        return self.header.hash()
