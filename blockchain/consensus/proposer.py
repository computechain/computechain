import time
import logging
import threading
from typing import Optional, Callable
from ...protocol.types.block import Block, BlockHeader
from ...protocol.types.tx import Transaction
from ...protocol.crypto.keys import sign, public_key_from_private
from ...protocol.crypto import pq
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.crypto.hash import sha256, merkle_root
from ...protocol.config.params import GAS_PER_TYPE
from ..core.chain import Blockchain
from ..core.mempool import Mempool
from ..p2p.node import P2PNode, SyncState

logger = logging.getLogger(__name__)

class BlockProposer:
    def __init__(self,
                 chain: Blockchain,
                 mempool: Mempool,
                 priv_key_hex: str,
                 p2p_node: Optional[P2PNode] = None): # Inject P2P Node
        self.chain = chain
        self.mempool = mempool
        self.p2p_node = p2p_node
        self.priv_key = bytes.fromhex(priv_key_hex)
        self.pub_key = public_key_from_private(self.priv_key)
        self.address = address_from_pubkey(self.pub_key, prefix=chain.config.bech32_prefix_cons)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.on_block_created: Optional[Callable[[Block], None]] = None
        self.last_prune_time = 0  # Track last mempool prune time

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"BlockProposer started. Address: {self.address}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def _run_loop(self):
        while self.running:
            try:
                self._try_produce_block_step()

                # Prune stale transactions every 30 seconds
                now = int(time.time())
                if now - self.last_prune_time >= 30:
                    try:
                        # Phase 1.4: Cleanup expired TXs before pruning stale
                        self.mempool.cleanup_expired()
                        self.mempool.prune_stale_transactions(self.chain.state)
                        self.last_prune_time = now
                    except Exception as e:
                        logger.error(f"Error pruning stale transactions: {e}")
            except Exception as e:
                logger.error(f"Error in proposer loop: {e}")

            # Check frequency - 1s is enough for 10s block time
            time.sleep(1.0)

    def _try_produce_block_step(self):
        # Check Sync State
        if self.p2p_node and self.p2p_node.sync_state == SyncState.SYNCING:
            # Do not produce blocks while syncing
            return

        # 0. Determine Round Logic
        last_ts = self.chain.last_block_timestamp
        now = int(time.time())
        block_time = self.chain.config.block_time_sec
        
        if now <= last_ts:
            # Clock skew or just produced? Wait.
            return

        time_since_last = now - last_ts
        
        # If less than 1 block time, we are waiting for the first slot (Round 0) to open
        if time_since_last < block_time:
            return

        # Calculate round
        # Round 0 starts at last_ts + block_time
        # Round 1 starts at last_ts + 2*block_time
        round = int((time_since_last - block_time) // block_time)
        
        next_height = self.chain.height + 1
        
        # Check who is proposer for this (height, round)
        expected_proposer = self.chain.consensus.get_proposer(next_height, round)
        
        if not expected_proposer:
             if not self.chain.consensus.validator_set.validators:
                 # Bootstrap mode: anyone can mine if empty set? 
                 # Or genesis validator only. For now, if empty, we might skip or try.
                 pass
             else:
                 return

        if expected_proposer and expected_proposer.address != self.address:
            # Not my turn yet.
            # But I should keep checking, because if time passes, round increases, and it MIGHT become my turn.
            return

        # If we are here, it IS my turn!
        logger.info(f"It's my turn! Height: {next_height}, Round: {round} (Time since last: {time_since_last}s)")

        # 1. Get transactions
        txs = self.mempool.get_transactions(self.chain.config.max_tx_per_block)
        
        # 2. Prepare Header info
        height = next_height
        prev_hash = self.chain.last_hash
        timestamp = now
        
        # 3. Execute to get State Root (Simulate)
        # Create temp state to validate txs and calc state root
        tmp_state = self.chain.state.clone()
        valid_txs = []
        cumulative_gas = 0
        block_gas_limit = self.chain.config.block_gas_limit
        
        for tx in txs:
            # Check block gas limit
            tx_gas = GAS_PER_TYPE.get(tx.tx_type, 0)
            if cumulative_gas + tx_gas > block_gas_limit:
                # Block full
                break

            try:
                tmp_state.apply_transaction(tx, skip_crypto_check=True)
                valid_txs.append(tx)
                cumulative_gas += tx_gas
            except Exception as e:
                logger.warning(f"Skipping invalid tx {tx.hash()} in proposer: {e}")
        
        # Use only valid txs
        txs = valid_txs
        
        # Calculate State Root
        state_root = tmp_state.compute_state_root()
        
        # Calculate Compute Root
        compute_root = self.chain.compute_poc_root(txs)

        # 4. Calculate Tx Root
        tx_hashes = [tx.hash() for tx in txs]
        tx_root_bytes = merkle_root([bytes.fromhex(h) for h in tx_hashes])
        tx_root = tx_root_bytes.hex()
        
        # 5. Create Header
        header = BlockHeader(
            height=height,
            prev_hash=prev_hash,
            timestamp=timestamp,
            chain_id=self.chain.config.chain_id,
            proposer_address=self.address,
            tx_root=tx_root,
            state_root=state_root,
            compute_root=compute_root,
            gas_used=cumulative_gas,
            gas_limit=block_gas_limit
        )

        # 6. Sign (PQ)
        # Block hash is the header hash
        block_hash_bytes = bytes.fromhex(header.hash())
        # Use PQ sign (currently wrapping secp)
        pq_signature = pq.sign(block_hash_bytes, self.priv_key).hex()

        # 7. Create Block
        block = Block(
            header=header,
            txs=txs,
            pq_signature=pq_signature,
            pq_sig_scheme_id=pq.SCHEME_ID
        )

        # 8. Add to local chain
        # Note: This will re-verify/re-apply but it's safer and ensures consistency
        if self.chain.add_block(block):
            # Remove transactions from mempool
            self.mempool.remove_transactions(txs)

            # Phase 1.4.1: Promote pending transactions after block inclusion
            # Promote ALL addresses in pending queue, not just processed TX senders
            # This fixes the deadlock when mempool is empty but pending_queue has TX
            if hasattr(self.mempool, 'pending_queue'):
                for address in list(self.mempool.pending_queue.keys()):
                    try:
                        self.mempool._promote_from_pending(address, self.chain.state)
                    except Exception as e:
                        logger.warning(f"Error promoting pending txs for {address[:10]}...: {e}")

            # Prune stale transactions (transactions with old nonces)
            try:
                # Phase 1.4: Cleanup expired TXs before pruning stale
                self.mempool.cleanup_expired()
                self.mempool.prune_stale_transactions(self.chain.state)
            except Exception as e:
                logger.error(f"Error pruning stale transactions: {e}")

            logger.info(f"Produced block {height} (I am proposer, Round {round})")

            # Notify callback (e.g. P2P broadcast)
            if self.on_block_created:
                try:
                    self.on_block_created(block)
                except Exception as e:
                    logger.error(f"Error in on_block_created callback: {e}")
        else:
            logger.error("Failed to add own produced block")
