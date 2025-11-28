# ComputeChain Техническая Спецификация
## Архитектура и протоколы L1-блокчейна

**Версия:** 1.2  
**Дата:** 16 ноября 2025  
**Аудитория:** Разработчики, технические архитекторы, исследователи протоколов

---

## 📋 Содержание

1. [Обзор архитектуры](#обзор-архитектуры)
2. [Механизм консенсуса](#механизм-консенсуса)
3. [Протокол верификации вычислений](#протокол-верификации-вычислений)
4. [Структура блока](#структура-блока)
5. [Типы транзакций](#типы-транзакций)
6. [Управление состоянием](#управление-состоянием)
7. [Сетевой протокол](#сетевой-протокол)
8. [Криптографические примитивы](#криптографические-примитивы)
9. [Схема базы данных](#схема-базы-данных)
10. [Спецификация RPC API](#спецификация-rpc-api)
11. [Характеристики производительности](#характеристики-производительности)

---

## 🏗️ Обзор архитектуры

### Компоненты системы

```
┌──────────────────────────────────────────────────┐
│              Сеть ComputeChain                   │
└──────────────────┬───────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌───────────────┐    ┌───────────────┐
│  Валидатор    │    │  Валидатор    │
│               │◄──►│               │
└───────┬───────┘    └───────┬───────┘
        │                    │
        │ WebSocket/gRPC     │
        │                    │
        ▼                    ▼
┌───────────────┐    ┌───────────────┐
│  Майнер       │    │  Майнер       │
│  + GPU Worker │    │  + GPU Worker │
└───────────────┘    └───────────────┘
```

### Архитектура слоев

**Слой 1: Консенсус (Валидаторы)**
- Производство блоков
- Валидация транзакций
- Переходы состояния
- Безопасность Proof-of-Stake

**Слой 2: Вычисления (Майнеры)**
- Выполнение GPU-челленджей
- Генерация доказательств
- Мониторинг heartbeat
- Реклама ресурсов

**Слой 3: Хранение**
- Состояние блокчейна (PostgreSQL/SQLite)
- Mempool (Redis)
- Архив блоков
- История compute-доказательств

**Слой 4: Сеть**
- P2P gossip протокол
- Распространение блоков
- Ретрансляция транзакций
- Механизм синхронизации

---

## ⚙️ Механизм консенсуса

### MVP: Proof-of-Authority (PoA)

**Фаза 1 (Testnet):**

```python
class PoAConsensus:
    """Простой федеративный консенсус для MVP"""
    
    def __init__(self, validators: List[str]):
        self.validators = validators  # Фиксированный список
        self.current_leader = 0
    
    def select_block_producer(self, height: int) -> str:
        """Round-robin выбор"""
        return self.validators[height % len(self.validators)]
    
    def validate_block(self, block: Block) -> bool:
        expected_producer = self.select_block_producer(block.height)
        if block.validator_address != expected_producer:
            return False
        
        if not verify_signature(block):
            return False
        
        return True
```

**Свойства:**
- Детерминированное производство блоков
- Время блока 2 минуты
- Без форков (единственный авторитет)
- Быстрый финалити (немедленный)

### Целевой: BFT Proof-of-Stake

**Фаза 3+ (Mainnet):**

```python
class BFTPoS:
    """Византийско-отказоустойчивый Proof-of-Stake"""
    
    def __init__(self):
        self.validator_set = ValidatorSet()
        self.min_stake = 10_000 * 10**18  # 10k CPC
    
    def calculate_voting_power(self, validator: Validator) -> int:
        """Сила голоса пропорциональна стейку"""
        return validator.stake_amount
    
    def consensus_round(self, height: int):
        """Консенсус в стиле CometBFT"""
        # 1. Propose
        proposer = self.select_proposer(height)
        block = proposer.propose_block()
        
        # 2. Prevote
        prevotes = self.collect_prevotes(block)
        if prevotes >= self.two_thirds_majority():
            # 3. Precommit
            precommits = self.collect_precommits(block)
            if precommits >= self.two_thirds_majority():
                # 4. Commit
                self.commit_block(block)
                return block
        
        # Timeout → следующий раунд
        return None
```

**Свойства:**
- Византийская отказоустойчивость (33% толерантность)
- Быстрый финалити (2 блока)
- Slashing за двойное подписание
- Динамический набор валидаторов

---

## 🧮 Протокол верификации вычислений

### Гибридный Challenge-Response

**Типы челленджей:**

1. **Синтетические челленджи** (нет клиентского задания)
2. **Реальные клиентские задания** (платные вычисления)

### Поток протокола

```python
class ComputeChallenge:
    """GPU-челлендж умножения матриц"""
    
    challenge_id: str
    seed: bytes32           # Случайное зерно
    matrix_size: int        # 8192 x 8192
    timeout: int            # 60 секунд
    target_miner: str
    created_at: int
```

**Фаза 1: Создание челленджа**

```python
def create_challenge(miner_address: str) -> ComputeChallenge:
    """Валидатор создает челлендж"""
    return ComputeChallenge(
        challenge_id=uuid4(),
        seed=random_bytes(32),
        matrix_size=8192,
        timeout=60,
        target_miner=miner_address,
        created_at=time.now()
    )
```

**Фаза 2: Вычисление**

```python
# Майнер вычисляет: C = A × B
# Где A, B = derive_from_seed(seed)

def compute_result(challenge: ComputeChallenge) -> Matrix:
    """GPU вычисление"""
    A = generate_matrix(challenge.seed, "A")
    B = generate_matrix(challenge.seed, "B")
    
    # Выполнение CUDA-ядра
    C = gpu_matmul(A, B)
    
    return C
```

**Фаза 3: Коммитмент**

```python
class Commitment:
    """Merkle коммитмент к результату"""
    
    challenge_id: str
    merkle_root: str        # Корень Merkle дерева результата
    timestamp: int
    signature: str          # ECDSA подпись майнера

def create_commitment(result: Matrix) -> Commitment:
    """Создать merkle коммитмент"""
    # Построить Merkle дерево из строк результата
    merkle_tree = MerkleTree()
    for row in result.rows:
        merkle_tree.add_leaf(sha256(row))
    
    root = merkle_tree.get_root()
    
    # Подписать коммитмент
    message = f"{challenge_id}|{root}|{timestamp}"
    signature = ecdsa_sign(private_key, message)
    
    return Commitment(
        challenge_id=challenge_id,
        merkle_root=root,
        timestamp=timestamp,
        signature=signature
    )
```

**Фаза 4: Выборочная верификация**

```python
class ProofRequest:
    """Валидатор запрашивает конкретные доказательства"""
    
    challenge_id: str
    requested_rows: List[int]  # Случайные строки для верификации

def verify_proof(commitment: Commitment, proof: Proof) -> bool:
    """Валидатор верифицирует выборочные доказательства"""
    
    # 1. Проверить подпись
    if not verify_ecdsa_signature(commitment):
        return False
    
    # 2. Локально пересчитать запрошенные строки
    A = generate_matrix(challenge.seed, "A")
    B = generate_matrix(challenge.seed, "B")
    
    for row_idx in proof_request.requested_rows:
        expected_row = compute_single_row(A[row_idx], B)
        provided_row = proof.rows[row_idx]
        
        if expected_row != provided_row:
            return False
        
        # 3. Проверить Merkle proof
        if not verify_merkle_proof(
            provided_row, 
            row_idx, 
            commitment.merkle_root,
            proof.merkle_proofs[row_idx]
        ):
            return False
    
    # Если 90%+ проверок прошли → принять
    return proof.success_rate >= 0.90
```

### Стратегия выборки верификации

```python
VERIFICATION_STRATEGY = {
    "sample_size": 10,           # Проверить 10 случайных строк
    "matrix_size": 8192,         # Всего строк
    "sample_rate": 0.12,         # 0.12% верификация
    "success_threshold": 0.90,   # 90% должны совпасть
    "fraud_probability": 0.001   # < 0.1% ложных срабатываний
}
```

---

## 📦 Структура блока

### Заголовок блока

```python
class BlockHeader:
    """Структура заголовка блока"""
    
    height: int                  # Номер блока
    prev_hash: bytes32           # Хеш предыдущего блока
    timestamp: int               # Unix timestamp
    validator_address: str       # Производитель блока
    
    # Merkle корни
    state_root: bytes32          # Состояние аккаунтов
    tx_root: bytes32             # Все транзакции
    receipts_root: bytes32       # Квитанции выполнения
    
    # Метаданные
    version: int                 # Версия протокола
    nonce: int                   # Для PoW (не используется в PoS)

def hash_header(header: BlockHeader) -> bytes32:
    """Канонический хеш блока"""
    data = (
        header.height.to_bytes(8, 'big') +
        header.prev_hash +
        header.timestamp.to_bytes(8, 'big') +
        bytes.fromhex(header.validator_address) +
        header.state_root +
        header.tx_root
    )
    return sha256(data)
```

### Тело блока

```python
class Block:
    """Полная структура блока"""
    
    header: BlockHeader
    
    # Транзакции
    token_transfers: List[TokenTransfer]
    compute_proofs: List[ComputeProofTx]
    
    # Награды
    block_reward: int                    # Базовая награда
    miner_rewards: Dict[str, int]        # Распределение
    validator_reward: int
    
    # Консенсус
    signature: bytes                     # Подпись валидатора
    votes: List[Vote]                    # BFT голоса (Фаза 3+)

def validate_block(block: Block, state: State) -> bool:
    """Правила валидации блока"""
    
    # 1. Проверки заголовка
    if block.header.height != state.height + 1:
        return False
    
    if block.header.prev_hash != state.last_block_hash:
        return False
    
    # 2. Подпись
    if not verify_block_signature(block):
        return False
    
    # 3. Транзакции
    for tx in block.token_transfers:
        if not validate_transaction(tx, state):
            return False
    
    # 4. Compute доказательства
    for proof_tx in block.compute_proofs:
        if not verify_compute_proof(proof_tx):
            return False
    
    # 5. Награды
    expected_rewards = calculate_rewards(block, state)
    if block.miner_rewards != expected_rewards:
        return False
    
    return True
```

---

## 📝 Типы транзакций

### 1. Перевод токенов

```python
class TokenTransfer:
    """Транзакция перевода CPC токенов"""
    
    from_address: str            # Отправитель (ECDSA адрес)
    to_address: str              # Получатель
    amount: int                  # Wei единицы (10^18 = 1 CPC)
    nonce: int                   # Anti-replay nonce
    gas_price: int               # Цена газа в wei
    gas_limit: int               # Макс. единиц газа
    timestamp: int
    signature: bytes             # ECDSA подпись

def sign_transfer(tx: TokenTransfer, private_key: bytes) -> bytes:
    """Подписать транзакцию"""
    message = (
        tx.from_address +
        tx.to_address +
        str(tx.amount) +
        str(tx.nonce)
    )
    return ecdsa_sign(private_key, sha256(message))

def validate_transfer(tx: TokenTransfer, state: State) -> bool:
    """Валидировать перевод"""
    # 1. Подпись
    if not verify_signature(tx):
        return False
    
    # 2. Nonce
    if tx.nonce != state.get_nonce(tx.from_address):
        return False
    
    # 3. Баланс
    if state.get_balance(tx.from_address) < tx.amount + tx.gas_price * tx.gas_limit:
        return False
    
    return True
```

### 2. Транзакция compute-доказательства

```python
class ComputeProofTx:
    """Доказательство compute-работы"""
    
    miner_address: str
    challenge_id: str
    commitment: Commitment       # Merkle коммитмент
    proof: SelectiveProof        # Выборочные доказательства строк
    timestamp: int
    signature: bytes

class SelectiveProof:
    """Данные выборочной верификации"""
    
    row_indices: List[int]
    row_values: List[bytes]
    merkle_proofs: List[MerkleProof]
```

### 3. Отправка compute-задания (Будущее)

```python
class ComputeJobTx:
    """Клиент отправляет compute-задание"""
    
    client_address: str
    job_type: str               # "matrix_mult", "render", "ai_training"
    parameters: Dict            # Параметры задания
    payment: int                # Сумма CPC
    deadline: int               # Unix timestamp
    signature: bytes
```

---

## 🗄️ Управление состоянием

### Состояние аккаунта

```python
class Account:
    """Объект состояния аккаунта"""
    
    address: str
    balance: int                 # Wei единицы
    nonce: int                   # Счетчик транзакций
    code_hash: bytes32           # Код контракта (Фаза 4+)
    storage_root: bytes32        # Хранилище контракта (Фаза 4+)

class AccountState:
    """Глобальное состояние аккаунтов"""
    
    def __init__(self):
        self.accounts: Dict[str, Account] = {}
        self.state_root: bytes32 = None
    
    def get_balance(self, address: str) -> int:
        account = self.accounts.get(address)
        return account.balance if account else 0
    
    def transfer(self, from_addr: str, to_addr: str, amount: int):
        """Выполнить перевод"""
        if from_addr not in self.accounts:
            raise InsufficientBalance()
        
        if self.accounts[from_addr].balance < amount:
            raise InsufficientBalance()
        
        self.accounts[from_addr].balance -= amount
        
        if to_addr not in self.accounts:
            self.accounts[to_addr] = Account(address=to_addr)
        
        self.accounts[to_addr].balance += amount
        self.accounts[from_addr].nonce += 1
    
    def compute_state_root(self) -> bytes32:
        """Вычислить Merkle корень состояния"""
        # MVP: Простой хеш отсортированных аккаунтов
        sorted_accounts = sorted(self.accounts.items())
        data = b''
        for addr, account in sorted_accounts:
            data += bytes.fromhex(addr)
            data += account.balance.to_bytes(32, 'big')
            data += account.nonce.to_bytes(8, 'big')
        
        return sha256(data)
        
        # Целевой: Merkle Patricia Trie
        # return merkle_patricia_trie(self.accounts)
```

---

## 🌐 Сетевой протокол

### P2P архитектура

**MVP (Фаза 1):**
```
Звездообразная топология с seed node

         Seed Node
        /    |    \
       /     |     \
    Node1  Node2  Node3
```

**Целевой (Фаза 3+):**
```
Gossipsub mesh сеть (libp2p)

Node1 ←→ Node2 ←→ Node3
  ↕        ↕        ↕
Node4 ←→ Node5 ←→ Node6
```

### Типы сообщений

```python
class Message:
    """Базовое P2P сообщение"""
    
    type: str
    payload: bytes
    timestamp: int
    sender_id: str
    signature: bytes

# Типы сообщений
MESSAGE_TYPES = {
    "NEW_BLOCK": "Объявить новый блок",
    "NEW_TX": "Объявить новую транзакцию",
    "GET_BLOCKS": "Запросить диапазон блоков",
    "BLOCKS": "Ответ с блоками",
    "GET_STATE": "Запросить снимок состояния",
    "HEARTBEAT": "Проверка живости пира"
}
```

### Распространение блоков

```python
async def propagate_block(block: Block, peers: List[Peer]):
    """Broadcast нового блока"""
    message = Message(
        type="NEW_BLOCK",
        payload=serialize(block),
        timestamp=time.now(),
        sender_id=self.node_id
    )
    
    for peer in peers:
        await peer.send(message)

async def handle_new_block(message: Message):
    """Обработать полученный блок"""
    block = deserialize(message.payload)
    
    # Валидировать
    if not validate_block(block):
        return
    
    # Добавить в цепь
    if blockchain.add_block(block):
        # Ре-пропагировать пирам (gossip)
        await propagate_block(block, self.peers)
```

---

## 🔐 Криптографические примитивы

### Хеширование

```python
HASH_FUNCTIONS = {
    "sha256": "Основной хеш (блоки, tx, merkle)",
    "keccak256": "Альтернатива (совместимость с Ethereum)",
    "blake3": "Высокоскоростное хеширование (контрольные суммы)"
}
```

### Цифровые подписи

```python
SIGNATURE_SCHEMES = {
    "secp256k1": "Основная (Ethereum-совместимые адреса)",
    "ed25519": "Альтернатива (быстрая верификация)"
}

def generate_keypair() -> (bytes, bytes):
    """Сгенерировать ECDSA keypair"""
    private_key = secrets.token_bytes(32)
    public_key = secp256k1_derive_public(private_key)
    return private_key, public_key

def address_from_public_key(public_key: bytes) -> str:
    """Адрес в стиле Ethereum"""
    hash = keccak256(public_key)
    return "0x" + hash[-20:].hex()
```

### Merkle деревья

```python
class MerkleTree:
    """Бинарное Merkle дерево"""
    
    def __init__(self):
        self.leaves = []
        self.layers = []
    
    def add_leaf(self, data: bytes):
        """Добавить лист"""
        self.leaves.append(sha256(data))
    
    def build(self):
        """Построить дерево"""
        current_layer = self.leaves
        self.layers = [current_layer]
        
        while len(current_layer) > 1:
            next_layer = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i+1] if i+1 < len(current_layer) else left
                parent = sha256(left + right)
                next_layer.append(parent)
            
            self.layers.append(next_layer)
            current_layer = next_layer
    
    def get_root(self) -> bytes32:
        """Получить Merkle корень"""
        return self.layers[-1][0]
    
    def get_proof(self, leaf_index: int) -> List[bytes32]:
        """Сгенерировать Merkle proof"""
        proof = []
        index = leaf_index
        
        for layer in self.layers[:-1]:
            sibling_index = index ^ 1  # XOR для получения соседа
            if sibling_index < len(layer):
                proof.append(layer[sibling_index])
            index //= 2
        
        return proof

def verify_merkle_proof(leaf: bytes32, index: int, root: bytes32, proof: List[bytes32]) -> bool:
    """Проверить Merkle proof"""
    current = leaf
    
    for sibling in proof:
        if index % 2 == 0:
            current = sha256(current + sibling)
        else:
            current = sha256(sibling + current)
        index //= 2
    
    return current == root
```

---

## 💾 Схема базы данных

### Таблицы (PostgreSQL)

```sql
-- Блоки
CREATE TABLE blocks (
    height BIGINT PRIMARY KEY,
    hash BYTEA UNIQUE NOT NULL,
    prev_hash BYTEA NOT NULL,
    timestamp BIGINT NOT NULL,
    validator_address VARCHAR(42) NOT NULL,
    state_root BYTEA NOT NULL,
    tx_root BYTEA NOT NULL,
    receipts_root BYTEA NOT NULL,
    block_reward NUMERIC(78, 0) NOT NULL,
    signature BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Транзакции
CREATE TABLE transactions (
    hash BYTEA PRIMARY KEY,
    block_height BIGINT REFERENCES blocks(height),
    tx_index INT NOT NULL,
    from_address VARCHAR(42) NOT NULL,
    to_address VARCHAR(42),
    amount NUMERIC(78, 0) NOT NULL,
    nonce BIGINT NOT NULL,
    gas_price NUMERIC(78, 0) NOT NULL,
    gas_used INT NOT NULL,
    signature BYTEA NOT NULL,
    status VARCHAR(10) NOT NULL,  -- 'success', 'failed'
    created_at TIMESTAMP DEFAULT NOW()
);

-- Аккаунты
CREATE TABLE accounts (
    address VARCHAR(42) PRIMARY KEY,
    balance NUMERIC(78, 0) NOT NULL DEFAULT 0,
    nonce BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Compute челленджи
CREATE TABLE compute_challenges (
    challenge_id UUID PRIMARY KEY,
    miner_address VARCHAR(42) NOT NULL,
    seed BYTEA NOT NULL,
    matrix_size INT NOT NULL,
    status VARCHAR(20) NOT NULL,  -- 'pending', 'committed', 'verified', 'failed'
    merkle_root BYTEA,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Майнеры
CREATE TABLE miners (
    address VARCHAR(42) PRIMARY KEY,
    gpu_model VARCHAR(50) NOT NULL,
    stake_amount NUMERIC(78, 0) NOT NULL,
    total_challenges INT DEFAULT 0,
    successful_challenges INT DEFAULT 0,
    current_weight NUMERIC(10, 4) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',  -- 'active', 'slashed', 'inactive'
    registered_at TIMESTAMP DEFAULT NOW()
);

-- Валидаторы
CREATE TABLE validators (
    address VARCHAR(42) PRIMARY KEY,
    stake_amount NUMERIC(78, 0) NOT NULL,
    blocks_produced INT DEFAULT 0,
    slashed_amount NUMERIC(78, 0) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    registered_at TIMESTAMP DEFAULT NOW()
);
```

---

## 🔌 Спецификация RPC API

### JSON-RPC 2.0 Endpoints

```python
# Получить блок по высоте
POST /rpc
{
    "jsonrpc": "2.0",
    "method": "cpc_getBlockByHeight",
    "params": [12345, true],  # height, full_transactions
    "id": 1
}

# Ответ
{
    "jsonrpc": "2.0",
    "result": {
        "height": 12345,
        "hash": "0x...",
        "timestamp": 1700000000,
        "transactions": [...]
    },
    "id": 1
}

# Получить баланс
POST /rpc
{
    "jsonrpc": "2.0",
    "method": "cpc_getBalance",
    "params": ["0x123..."],  # address
    "id": 2
}

# Отправить транзакцию
POST /rpc
{
    "jsonrpc": "2.0",
    "method": "cpc_sendTransaction",
    "params": [{
        "from": "0x123...",
        "to": "0x456...",
        "amount": "1000000000000000000",  # 1 CPC
        "nonce": 5,
        "gasPrice": "1000000000",
        "gasLimit": 21000,
        "signature": "0x..."
    }],
    "id": 3
}
```

### REST API (Альтернатива)

```
GET  /api/v1/blocks/:height
GET  /api/v1/blocks/latest
GET  /api/v1/transactions/:hash
GET  /api/v1/accounts/:address/balance
POST /api/v1/transactions
GET  /api/v1/miners
GET  /api/v1/validators
GET  /api/v1/challenges/:miner_address
```

---

## ⚡ Характеристики производительности

### Целевые метрики

```python
PERFORMANCE_TARGETS = {
    "MVP (Python)": {
        "tps": 50-100,
        "block_time": 120,  # секунды
        "finality_time": 120,  # немедленный (PoA)
        "tx_latency": 2-5,  # секунды
    },
    
    "Целевой (Cosmos/Substrate)": {
        "tps": 1000-5000,
        "block_time": 120,
        "finality_time": 240,  # 2 блока (BFT)
        "tx_latency": 2-5,
    }
}
```

### Стратегия масштабирования

```python
SCALING_ROADMAP = {
    "Фаза 1": "Одна цепь, 50-100 TPS",
    "Фаза 2": "Оптимизированная одна цепь, 1000 TPS",
    "Фаза 3": "Подготовка к шардингу",
    "Фаза 4": "Множественные шарды, 10,000+ TPS"
}
```

---

## 🧪 Стратегия тестирования

### Unit-тесты
- Логика валидации блоков
- Подписание/верификация транзакций
- Переходы состояния
- Операции Merkle дерева
- Криптографические функции

### Integration-тесты
- Многоузловая синхронизация
- Распространение блоков
- Разрешение форков
- Консистентность состояния

### Performance-тесты
- Пропускная способность транзакций
- Задержка распространения блоков
- Производительность запросов к БД
- Профилирование использования памяти

### Security-тесты
- Верификация подписей
- Попытки double-spend
- Симуляция Sybil-атак
- Восстановление после разделения сети

---

## 📚 Справочные материалы

- **Bitcoin Whitepaper**: Satoshi Nakamoto (2008)
- **Ethereum Yellow Paper**: Gavin Wood (2014)
- **CometBFT Documentation**: [https://docs.cometbft.com](https://docs.cometbft.com)
- **Cosmos SDK**: [https://docs.cosmos.network](https://docs.cosmos.network)
- **Substrate**: [https://docs.substrate.io](https://docs.substrate.io)

---

**Версия 1.2** | Техническая спецификация  
**Последнее обновление:** 16 ноября 2025

*Это живой документ, который будет обновляться по мере эволюции протокола.*

