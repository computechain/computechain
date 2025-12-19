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
        """
        self.get_blockchain_nonce = get_blockchain_nonce

        # Подтверждённый nonce из блокчейна
        self.blockchain_nonce: Dict[str, int] = {}

        # Следующий доступный nonce (с учётом pending)
        self.pending_nonce: Dict[str, int] = {}

        # Pending транзакции для каждого адреса
        self.pending_txs: Dict[str, deque] = defaultdict(deque)

        # Множество tx_hash для быстрой проверки
        self.pending_hashes: Set[str] = set()

        # Время последней синхронизации с блокчейном
        self.last_sync: Dict[str, float] = {}

        # Блокировка для thread-safety
        self.lock = threading.RLock()

        # Настройки
        self.sync_interval = 30  # Ресинхронизация каждые 30 сек
        self.tx_timeout = 120  # Таймаут для pending TX (2 минуты)

        # Статистика
        self.stats = {
            'total_pending': 0,
            'total_confirmed': 0,
            'total_failed': 0,
            'resyncs': 0
        }

    def get_next_nonce(self, address: str) -> int:
        """
        Получить следующий доступный nonce для адреса.

        Returns:
            Nonce для новой транзакции
        """
        with self.lock:
            # Проверяем нужна ли синхронизация
            self._maybe_sync(address)

            # Возвращаем pending_nonce (учитывает все pending TX)
            nonce = self.pending_nonce.get(address, 0)

            logger.debug(f"get_next_nonce({address[:10]}...): {nonce} "
                        f"(blockchain: {self.blockchain_nonce.get(address, 0)}, "
                        f"pending: {len(self.pending_txs.get(address, []))})")

            return nonce

    def on_tx_sent(self, address: str, tx_hash: str, nonce: int) -> None:
        """
        Вызывается когда транзакция успешно отправлена в mempool.

        Args:
            address: Адрес отправителя
            tx_hash: Hash транзакции
            nonce: Nonce транзакции
        """
        with self.lock:
            # Создаём pending транзакцию
            pending_tx = PendingTransaction(tx_hash, nonce, time.time())

            # Добавляем в очередь pending транзакций
            self.pending_txs[address].append(pending_tx)
            self.pending_hashes.add(tx_hash)

            # Обновляем pending_nonce (следующий доступный nonce)
            self.pending_nonce[address] = nonce + 1

            # Статистика
            self.stats['total_pending'] += 1

            logger.debug(f"on_tx_sent({address[:10]}...): tx={tx_hash[:8]}..., nonce={nonce}, "
                        f"new_pending_nonce={self.pending_nonce[address]}, "
                        f"pending_count={len(self.pending_txs[address])}")

    def on_tx_confirmed(self, address: str, tx_hash: str, nonce: int) -> None:
        """
        Вызывается когда транзакция подтверждена в блоке.

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
        """
        with self.lock:
            now = time.time()

            for address in list(self.pending_txs.keys()):
                for pending_tx in list(self.pending_txs[address]):
                    age = now - pending_tx.timestamp

                    if age > self.tx_timeout and not pending_tx.confirmed:
                        logger.warning(f"Pending TX timeout: {pending_tx.tx_hash[:8]}... "
                                      f"(age={age:.0f}s, nonce={pending_tx.nonce})")

                        # Помечаем как failed и ресинхронизируем
                        pending_tx.failed = True
                        if pending_tx.tx_hash in self.pending_hashes:
                            self.pending_hashes.remove(pending_tx.tx_hash)

                        self._force_sync(address)
                        break  # После ресинхронизации выходим из цикла

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
        """
        try:
            # Получаем актуальный nonce из блокчейна
            blockchain_nonce = self.get_blockchain_nonce(address)

            # Обновляем blockchain_nonce
            old_blockchain = self.blockchain_nonce.get(address, 0)
            self.blockchain_nonce[address] = blockchain_nonce

            # Чистим устаревшие pending транзакции
            # (все с nonce < blockchain_nonce уже подтверждены или отклонены)
            if address in self.pending_txs:
                new_pending = deque()
                for pending_tx in self.pending_txs[address]:
                    if pending_tx.nonce >= blockchain_nonce:
                        new_pending.append(pending_tx)
                    else:
                        # Транзакция с nonce < blockchain_nonce должна быть подтверждена
                        if not pending_tx.confirmed and not pending_tx.failed:
                            pending_tx.confirmed = True
                            self.stats['total_confirmed'] += 1

                        if pending_tx.tx_hash in self.pending_hashes:
                            self.pending_hashes.remove(pending_tx.tx_hash)

                self.pending_txs[address] = new_pending

            # Пересчитываем pending_nonce
            if address in self.pending_txs and len(self.pending_txs[address]) > 0:
                # Есть pending транзакции - следующий nonce после последней pending
                max_pending_nonce = max(tx.nonce for tx in self.pending_txs[address])
                self.pending_nonce[address] = max_pending_nonce + 1
            else:
                # Нет pending транзакций - используем blockchain_nonce
                self.pending_nonce[address] = blockchain_nonce

            self.last_sync[address] = time.time()
            self.stats['resyncs'] += 1

            logger.info(f"Synced {address[:10]}...: blockchain_nonce={blockchain_nonce} "
                       f"(was {old_blockchain}), pending_nonce={self.pending_nonce[address]}, "
                       f"pending_count={len(self.pending_txs.get(address, []))}")

        except Exception as e:
            logger.error(f"Failed to sync nonce for {address[:10]}...: {e}")

    def _cleanup_confirmed(self, address: str) -> None:
        """
        Удаляет подтверждённые транзакции из pending списка.
        """
        if address not in self.pending_txs:
            return

        # Удаляем все подтверждённые TX с начала очереди
        while self.pending_txs[address] and self.pending_txs[address][0].confirmed:
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

            if address in self.pending_nonce:
                del self.pending_nonce[address]

            if address in self.last_sync:
                del self.last_sync[address]

            logger.info(f"Reset nonce state for {address[:10]}...")
