# ComputeChain

**ComputeChain** is an experimental Layer-1 blockchain built around a new consensus and incentive model called **Proof-of-Compute (PoC)** — focused on executing *useful* GPU computations (targeting RTX 4090/5090 and later).

The chain currently operates in **Stage 4: Proof-of-Compute Framework**, featuring a stable multi-validator PoA consensus, post-quantum-ready signing architecture, and a gas-based economic model.

---

## ✨ Key Features

### 🔐 **Consensus & Security**
* **Multi-Validator PoA (Round-Robin)**
* **Post-Quantum Signature Architecture** (Dilithium/Falcon-ready)
* **Deterministic block production**

### 💸 **Economics**
* **Ethereum-like Gas Model** for anti-spam protection
* **Gas-metered transactions** (Transfer, Stake, Submit Result)

### 🧠 **Proof-of-Compute (PoC)**
* **ComputeTask / ComputeResult** native types
* **Merkle verification** of compute results in block headers

---

## 📖 Documentation

Full documentation, including architecture details, node setup, and API references, is available in the **[ComputeChain Documentation](https://docs.computechain.space)**.

---

## 🛠 Repository Structure

```
.
├── blockchain/      # L1 node (consensus, state, networking)
├── protocol/        # Protocol definitions (types, crypto, config)
├── cli/             # CLI wallet (cpc-cli)
├── miner/           # GPU worker stack
├── validator/       # PoC validator/orchestrator
├── scripts/         # Devnet launchers & E2E tests
└── tests/           # Unit tests
```

---

## 🧪 Development

**Install dependencies:**

```bash
pip install -r requirements.txt
```

**Run unit tests:**

```bash
pytest blockchain/tests
```

**Run End-to-End battle test:**

```bash
python3 scripts/e2e_battle.py
```

---

## 📄 License

**MIT License**
