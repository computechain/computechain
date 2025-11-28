# ComputeChain

**ComputeChain** is an experimental Layer-1 blockchain built around a new consensus and incentive model called **Proof-of-Compute (PoC)** — focused on executing *useful* GPU computations (targeting RTX 4090/5090 and later).

The chain currently operates in **Stage 4: Proof-of-Compute Framework**, featuring a stable multi-validator PoA consensus, post-quantum-ready signing architecture, and a gas-based economic model.

---

## ✨ Key Features

### 🔐 **Consensus & Security**

* **Multi-Validator PoA (Round-Robin)**
* **Post-Quantum Signature Architecture** (Dilithium/Falcon-ready)
* **Deterministic block production**
* **Validator rotation every 10 blocks (epoch)**

### 💸 **Economics & State**

* **Ethereum-like Gas Model** for anti-spam protection
* Account-based state (balance, nonce, stake)
* Gas-metered transactions:
  * Transfer
  * Stake / Unstake
  * Submit Compute Result

### 🧠 **Proof-of-Compute Layer (PoC)**

* Built-in types: `ComputeTask`, `ComputeResult`
* Block header contains `compute_root` (Merkle root of compute results)
* Reserved fields for **ZK-proofs** (future integration)
* Foundation for GPU worker execution & verification

### 🌐 **Networking**

* Lightweight P2P protocol
* Automatic sync mode and fork resolution
* Peer persistence (`peers.json`)

---

## 🚀 Getting Started

Full developer and validator documentation is available in the `/docs` directory:

* **Architecture Overview**
* **Running a Local Node**
* **Staking & Validating**
* **Wallet & Keys (cpc-cli)**
* **GPU Workers & PoC Execution**
* **API / RPC Reference**

To start documentation locally:

```bash
./start_docs.sh
```

Runs on: **[http://localhost:8008](http://localhost:8008)**

---

## 🛠 Repository Structure

```
computechain/
├── blockchain/      # L1 node: consensus, state, networking
│   ├── core/        # Chain, mempool, gas logic
│   ├── consensus/   # PoA engine (PQ-ready)
│   ├── p2p/         # Lightweight P2P protocol
│   └── storage/     # SQLite backend
├── protocol/        # Shared protocol definitions
│   ├── types/       # Blocks, tx, PoC structures
│   ├── crypto/      # PQ signing abstraction
│   └── config/      # Network & gas parameters
├── cli/             # cpc-cli wallet & transaction tool
├── docs/            # Full documentation site
└── scripts/         # Devnet helpers & E2E tests
```

---

## 🧭 Roadmap (High-Level)

### **Completed**

* Multi-Validator PoA Consensus
* Dynamic Validator Set
* Post-Quantum Signature Architecture
* Gas Model & Fee Market
* Proof-of-Compute Framework (Stage 4)

### **In Progress**

* GPU Worker Runtime (PoC Execution Engine)
* Task Orchestrator & Compute Market
* ZK-Proof Integration for compute verification

---

## 🧪 Development

Run unit tests:

```bash
pytest computechain/blockchain/tests
```

End-to-end testing scenario:

```bash
python3 scripts/e2e_battle.py
```

---

## 📄 License

**MIT License**
