from typing import Dict, List, Optional, TYPE_CHECKING
import threading
from ...protocol.types.tx import Transaction
from ...protocol.crypto.keys import verify
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.config.params import GAS_PER_TYPE, CURRENT_NETWORK
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

    def add_transaction(self, tx: Transaction) -> tuple[bool, str]:
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

            import time
            self.transactions[tx_hash] = tx
            self.tx_timestamps[tx_hash] = time.time()  # Track timestamp for TTL (Phase 1.4)
            logger.info(f"Tx added to mempool: {tx_hash[:8]}...")
            return True, "added"

    def get_transactions(self, max_count: int) -> List[Transaction]:
        """
        Returns up to max_count transactions for block inclusion.
        Simple FIFO for MVP.
        """
        with self._lock:
            # In real implementation: sort by gas_price
            return list(self.transactions.values())[:max_count]

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

        Returns:
            The number of expired transactions removed.
        """
        import time

        with self._lock:
            now = time.time()
            expired_txs = []

            # Find expired transactions
            for tx_hash, timestamp in self.tx_timestamps.items():
                age = now - timestamp
                if age > self.tx_ttl_seconds:
                    expired_txs.append(tx_hash)

            # Remove expired transactions
            for tx_hash in expired_txs:
                if tx_hash in self.transactions:
                    del self.transactions[tx_hash]
                if tx_hash in self.tx_timestamps:
                    del self.tx_timestamps[tx_hash]

                # Mark as expired in receipt store
                try:
                    from computechain.blockchain.core.tx_receipt import tx_receipt_store
                    tx_receipt_store.mark_expired(tx_hash)
                except Exception as e:
                    logger.debug(f"Could not mark tx {tx_hash[:8]} as expired: {e}")

            if expired_txs:
                logger.info(f"Cleaned up {len(expired_txs)} expired transactions from mempool (TTL={self.tx_ttl_seconds}s)")

            return len(expired_txs)
