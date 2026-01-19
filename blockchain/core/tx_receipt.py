"""
Transaction receipt tracking.

Stores the lifecycle status of transactions for querying.
"""
from dataclasses import dataclass
from typing import Optional, Dict
import time
import logging
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass
class TxReceipt:
    """
    Transaction receipt containing confirmation status.

    Attributes:
        tx_hash: Transaction hash
        status: Transaction status ('pending', 'confirmed', 'failed')
        block_height: Block height where TX was included (None if pending/failed)
        timestamp: When receipt was created (unix timestamp)
        error: Error message if TX failed (None otherwise)
        confirmations: Number of confirmations (current_height - block_height + 1)
    """
    tx_hash: str
    status: str  # 'pending', 'confirmed', 'failed'
    block_height: Optional[int] = None
    timestamp: int = 0
    error: Optional[str] = None

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())

    def to_dict(self) -> dict:
        """Convert receipt to dictionary for API response."""
        return {
            "tx_hash": self.tx_hash,
            "status": self.status,
            "block_height": self.block_height,
            "timestamp": self.timestamp,
            "error": self.error,
        }


class TxReceiptStore:
    """
    In-memory store for transaction receipts.

    Thread-safe storage with automatic cleanup of old receipts.
    """

    def __init__(self, max_receipts: int = 10000):
        """
        Initialize receipt store.

        Args:
            max_receipts: Maximum number of receipts to keep in memory
        """
        self.receipts: Dict[str, TxReceipt] = {}
        self.max_receipts = max_receipts
        self.lock = RLock()

    def add_pending(self, tx_hash: str) -> TxReceipt:
        """
        Add a pending transaction receipt.

        Args:
            tx_hash: Transaction hash

        Returns:
            Created receipt
        """
        with self.lock:
            existing = self.receipts.get(tx_hash)
            if existing and existing.status == 'confirmed':
                return existing

            receipt = TxReceipt(
                tx_hash=tx_hash,
                status='pending',
            )
            self.receipts[tx_hash] = receipt

            # Cleanup old receipts if needed
            if len(self.receipts) > self.max_receipts:
                self._cleanup_old_receipts()

            logger.debug(f"Added pending receipt: {tx_hash[:16]}...")
            return receipt

    def mark_confirmed(self, tx_hash: str, block_height: int) -> Optional[TxReceipt]:
        """
        Mark transaction as confirmed.

        Args:
            tx_hash: Transaction hash
            block_height: Block height where TX was included

        Returns:
            Updated receipt, or None if not found
        """
        with self.lock:
            receipt = self.receipts.get(tx_hash)
            confirmation_time = None

            if not receipt:
                # Create receipt if it doesn't exist (TX was never tracked as pending)
                receipt = TxReceipt(
                    tx_hash=tx_hash,
                    status='confirmed',
                    block_height=block_height,
                )
                self.receipts[tx_hash] = receipt
            else:
                # Calculate confirmation time (from pending to confirmed)
                old_timestamp = receipt.timestamp
                receipt.status = 'confirmed'
                receipt.block_height = block_height
                receipt.timestamp = int(time.time())
                confirmation_time = receipt.timestamp - old_timestamp

            # Update Prometheus metrics (Phase 1.4)
            if confirmation_time is not None:
                try:
                    from blockchain.observability.metrics import tx_confirmation_time_seconds
                    tx_confirmation_time_seconds.observe(confirmation_time)
                except Exception as e:
                    logger.debug(f"Failed to update confirmation time metric: {e}")

            logger.debug(f"Marked confirmed: {tx_hash[:16]}... at height {block_height}" +
                        (f" (confirmation_time={confirmation_time}s)" if confirmation_time else ""))
            return receipt

    def mark_failed(self, tx_hash: str, error: str) -> Optional[TxReceipt]:
        """
        Mark transaction as failed.

        Args:
            tx_hash: Transaction hash
            error: Error message

        Returns:
            Updated receipt, or None if not found
        """
        with self.lock:
            receipt = self.receipts.get(tx_hash)
            if not receipt:
                # Create receipt if it doesn't exist
                receipt = TxReceipt(
                    tx_hash=tx_hash,
                    status='failed',
                    error=error,
                )
                self.receipts[tx_hash] = receipt
            else:
                receipt.status = 'failed'
                receipt.error = error
                receipt.timestamp = int(time.time())

            logger.debug(f"Marked failed: {tx_hash[:16]}... - {error}")
            return receipt

    def mark_expired(self, tx_hash: str) -> Optional[TxReceipt]:
        """
        Mark a transaction as expired (TTL exceeded in mempool).

        Args:
            tx_hash: Transaction hash

        Returns:
            Updated receipt
        """
        return self.mark_failed(tx_hash, "Transaction expired (TTL exceeded)")

    def get(self, tx_hash: str) -> Optional[TxReceipt]:
        """
        Get receipt for transaction.

        Args:
            tx_hash: Transaction hash

        Returns:
            Receipt if found, None otherwise
        """
        with self.lock:
            return self.receipts.get(tx_hash)

    def get_confirmations(self, tx_hash: str, current_height: int) -> Optional[int]:
        """
        Get number of confirmations for a transaction.

        Args:
            tx_hash: Transaction hash
            current_height: Current blockchain height

        Returns:
            Number of confirmations, or None if TX not found or not confirmed
        """
        with self.lock:
            receipt = self.receipts.get(tx_hash)
            if not receipt or receipt.status != 'confirmed' or receipt.block_height is None:
                return None

            return current_height - receipt.block_height + 1

    def _cleanup_old_receipts(self) -> None:
        """
        Remove oldest receipts to stay under max_receipts limit.

        Removes 10% of oldest receipts when limit is exceeded.
        """
        num_to_remove = len(self.receipts) // 10  # Remove 10%

        # Sort by timestamp (oldest first)
        sorted_receipts = sorted(
            self.receipts.items(),
            key=lambda x: x[1].timestamp
        )

        for tx_hash, _ in sorted_receipts[:num_to_remove]:
            del self.receipts[tx_hash]

        logger.info(f"Cleaned up {num_to_remove} old receipts (total: {len(self.receipts)})")

    def clear(self) -> None:
        """Clear all receipts (for testing)."""
        with self.lock:
            self.receipts.clear()
            logger.debug("Cleared all receipts")


# Global receipt store instance
tx_receipt_store = TxReceiptStore()
