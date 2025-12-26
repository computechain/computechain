#!/usr/bin/env python3
"""
Nonce Manager with Pending Transaction Tracking
Решает проблему nonce race condition при высокой нагрузке
"""

import time
import logging
import threading
from typing import Dict, Set, Optional, Callable
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class PendingTransaction:
    """Информация о pending транзакции."""

    def __init__(self, tx_hash: str, nonce: int, timestamp: float):
        self.tx_hash = tx_hash
        self.nonce = nonce
        self.timestamp = timestamp
        self.confirmed = False
        self.failed = False

    def __repr__(self):
        status = "confirmed" if self.confirmed else ("failed" if self.failed else "pending")
        return f"PendingTx(hash={self.tx_hash[:8]}..., nonce={self.nonce}, status={status})"


class NonceManager:
    """
    Управление nonce с отслеживанием pending транзакций.

    Решает nonce race condition путём:
    1. Отслеживания blockchain_nonce (подтверждённый из блокчейна)
    2. Отслеживания pending_nonce (следующий доступный с учётом pending TX)
    3. Автоматической ресинхронизации при сбоях
    """

    def __init__(self, get_blockchain_nonce: Callable[[str], int]):
        """
        Args:
            get_blockchain_nonce: Функция для получения nonce из блокчейна

        Phase 1.4: Uses event-based transaction tracking only.
        Aggressive cleanup has been REMOVED for safety.
        """
        self.get_blockchain_nonce = get_blockchain_nonce

        # Подтверждённый nonce из блокчейна
        self.blockchain_nonce: Dict[str, int] = {}

        # Pending транзакции для каждого адреса
        # Phase 1.4.1: Removed pending_nonce dict - calculated dynamically in get_next_nonce()
        self.pending_txs: Dict[str, deque] = defaultdict(deque)

        # Множество tx_hash для быстрой проверки
        self.pending_hashes: Set[str] = set()

        # Время последней синхронизации с блокчейном
        self.last_sync: Dict[str, float] = {}

        # Блокировка для thread-safety
        self.lock = threading.RLock()

        # Настройки (Phase 1.4.1: Optimized for high-load scenarios)
        self.sync_interval = 60  # Ресинхронизация каждые 60 сек (не слишком часто)
        self.tx_timeout = 600  # Таймаут для pending TX (10 минут - терпеливо ждём в high load)

        # Статистика
        self.stats = {
            'total_pending': 0,
            'total_confirmed': 0,
            'total_failed': 0,
            'resyncs': 0,
            'event_confirmations': 0,  # Track event-based confirmations (Phase 1.4)
        }

    def get_next_nonce(self, address: str) -> int:
        """
        Получить следующий доступный nonce для адреса.

        Phase 1.4.1: SEQUENTIAL gap-filling algorithm.
        Always returns the FIRST missing nonce in the sequence,
        ensuring no gaps and no duplicates.

        Returns:
            Nonce для новой транзакции
        """
        with self.lock:
            # Проверяем нужна ли синхронизация
            self._maybe_sync(address)

            # Get blockchain nonce (confirmed up to this point)
            blockchain_nonce = self.blockchain_nonce.get(address, 0)

            # Get all pending (unconfirmed, unfailed) nonces for this address
            pending_nonces = sorted([
                tx.nonce for tx in self.pending_txs.get(address, [])
                if not tx.confirmed and not tx.failed
            ])

            # Find the first missing nonce in the sequence
            expected_nonce = blockchain_nonce
            for pending_nonce in pending_nonces:
                if pending_nonce == expected_nonce:
                    # This nonce is already pending, move to next
                    expected_nonce += 1
                elif pending_nonce > expected_nonce:
                    # Gap found! Return the missing nonce to fill the gap
                    logger.debug(f"get_next_nonce({address[:10]}...): {expected_nonce} "
                                f"(GAP FILL - blockchain: {blockchain_nonce}, "
                                f"pending: {pending_nonces})")
                    return expected_nonce
                # if pending_nonce < expected_nonce, it's stale (already confirmed), skip

            # No gaps found, return next sequential nonce
            logger.debug(f"get_next_nonce({address[:10]}...): {expected_nonce} "
                        f"(blockchain: {blockchain_nonce}, pending: {len(pending_nonces)})")

            return expected_nonce

    def on_tx_sent(self, address: str, tx_hash: str, nonce: int) -> None:
        """
        Вызывается когда транзакция успешно отправлена в mempool.

        Args:
            address: Адрес отправителя
            tx_hash: Hash транзакции
            nonce: Nonce транзакции

        Phase 1.4.1: Simplified - no longer tracks pending_nonce here.
        Next nonce is calculated dynamically in get_next_nonce().
        """
        with self.lock:
            # Создаём pending транзакцию
            pending_tx = PendingTransaction(tx_hash, nonce, time.time())

            # Добавляем в очередь pending транзакций
            self.pending_txs[address].append(pending_tx)
            self.pending_hashes.add(tx_hash)

            # Статистика
            self.stats['total_pending'] += 1

            logger.debug(f"on_tx_sent({address[:10]}...): tx={tx_hash[:8]}..., nonce={nonce}, "
                        f"pending_count={len(self.pending_txs[address])}")

    def on_tx_confirmed(self, address: str, tx_hash: str, nonce: int) -> None:
        """
        Вызывается когда транзакция подтверждена в блоке (Phase 1.4).

        Args:
            address: Адрес отправителя
            tx_hash: Hash транзакции
            nonce: Nonce транзакции
        """
        with self.lock:
            # Обновляем blockchain_nonce
            if nonce >= self.blockchain_nonce.get(address, 0):
                self.blockchain_nonce[address] = nonce + 1

            # Помечаем транзакцию как подтверждённую
            if tx_hash in self.pending_hashes:
                for pending_tx in self.pending_txs.get(address, []):
                    if pending_tx.tx_hash == tx_hash:
                        pending_tx.confirmed = True
                        break

                self.pending_hashes.remove(tx_hash)
                self.stats['total_confirmed'] += 1
                self.stats['event_confirmations'] += 1  # NEW: track event-based confirmations

            # Чистим подтверждённые транзакции
            self._cleanup_confirmed(address)

            logger.debug(f"on_tx_confirmed({address[:10]}...): tx={tx_hash[:8]}..., nonce={nonce}, "
                        f"blockchain_nonce={self.blockchain_nonce[address]}")

    def on_tx_failed(self, address: str, tx_hash: str, nonce: int, reason: str = "") -> None:
        """
        Вызывается когда транзакция отклонена или провалилась.

        Args:
            address: Адрес отправителя
            tx_hash: Hash транзакции
            nonce: Nonce транзакции
            reason: Причина отклонения
        """
        with self.lock:
            # Помечаем транзакцию как failed
            if tx_hash in self.pending_hashes:
                for pending_tx in self.pending_txs.get(address, []):
                    if pending_tx.tx_hash == tx_hash:
                        pending_tx.failed = True
                        break

                self.pending_hashes.remove(tx_hash)
                self.stats['total_failed'] += 1

            logger.warning(f"on_tx_failed({address[:10]}...): tx={tx_hash[:8]}..., nonce={nonce}, "
                          f"reason={reason}")

            # Ресинхронизация с блокчейном
            self._force_sync(address)

    def check_timeouts(self) -> None:
        """
        Проверяет pending транзакции на таймаут и ресинхронизирует.
        Должна вызываться периодически (например, каждые 10 секунд).

        Phase 1.4.1: More tolerant timeout handling - don't trigger full resync
        for every timeout. Just mark as failed and clean up.
        """
        with self.lock:
            now = time.time()
            addresses_to_sync = set()

            for address in list(self.pending_txs.keys()):
                timed_out_count = 0

                for pending_tx in list(self.pending_txs[address]):
                    age = now - pending_tx.timestamp

                    if age > self.tx_timeout and not pending_tx.confirmed and not pending_tx.failed:
                        logger.warning(f"Pending TX timeout: {pending_tx.tx_hash[:8]}... "
                                      f"(age={age:.0f}s, nonce={pending_tx.nonce})")

                        # Помечаем как failed
                        pending_tx.failed = True
                        if pending_tx.tx_hash in self.pending_hashes:
                            self.pending_hashes.remove(pending_tx.tx_hash)

                        timed_out_count += 1
                        self.stats['total_failed'] += 1

                # Only resync if we had timeouts AND it's been a while since last sync
                if timed_out_count > 0:
                    last_sync_age = now - self.last_sync.get(address, 0)
                    if last_sync_age > self.sync_interval:
                        addresses_to_sync.add(address)

            # Sync addresses that need it (outside the loop to avoid lock issues)
            for address in addresses_to_sync:
                self._force_sync(address)

    def _maybe_sync(self, address: str) -> None:
        """
        Синхронизация с блокчейном если прошло достаточно времени.
        """
        now = time.time()

        need_sync = (
            address not in self.blockchain_nonce or
            address not in self.last_sync or
            (now - self.last_sync[address]) > self.sync_interval
        )

        if need_sync:
            self._force_sync(address)

    def _force_sync(self, address: str) -> None:
        """
        Принудительная синхронизация с блокчейном.

        Phase 1.4.1: Simplified mode (no SSE dependency).
        Auto-marks pending TX as confirmed when blockchain_nonce advances.
        """
        try:
            # Получаем актуальный nonce из блокчейна
            blockchain_nonce = self.get_blockchain_nonce(address)

            # Обновляем blockchain_nonce
            old_blockchain = self.blockchain_nonce.get(address, 0)
            self.blockchain_nonce[address] = blockchain_nonce

            if blockchain_nonce != old_blockchain:
                processed_count = blockchain_nonce - old_blockchain

                # Phase 1.4.1: Auto-mark TX as confirmed (no SSE events)
                confirmed_count = 0
                for ptx in self.pending_txs.get(address, []):
                    if ptx.nonce < blockchain_nonce and not ptx.confirmed and not ptx.failed:
                        ptx.confirmed = True
                        if ptx.tx_hash in self.pending_hashes:
                            self.pending_hashes.remove(ptx.tx_hash)
                        self.stats['total_confirmed'] += 1
                        confirmed_count += 1

                logger.info(f"Periodic sync for {address[:10]}...: "
                           f"blockchain_nonce {old_blockchain} -> {blockchain_nonce} "
                           f"({processed_count} txs processed, {confirmed_count} marked confirmed)")

                # Чистим подтверждённые и failed транзакции
                self._cleanup_confirmed(address)

                # Phase 1.4.1: No need to calculate pending_nonce here.
                # It's calculated dynamically in get_next_nonce() using gap-filling algorithm.

            self.last_sync[address] = time.time()
            self.stats['resyncs'] += 1

            # Phase 1.4.1: pending_nonce no longer stored, calculated dynamically
            logger.debug(f"Synced {address[:10]}...: blockchain_nonce={blockchain_nonce} "
                        f"(was {old_blockchain}), "
                        f"pending_count={len(self.pending_txs.get(address, []))}")

        except Exception as e:
            logger.error(f"Failed to sync nonce for {address[:10]}...: {e}")

    def _cleanup_confirmed(self, address: str) -> None:
        """
        Удаляет подтверждённые и failed транзакции из pending списка.

        Phase 1.4.1: Also remove failed transactions to prevent blocking.
        """
        if address not in self.pending_txs:
            return

        # Удаляем все подтверждённые и failed TX с начала очереди
        while self.pending_txs[address] and (self.pending_txs[address][0].confirmed or
                                              self.pending_txs[address][0].failed):
            self.pending_txs[address].popleft()

        # Если очередь пустая, удаляем ключ
        if not self.pending_txs[address]:
            del self.pending_txs[address]

    def get_pending_count(self, address: str) -> int:
        """Получить количество pending транзакций для адреса."""
        with self.lock:
            return len(self.pending_txs.get(address, []))

    def get_stats(self) -> Dict:
        """Получить статистику."""
        with self.lock:
            current_pending = sum(len(txs) for txs in self.pending_txs.values())
            return {
                **self.stats,
                'current_pending': current_pending,
                'addresses_tracked': len(self.blockchain_nonce)
            }

    def reset_address(self, address: str) -> None:
        """Сбросить состояние для адреса (для debugging)."""
        with self.lock:
            if address in self.pending_txs:
                for tx in self.pending_txs[address]:
                    if tx.tx_hash in self.pending_hashes:
                        self.pending_hashes.remove(tx.tx_hash)
                del self.pending_txs[address]

            if address in self.blockchain_nonce:
                del self.blockchain_nonce[address]

            if address in self.last_sync:
                del self.last_sync[address]

            logger.info(f"Reset nonce state for {address[:10]}...")
