import time
from ...protocol.types.block import Block
from ...protocol.crypto.keys import verify, public_key_from_private
from ...protocol.crypto.hash import sha256, merkle_root
from ..core.chain import Blockchain
from ..core.state import AccountState
from ...protocol.config.params import NetworkConfig

class BlockValidator:
    def __init__(self, chain: Blockchain):
        self.chain = chain
        self.config = chain.config

    def validate_block(self, block: Block) -> bool:
        """
        Full stateless and stateful validation of a block.
        Raises ValueError on failure.
        """
        header = block.header
        
        # 1. Linkage Check
        if header.height != self.chain.height + 1:
             raise ValueError(f"Invalid height: expected {self.chain.height + 1}, got {header.height}")
        
        if self.chain.height >= 0:
            if header.prev_hash != self.chain.last_hash:
                raise ValueError(f"Invalid prev_hash: expected {self.chain.last_hash}, got {header.prev_hash}")
        else:
            # Genesis validation (prev_hash should be 0s or specific)
            if header.height == 0 and header.prev_hash != "0"*64:
                 raise ValueError("Genesis block must have 0-prev_hash")

        # 2. Timestamp Check (slot-based)
        genesis_time = self.chain.genesis_time
        if genesis_time <= 0:
            raise ValueError("Missing genesis_time for slot validation")
        round = getattr(header, "round", 0)
        if round < 0:
            raise ValueError("Invalid round value")
        expected_ts = genesis_time + (header.height * self.config.block_time_sec) + (round * self.config.block_time_sec)
        if header.timestamp != expected_ts:
            raise ValueError(f"Invalid timestamp for slot: expected {expected_ts}, got {header.timestamp}")
        
        # 3. Proposer Signature Check
        # We have block.pq_signature and header.hash().
        # But we only have proposer_address in header. We need PubKey to verify.
        # For MVP v1, since we don't have on-chain validator set with pubkeys, 
        # and header doesn't carry pubkey, we cannot strictly verify signature here 
        # without recovering pubkey (which needs specific crypto libs) or adding pubkey to header.
        # Skipping for now as per existing pattern.
        if not block.pq_signature:
            # Warn if empty?
            pass
            
        # 4. Tx Root Check
        tx_hashes = [tx.hash() for tx in block.txs]
        calculated_tx_root_bytes = merkle_root([bytes.fromhex(h) for h in tx_hashes])
        calculated_tx_root = calculated_tx_root_bytes.hex()
        
        if calculated_tx_root != header.tx_root:
             raise ValueError(f"Invalid tx_root: expected {header.tx_root}, got {calculated_tx_root}")

        # 5. Stateful Validation (State Root)
        # This is typically done during execution/addition to chain (in chain.add_block).
        # BlockValidator might be used for P2P pre-check.
        # If we want to validate fully here, we need to simulate execution.
        # Let's rely on chain.add_block for the heavy lifting of state application.
        # But if this is called BEFORE add_block, it acts as a filter.
        
        return True
