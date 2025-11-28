# ComputeChain Руководство по реализации MVP
## Практический план разработки для v0.1

**Версия:** 1.2  
**Дата:** 16 ноября 2025  
**Аудитория:** Команда разработки, контрибьюторы

---

## 📋 Содержание

1. [Цели и scope MVP](#цели-и-scope-mvp)
2. [Технологический стек](#технологический-стек)
3. [Структура проекта](#структура-проекта)
4. [Фазы разработки](#фазы-разработки)
5. [Руководство по реализации](#руководство-по-реализации)
6. [Стратегия тестирования](#стратегия-тестирования)
7. [Руководство по развертыванию](#руководство-по-развертыванию)
8. [Мониторинг и операции](#мониторинг-и-операции)

---

## 🎯 Цели и scope MVP

### Что ЕСТЬ в MVP

✅ **Минимальный жизнеспособный блокчейн** с:
- Токен CPC
- Производство блоков (1-3 валидатора, PoA)
- Простые compute-челленджи
- Базовая верификация
- RPC API + CLI кошелек

### Чего НЕТ в MVP

❌ **Не включено в v0.1:**
- Контракты маркетплейса
- DeFi функции
- VM смарт-контрактов
- DAO управление
- Мобильные кошельки
- Продвинутый P2P (libp2p)
- Block explorer UI

### Критерии успеха

```python
MVP_SUCCESS = {
    "functional": [
        "3 валидаторские ноды работают стабильно",
        "Блоки производятся каждые 120 секунд",
        "Переводы токенов работают",
        "Compute-челленджи выполняются",
        "RPC API отвечает"
    ],
    
    "performance": {
        "tps": 50-100,
        "block_time": 120,  # секунд
        "uptime": 95,       # %
    },
    
    "timeline": "2-3 месяца",
    "code_size": "3,000-5,000 строк"
}
```

---

## 🛠 Технологический стек

### Основные компоненты

```yaml
Язык: Python 3.10+
  Причина: Быстрое прототипирование, существующие ByteLeap компоненты
  Примечание: Будет миграция на Rust/Go для production

База данных: PostgreSQL 14+
  Причина: ACID compliance, production-ready
  Альтернатива: SQLite для легких нод

Кеш: Redis 7+
  Причина: Mempool, временное состояние

API: FastAPI 0.104+
  Причина: Современный, async, авто-документация

Криптография: cryptography 41+
  Причина: Индустриальный стандарт, хорошо проаудирован
```

### Инструменты разработки

```yaml
Версионный контроль: Git + GitHub
Менеджер пакетов: Poetry
Тестирование: pytest + pytest-asyncio
Качество кода: black, mypy, pylint
Документация: Sphinx + mkdocs
CI/CD: GitHub Actions
Контейнеризация: Docker + Docker Compose
```

### Зависимости

```toml
# pyproject.toml
[tool.poetry.dependencies]
python = "^3.10"
fastapi = "^0.104.0"
uvicorn = "^0.24.0"
sqlalchemy = "^2.0.0"
psycopg2-binary = "^2.9.9"
redis = "^5.0.0"
cryptography = "^41.0.0"
pydantic = "^2.5.0"
asyncio = "^3.4.3"

[tool.poetry.dev-dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
black = "^23.11.0"
mypy = "^1.7.0"
pylint = "^3.0.0"
```

---

## 📁 Структура проекта

```
computechain/
├── blockchain/
│   ├── core/
│   │   ├── block.py           # Структура блока
│   │   ├── chain.py           # Логика блокчейна
│   │   ├── transaction.py     # Типы транзакций
│   │   └── state.py           # Состояние аккаунтов
│   │
│   ├── consensus/
│   │   ├── poa.py             # PoA консенсус (MVP)
│   │   └── validator.py       # Логика валидатора
│   │
│   ├── compute/
│   │   ├── challenge.py       # Создание челленджей
│   │   ├── verifier.py        # Верификация доказательств
│   │   └── rewards.py         # Расчет наград
│   │
│   ├── crypto/
│   │   ├── keys.py            # Генерация ключей
│   │   ├── signatures.py      # ECDSA подписи
│   │   └── merkle.py          # Merkle деревья
│   │
│   ├── network/
│   │   ├── node.py            # Сетевая нода
│   │   ├── messages.py        # P2P сообщения
│   │   └── sync.py            # Синхронизация блокчейна
│   │
│   └── storage/
│       ├── database.py        # DB модели
│       └── cache.py           # Redis кеш
│
├── api/
│   ├── rpc.py                 # JSON-RPC endpoints
│   ├── rest.py                # REST endpoints
│   └── websocket.py           # WebSocket (блоки)
│
├── cli/
│   ├── wallet.py              # Команды кошелька
│   ├── node.py                # Команды ноды
│   └── utils.py               # Утилиты
│
├── config/
│   ├── genesis.json           # Genesis блок
│   ├── validator.yaml         # Конфигурация валидатора
│   └── node.yaml              # Конфигурация ноды
│
├── tests/
│   ├── unit/                  # Unit тесты
│   ├── integration/           # Integration тесты
│   └── e2e/                   # End-to-end тесты
│
├── scripts/
│   ├── deploy.sh              # Скрипт развертывания
│   ├── reset_testnet.sh       # Сброс для тестирования
│   └── benchmark.py           # Тесты производительности
│
├── docker/
│   ├── Dockerfile.validator
│   ├── Dockerfile.node
│   └── docker-compose.yml
│
├── docs/
│   ├── api.md
│   ├── setup.md
│   └── architecture.md
│
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## 📅 Фазы разработки

### Фаза 0: Настройка (Неделя 1)

```bash
# Задачи:
✓ Настройка репозитория проекта
✓ Среда разработки
✓ CI/CD pipeline
✓ Структура документации

# Результаты:
- GitHub репо со структурой
- Docker dev окружение
- Базовый README
```

### Фаза 1: Core блокчейн (Недели 2-4)

**Неделя 2: Структуры данных**

```python
# Реализовать:
- Структуры заголовка + тела блока
- Типы транзакций (TokenTransfer)
- Состояние аккаунтов
- Утилиты Merkle дерева

# Файлы:
blockchain/core/block.py        # ~300 строк
blockchain/core/transaction.py  # ~200 строк
blockchain/core/state.py        # ~250 строк
blockchain/crypto/merkle.py     # ~150 строк
```

**Неделя 3: Логика блокчейна**

```python
# Реализовать:
- Класс Blockchain (add_block, validate_block)
- Создание genesis блока
- Переходы состояния
- Базовые правила валидации

# Файлы:
blockchain/core/chain.py        # ~400 строк
blockchain/consensus/poa.py     # ~200 строк
```

**Неделя 4: Слой хранения**

```python
# Реализовать:
- PostgreSQL модели (SQLAlchemy)
- Миграции базы данных
- Redis кеш для mempool
- Персистентность состояния

# Файлы:
blockchain/storage/database.py # ~400 строк
blockchain/storage/cache.py    # ~100 строк
```

### Фаза 2: Токены и аккаунты (Неделя 5)

```python
# Реализовать:
- Логика токена CPC
- Управление аккаунтами
- Отслеживание баланса
- Выполнение переводов
- Управление nonce

# Файлы:
blockchain/token/cpc.py         # ~200 строк
blockchain/token/accounts.py    # ~300 строк

# Тесты:
tests/unit/test_token.py        # ~200 строк
tests/unit/test_accounts.py     # ~150 строк
```

### Фаза 3: Крипто и ключи (Неделя 6)

```python
# Реализовать:
- Генерация ECDSA ключей
- Создание/верификация подписей
- Деривация адреса (стиль Ethereum)
- Подписание транзакций

# Файлы:
blockchain/crypto/keys.py       # ~250 строк
blockchain/crypto/signatures.py # ~200 строк

# Тесты:
tests/unit/test_crypto.py       # ~300 строк
```

### Фаза 4: Compute слой (Неделя 7)

```python
# Реализовать:
- Простая генерация челленджей
- Умножение матриц (малый размер)
- Создание коммитмента
- Выборочная верификация доказательств

# Файлы:
blockchain/compute/challenge.py # ~250 строк
blockchain/compute/verifier.py  # ~300 строк
blockchain/compute/rewards.py   # ~200 строк

# Тесты:
tests/unit/test_compute.py      # ~250 строк
```

### Фаза 5: Сетевой слой (Неделя 8)

```python
# Реализовать:
- Простой TCP сервер
- Протокол сообщений
- Распространение блоков
- Ретрансляция транзакций
- Базовая синхронизация

# Файлы:
blockchain/network/node.py      # ~400 строк
blockchain/network/messages.py  # ~200 строк
blockchain/network/sync.py      # ~250 строк
```

### Фаза 6: RPC API (Неделя 9)

```python
# Реализовать:
- JSON-RPC 2.0 endpoints
- REST API (альтернатива)
- WebSocket (уведомления о блоках)
- Документация API

# Файлы:
api/rpc.py                      # ~500 строк
api/rest.py                     # ~300 строк
api/websocket.py                # ~150 строк

# Endpoints:
POST /rpc
  - cpc_getBlockByHeight
  - cpc_getBalance
  - cpc_sendTransaction
  - cpc_getChainHead
  - cpc_getTransactionReceipt
```

### Фаза 7: CLI кошелек (Неделя 10)

```python
# Реализовать:
- Генерация/импорт ключей
- Проверка баланса
- Отправка транзакций
- Просмотр истории транзакций

# Файлы:
cli/wallet.py                   # ~400 строк
cli/node.py                     # ~200 строк

# Команды:
$ cpc-wallet create
$ cpc-wallet import --key <privkey>
$ cpc-wallet balance <address>
$ cpc-wallet send --to <addr> --amount <cpc>
$ cpc-wallet history <address>
```

### Фаза 8: Интеграция и тестирование (Недели 11-12)

```python
# Задачи:
- Integration тесты (много нод)
- End-to-end тесты
- Бенчмарки производительности
- Исправление багов
- Документация

# Тесты:
tests/integration/test_3_nodes.py
tests/e2e/test_full_flow.py
scripts/benchmark.py
```

---

## 💻 Руководство по реализации

### Шаг 1: Структура блока

```python
# blockchain/core/block.py

from dataclasses import dataclass
from typing import List, Dict
import hashlib
import json

@dataclass
class BlockHeader:
    """Заголовок блока"""
    height: int
    prev_hash: str
    timestamp: int
    validator_address: str
    state_root: str
    tx_root: str
    
    def hash(self) -> str:
        """Вычислить хеш блока"""
        data = {
            "height": self.height,
            "prev_hash": self.prev_hash,
            "timestamp": self.timestamp,
            "validator": self.validator_address,
            "state_root": self.state_root,
            "tx_root": self.tx_root
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

@dataclass
class Block:
    """Полный блок"""
    header: BlockHeader
    transactions: List[dict]
    signature: str
    
    def validate(self) -> bool:
        """Валидировать структуру блока"""
        # Проверить заголовок
        if self.header.height < 0:
            return False
        
        # Проверить транзакции
        for tx in self.transactions:
            if not self._validate_tx(tx):
                return False
        
        # Проверить подпись
        if not self._verify_signature():
            return False
        
        return True
    
    def _validate_tx(self, tx: dict) -> bool:
        # Логика валидации транзакции
        pass
    
    def _verify_signature(self) -> bool:
        # Логика верификации подписи
        pass
```

### Шаг 2: Класс Blockchain

```python
# blockchain/core/chain.py

from typing import List, Optional
from .block import Block, BlockHeader
from .state import AccountState

class Blockchain:
    """Основной класс блокчейна"""
    
    def __init__(self, genesis_block: Optional[Block] = None):
        if genesis_block:
            self.chain = [genesis_block]
        else:
            self.chain = [self._create_genesis()]
        
        self.mempool = []
        self.state = AccountState()
    
    def _create_genesis(self) -> Block:
        """Создать genesis блок"""
        header = BlockHeader(
            height=0,
            prev_hash="0" * 64,
            timestamp=1700000000,
            validator_address="genesis",
            state_root="0" * 64,
            tx_root="0" * 64
        )
        
        return Block(
            header=header,
            transactions=[],
            signature="genesis_signature"
        )
    
    def add_block(self, block: Block) -> bool:
        """Добавить блок в цепь"""
        # Валидировать блок
        if not self.validate_block(block):
            return False
        
        # Добавить в цепь
        self.chain.append(block)
        
        # Обновить состояние
        self.state.apply_block(block)
        
        return True
    
    def validate_block(self, block: Block) -> bool:
        """Валидировать блок перед добавлением"""
        # Проверить высоту
        if block.header.height != len(self.chain):
            return False
        
        # Проверить prev_hash
        if block.header.prev_hash != self.chain[-1].header.hash():
            return False
        
        # Проверить timestamp (не слишком далеко в будущем)
        import time
        if block.header.timestamp > time.time() + 60:
            return False
        
        # Валидировать структуру блока
        if not block.validate():
            return False
        
        return True
    
    def get_block(self, height: int) -> Optional[Block]:
        """Получить блок по высоте"""
        if 0 <= height < len(self.chain):
            return self.chain[height]
        return None
    
    def get_latest_block(self) -> Block:
        """Получить последний блок"""
        return self.chain[-1]
```

### Шаг 3: Состояние аккаунтов

```python
# blockchain/core/state.py

from typing import Dict
from decimal import Decimal

class Account:
    """Объект аккаунта"""
    def __init__(self, address: str):
        self.address = address
        self.balance = 0
        self.nonce = 0

class AccountState:
    """Глобальное состояние аккаунтов"""
    
    def __init__(self):
        self.accounts: Dict[str, Account] = {}
    
    def get_balance(self, address: str) -> int:
        """Получить баланс аккаунта"""
        if address not in self.accounts:
            return 0
        return self.accounts[address].balance
    
    def get_nonce(self, address: str) -> int:
        """Получить nonce аккаунта"""
        if address not in self.accounts:
            return 0
        return self.accounts[address].nonce
    
    def transfer(self, from_addr: str, to_addr: str, amount: int) -> bool:
        """Выполнить перевод"""
        # Проверить баланс
        if self.get_balance(from_addr) < amount:
            return False
        
        # Вычесть у отправителя
        if from_addr not in self.accounts:
            self.accounts[from_addr] = Account(from_addr)
        self.accounts[from_addr].balance -= amount
        self.accounts[from_addr].nonce += 1
        
        # Добавить получателю
        if to_addr not in self.accounts:
            self.accounts[to_addr] = Account(to_addr)
        self.accounts[to_addr].balance += amount
        
        return True
    
    def mint(self, address: str, amount: int):
        """Создать новые токены (награда за блок)"""
        if address not in self.accounts:
            self.accounts[address] = Account(address)
        self.accounts[address].balance += amount
    
    def apply_block(self, block):
        """Применить транзакции блока к состоянию"""
        for tx in block.transactions:
            if tx['type'] == 'transfer':
                self.transfer(
                    tx['from'],
                    tx['to'],
                    tx['amount']
                )
```

### Шаг 4: Простой консенсус (PoA)

```python
# blockchain/consensus/poa.py

from typing import List

class ProofOfAuthority:
    """Простой PoA консенсус"""
    
    def __init__(self, validators: List[str]):
        self.validators = validators
        self.current_index = 0
    
    def select_block_producer(self, height: int) -> str:
        """Round-robin выбор валидатора"""
        return self.validators[height % len(self.validators)]
    
    def is_valid_producer(self, block_height: int, validator_addr: str) -> bool:
        """Проверить может ли валидатор произвести блок"""
        expected = self.select_block_producer(block_height)
        return validator_addr == expected
```

---

## 🧪 Стратегия тестирования

### Unit тесты

```python
# tests/unit/test_block.py

import pytest
from blockchain.core.block import Block, BlockHeader

def test_block_hash():
    """Тест вычисления хеша блока"""
    header = BlockHeader(
        height=1,
        prev_hash="0" * 64,
        timestamp=1700000000,
        validator_address="0xabc",
        state_root="0" * 64,
        tx_root="0" * 64
    )
    
    hash1 = header.hash()
    hash2 = header.hash()
    
    assert hash1 == hash2  # Детерминированный
    assert len(hash1) == 64  # SHA256

def test_block_validation():
    """Тест валидации блока"""
    # TODO: Реализовать
    pass
```

### Integration тесты

```python
# tests/integration/test_3_nodes.py

import pytest
import asyncio
from blockchain.network.node import Node

@pytest.mark.asyncio
async def test_block_propagation():
    """Тест распространения блока между 3 нодами"""
    # Запустить 3 ноды
    node1 = Node("127.0.0.1", 8001)
    node2 = Node("127.0.0.1", 8002)
    node3 = Node("127.0.0.1", 8003)
    
    await node1.start()
    await node2.start()
    await node3.start()
    
    # Соединить ноды
    await node2.connect_to_peer("127.0.0.1:8001")
    await node3.connect_to_peer("127.0.0.1:8001")
    
    # Node1 создает блок
    block = node1.blockchain.create_block()
    await node1.broadcast_block(block)
    
    # Подождать распространения
    await asyncio.sleep(1)
    
    # Проверить что все ноды имеют блок
    assert node1.blockchain.get_latest_block() == block
    assert node2.blockchain.get_latest_block() == block
    assert node3.blockchain.get_latest_block() == block
```

---

## 🚀 Руководство по развертыванию

### Настройка Docker

```dockerfile
# docker/Dockerfile.validator

FROM python:3.10-slim

WORKDIR /app

# Установить зависимости
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --no-dev

# Скопировать код
COPY . .

# Открыть порты
EXPOSE 8545 30303

CMD ["poetry", "run", "python", "-m", "blockchain.validator"]
```

```yaml
# docker/docker-compose.yml

version: '3.8'

services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: computechain
      POSTGRES_USER: cpc
      POSTGRES_PASSWORD: cpc_password
    volumes:
      - pgdata:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  validator1:
    build:
      context: ..
      dockerfile: docker/Dockerfile.validator
    depends_on:
      - postgres
      - redis
    environment:
      VALIDATOR_ADDRESS: "0x1111111111111111111111111111111111111111"
      DATABASE_URL: "postgresql://cpc:cpc_password@postgres:5432/computechain"
      REDIS_URL: "redis://redis:6379"
    ports:
      - "8545:8545"
      - "30303:30303"
  
  validator2:
    build:
      context: ..
      dockerfile: docker/Dockerfile.validator
    depends_on:
      - postgres
      - redis
    environment:
      VALIDATOR_ADDRESS: "0x2222222222222222222222222222222222222222"
      DATABASE_URL: "postgresql://cpc:cpc_password@postgres:5432/computechain"
      REDIS_URL: "redis://redis:6379"
      PEER_ADDRESS: "validator1:30303"
    ports:
      - "8546:8545"
      - "30304:30303"

volumes:
  pgdata:
```

### Запуск MVP

```bash
# Сборка
docker compose -f docker/docker-compose.yml build

# Запуск валидаторов
docker compose -f docker/docker-compose.yml up -d

# Проверка логов
docker compose logs -f validator1

# Остановка
docker compose down
```

---

## 📊 Мониторинг и операции

### Метрики для отслеживания

```python
METRICS = {
    "blockchain": [
        "chain_height",
        "blocks_per_minute",
        "tx_per_block",
        "tps (транзакций в секунду)"
    ],
    
    "node": [
        "peer_count",
        "mempool_size",
        "sync_status",
        "network_latency"
    ],
    
    "performance": [
        "block_validation_time",
        "db_write_time",
        "api_response_time",
        "memory_usage"
    ]
}
```

### Endpoint проверки здоровья

```python
# api/health.py

from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """Endpoint проверки здоровья"""
    return {
        "status": "ok",
        "chain_height": blockchain.get_latest_block().header.height,
        "peers": len(node.peers),
        "mempool_size": len(blockchain.mempool)
    }
```

---

## 📝 Чек-лист разработки

### Перед релизом MVP

- [ ] Все unit тесты проходят
- [ ] Integration тесты проходят
- [ ] 3-узловой testnet работает стабильно (24ч+)
- [ ] RPC API задокументирован
- [ ] CLI кошелек функционален
- [ ] Базовый мониторинг на месте
- [ ] Code review завершен
- [ ] Чек-лист безопасности проверен
- [ ] Бенчмарки производительности запущены
- [ ] README обновлен

---

**Версия 1.2** | Руководство по реализации MVP  
**Последнее обновление:** 16 ноября 2025

*Это руководство будет обновляться по мере прогресса разработки.*

