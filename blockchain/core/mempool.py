from typing import Dict, List, Optional, TYPE_CHECKING
import threading
from ...protocol.types.tx import Transaction
from ...protocol.crypto.keys import verify
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.config.params import GAS_PER_TYPE, CURRENT_NETWORK
from .events import event_bus  # Import at module level!
import logging

if TYPE_CHECKING:
    from .state import AccountState

logger = logging.getLogger(__name__)

MAX_TX_PER_SENDER = 1000  # Increased from 64 to handle high-load scenarios

class Mempool:
    def __init__(self, max_size: int = 100000, tx_ttl_seconds: int = 3600):  # Increased from 5000 to handle high-load
        self.transactions: Dict[str, Transaction] = {} # tx_hash -> Transaction
        self.tx_timestamps: Dict[str, float] = {}  # tx_hash -> timestamp (Phase 1.4 TTL)
        self.tx_ttl_seconds = tx_ttl_seconds  # Time-to-live for transactions (default: 1 hour)
        self.max_size = max_size
        self._lock = threading.Lock()

        # Phase 1.4.1: Nonce-aware mempool
        self.pending_queue: Dict[str, List[Transaction]] = {}  # address -> future nonce transactions
        self.pending_timestamps: Dict[str, float] = {}  # tx_hash -> timestamp for pending queue

    def _add_to_pool(self, tx: Transaction):
        """Internal helper to add transaction to main pool."""
        import time
        tx_hash = tx.hash_hex
        self.transactions[tx_hash] = tx
        self.tx_timestamps[tx_hash] = time.time()
        logger.info(f"Tx added to mempool: {tx_hash[:8]}...")

    def _promote_from_pending(self, address: str, state: 'AccountState'):
        """
        Move transactions from pending queue to main pool when nonces align.

        Phase 1.4.1: Nonce-aware mempool promotion logic with balance validation.
        """
        if address not in self.pending_queue:
            return

        account = state.get_account(address)
        expected_nonce = account.nonce

        # Promote transactions with matching nonces
        while self.pending_queue[address]:
            next_tx = self.pending_queue[address][0]
            if next_tx.nonce == expected_nonce:
                # Validate balance before promotion (balance may have changed while in queue)
                total_cost = next_tx.amount + next_tx.fee
                if account.balance < total_cost:
                    # Insufficient balance - remove from pending queue and don't promote
                    self.pending_queue[address].pop(0)
                    tx_hash = next_tx.hash_hex
                    if tx_hash in self.pending_timestamps:
                        del self.pending_timestamps[tx_hash]
                    logger.warning(f"Dropped tx {tx_hash[:8]} from pending queue: insufficient balance (have {account.balance}, need {total_cost})")
                    break  # Stop promotion chain - subsequent TX depend on this one

                # Balance OK - promote to main pool
                self.pending_queue[address].pop(0)
                self._add_to_pool(next_tx)
                expected_nonce += 1  # Next expected nonce
                logger.info(f"Promoted tx {next_tx.hash_hex[:8]} from pending queue (nonce={next_tx.nonce})")
            else:
                break  # Gap remains

        # Clean up empty pending queue
        if not self.pending_queue[address]:
            del self.pending_queue[address]

    def add_transaction(self, tx: Transaction, state: Optional['AccountState'] = None) -> tuple[bool, str]:
        """
        Adds transaction to mempool.
        Returns (True, "added") if added.
        Returns (False, reason) if rejected.
        """
        with self._lock:
            tx_hash = tx.hash_hex
            
            if tx_hash in self.transactions:
                return False, "already_in_pool"
            
            # Anti-Spam: 1. Check Min Gas Price
            if tx.gas_price < CURRENT_NETWORK.min_gas_price:
                msg = f"gas_price {tx.gas_price} < min {CURRENT_NETWORK.min_gas_price}"
                logger.warning(f"Reject tx {tx_hash[:8]}: {msg}")
                return False, msg
                
            # Anti-Spam: 2. Check Gas Limit & Fee
            base_gas = GAS_PER_TYPE.get(tx.tx_type)
            if base_gas is None:
                return False, "unknown_tx_type"
            
            if tx.gas_limit < base_gas:
                msg = f"gas_limit {tx.gas_limit} < base_gas {base_gas}"
                logger.warning(f"Reject tx {tx_hash[:8]}: {msg}")
                return False, msg
                
            needed_fee = base_gas * tx.gas_price
            if tx.fee < needed_fee:
                msg = f"fee {tx.fee} < needed_fee {needed_fee}"
                logger.warning(f"Reject tx {tx_hash[:8]}: {msg}")
                return False, msg

            if len(self.transactions) >= self.max_size:
                logger.warning("Mempool full, rejecting transaction")
                return False, "mempool_full"

            # Anti-Spam: 3. Per-Account Limit
            sender_tx_count = sum(1 for t in self.transactions.values() if t.from_address == tx.from_address)
            if sender_tx_count >= MAX_TX_PER_SENDER:
                logger.warning(f"Reject tx {tx_hash[:8]}: sender {tx.from_address} exceeded limits")
                return False, "sender_limit_exceeded"

            # Stateless Validation (Crypto)
            # 1. Check fields
            if not tx.signature or not tx.pub_key:
                 logger.warning(f"Rejecting tx {tx_hash[:8]}: missing signature/pub_key")
                 return False, "missing_sig_or_key"

            # 2. Check address derivation
            try:
                prefix = tx.from_address.split("1")[0]
                derived_addr = address_from_pubkey(bytes.fromhex(tx.pub_key), prefix=prefix)
                if derived_addr != tx.from_address:
                    logger.warning(f"Rejecting tx {tx_hash[:8]}: pub_key mismatch")
                    return False, "pub_key_mismatch"
            except Exception as e:
                 logger.warning(f"Rejecting tx {tx_hash[:8]}: invalid address/key: {e}")
                 return False, f"invalid_key_format: {e}"

            # 3. Verify signature
            try:
                msg_hash_bytes = bytes.fromhex(tx.hash())
                sig_bytes = bytes.fromhex(tx.signature)
                pub_bytes = bytes.fromhex(tx.pub_key)
                
                if not verify(msg_hash_bytes, sig_bytes, pub_bytes):
                     logger.warning(f"Rejecting tx {tx_hash[:8]}: invalid signature")
                     return False, "invalid_signature"
            except Exception as e:
                 logger.warning(f"Rejecting tx {tx_hash[:8]}: crypto error: {e}")
                 return False, f"crypto_error: {e}"

            # Phase 1.4.1: Nonce-aware mempool logic
            if state:
                account = state.get_account(tx.from_address)
                expected_nonce = account.nonce

                # Check balance early (Ethereum-style validation)
                # Calculate total cost: amount + fee
                total_cost = tx.amount + tx.fee
                if account.balance < total_cost:
                    logger.warning(f"Reject tx {tx_hash[:8]}: insufficient balance (have {account.balance}, need {total_cost})")
                    return False, "insufficient_balance"

                if tx.nonce < expected_nonce:
                    # Stale nonce - reject
                    logger.warning(f"Reject tx {tx_hash[:8]}: nonce too low ({tx.nonce} < {expected_nonce})")
                    return False, "nonce_too_low"
                elif tx.nonce == expected_nonce:
                    # Perfect - add to main pool
                    self._add_to_pool(tx)

                    # Try to promote any pending transactions
                    self._promote_from_pending(tx.from_address, state)
                    return True, "added"
                else:
                    # Future nonce - add to pending queue
                    # Note: balance may change before this TX is promoted, so we re-check during promotion
                    import time
                    if tx.from_address not in self.pending_queue:
                        self.pending_queue[tx.from_address] = []
                    self.pending_queue[tx.from_address].append(tx)
                    self.pending_queue[tx.from_address].sort(key=lambda t: t.nonce)
                    self.pending_timestamps[tx_hash] = time.time()
                    logger.info(f"Tx {tx_hash[:8]} queued in pending (nonce={tx.nonce}, expected={expected_nonce})")
                    return True, "queued_future_nonce"
            else:
                # No state available (old path) - just add to pool
                self._add_to_pool(tx)
                return True, "added"

    def get_transactions(self, max_count: int) -> List[Transaction]:
        """
        Returns transactions sorted by gas price (DESC), then nonce (ASC).
        This creates a priority queue favoring high-fee transactions while
        maintaining nonce sequence per sender.

        Phase 1.4.1: Optimized with heapq for O(n log m) complexity.
        """
        with self._lock:
            if not self.transactions:
                return []

            # Group transactions by sender for nonce ordering
            by_sender: Dict[str, List[Transaction]] = {}
            for tx in self.transactions.values():
                if tx.from_address not in by_sender:
                    by_sender[tx.from_address] = []
                by_sender[tx.from_address].append(tx)

            # Sort each sender's transactions by nonce (maintain sequence)
            for addr in by_sender:
                by_sender[addr].sort(key=lambda tx: tx.nonce)

            # Build priority heap: O(m) initialization where m = num_senders
            import heapq
            heap = []
            for addr, txs in by_sender.items():
                if txs:
                    # Use negative gas_price for max-heap behavior (heapq is min-heap)
                    # Tuple: (-gas_price, address) for priority ordering
                    heapq.heappush(heap, (-txs[0].gas_price, addr))

            # Extract transactions: O(n log m) where n = result count
            result: List[Transaction] = []
            while heap and len(result) < max_count:
                neg_gas_price, addr = heapq.heappop(heap)

                # Take first transaction from this sender
                tx = by_sender[addr].pop(0)
                result.append(tx)

                # If sender has more transactions, add back to heap
                if by_sender[addr]:
                    heapq.heappush(heap, (-by_sender[addr][0].gas_price, addr))

            return result

    def remove_transactions(self, txs: List[Transaction]):
        """Removes transactions from pool (e.g. after block inclusion)."""
        with self._lock:
            for tx in txs:
                tx_hash = tx.hash_hex
                if tx_hash in self.transactions:
                    del self.transactions[tx_hash]
                    if tx_hash in self.tx_timestamps:  # Also remove timestamp (Phase 1.4 TTL)
                        del self.tx_timestamps[tx_hash]

    def size(self) -> int:
        with self._lock:
            return len(self.transactions)

    def prune_stale_transactions(self, state: 'AccountState') -> int:
        """
        Removes transactions with stale nonces (nonce < account's current nonce).
        Returns the number of transactions removed.
        """
        with self._lock:
            stale_txs = []
            for tx_hash, tx in self.transactions.items():
                try:
                    account = state.get_account(tx.from_address)
                    if tx.nonce < account.nonce:
                        stale_txs.append(tx_hash)
                except Exception as e:
                    # If we can't get account state, keep the transaction
                    logger.debug(f"Could not check nonce for tx {tx_hash[:8]}: {e}")

            # Remove stale transactions
            for tx_hash in stale_txs:
                del self.transactions[tx_hash]

            if stale_txs:
                logger.info(f"Pruned {len(stale_txs)} stale transactions from mempool")

            return len(stale_txs)

    def cleanup_expired(self) -> int:
        """
        Removes transactions that exceeded TTL (Time-To-Live).

        Phase 1.4: Prevents mempool from accumulating old pending transactions.
        Phase 1.4.1: Also cleans up pending queue.

        Returns:
            The number of expired transactions removed.
        """
        import time

        with self._lock:
            now = time.time()
            expired_txs = []

            # Find expired transactions in main pool
            for tx_hash, timestamp in self.tx_timestamps.items():
                age = now - timestamp
                if age > self.tx_ttl_seconds:
                    expired_txs.append(tx_hash)

            # Remove expired transactions from main pool
            for tx_hash in expired_txs:
                if tx_hash in self.transactions:
                    del self.transactions[tx_hash]
                if tx_hash in self.tx_timestamps:
                    del self.tx_timestamps[tx_hash]

                # Mark as expired in receipt store and emit event
                try:
                    from computechain.blockchain.core.tx_receipt import tx_receipt_store
                    tx_receipt_store.mark_expired(tx_hash)

                    # Emit tx_failed event to notify subscribers (e.g., NonceManager)
                    event_bus.emit('tx_failed',
                                  tx_hash=tx_hash,
                                  error="Transaction expired (TTL exceeded)")
                except Exception as e:
                    logger.debug(f"Could not mark tx {tx_hash[:8]} as expired: {e}")

            # Phase 1.4.1: Clean up expired transactions from pending queue
            expired_pending = []
            for tx_hash, timestamp in self.pending_timestamps.items():
                age = now - timestamp
                if age > self.tx_ttl_seconds:
                    expired_pending.append(tx_hash)

            # Remove expired transactions from pending queue
            for tx_hash in expired_pending:
                # Find and remove from pending queue
                for address, pending_txs in list(self.pending_queue.items()):
                    self.pending_queue[address] = [tx for tx in pending_txs if tx.hash_hex != tx_hash]
                    if not self.pending_queue[address]:
                        del self.pending_queue[address]

                if tx_hash in self.pending_timestamps:
                    del self.pending_timestamps[tx_hash]

                # Mark as expired
                try:
                    from computechain.blockchain.core.tx_receipt import tx_receipt_store
                    tx_receipt_store.mark_expired(tx_hash)
                    event_bus.emit('tx_failed',
                                  tx_hash=tx_hash,
                                  error="Transaction expired in pending queue (TTL exceeded)")
                except Exception as e:
                    logger.debug(f"Could not mark pending tx {tx_hash[:8]} as expired: {e}")

            total_expired = len(expired_txs) + len(expired_pending)
            if total_expired > 0:
                logger.info(f"Cleaned up {len(expired_txs)} expired TX from mempool, "
                           f"{len(expired_pending)} from pending queue (TTL={self.tx_ttl_seconds}s)")

            return total_expired
