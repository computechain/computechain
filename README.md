# ComputeChain

> ✅ **Live Testnet** | ⚠️ Use at your own risk

**ComputeChain** is a Layer-1 blockchain built around a novel consensus and incentive model called **Proof-of-Compute (PoC)** — designed to execute *useful* GPU computations (targeting RTX 4090/5090 and later).

The network features a production-ready validator system with performance tracking, automated slashing, delegation support, and comprehensive test coverage. Built with post-quantum-ready cryptography and an Ethereum-like gas model.

---

## ✨ Key Features

### 🔐 **Consensus & Security**
* **Multi-Validator PoA (Round-Robin)** with deterministic block production
* **Post-Quantum Signature Architecture** (Dilithium/Falcon-ready)
* **Validator Performance Tracking** with automated jailing and slashing

### 💸 **Economics & Staking**
* **Ethereum-like Gas Model** for anti-spam protection
* **Comprehensive Staking System**: STAKE, UNSTAKE with penalties
* **Delegation Support**: Delegate tokens to validators
* **Commission-based Rewards**: Validators earn commission from delegations (default 10%)
* **Graduated Slashing**: Progressive penalties (5% → 10% → 100% ejection)

### 👥 **Validator System**
* **Metadata Support**: Validators can set name, website, description
* **Performance Monitoring**: Uptime score, missed blocks, jail count
* **Minimum Uptime Requirement**: 75% uptime to remain in active set
* **Early Unjail**: Pay 1000 CPC to exit jail early
* **Dashboard**: Real-time web dashboard with validator leaderboard

### 🧠 **Proof-of-Compute (PoC)**
* **ComputeTask / ComputeResult** native types
* **Merkle verification** of compute results in block headers

---

## 📖 Documentation

* **[QUICK_START.md](./QUICK_START.md)** - Quick start guide for running nodes
* **[VALIDATOR_PERFORMANCE_GUIDE.md](./VALIDATOR_PERFORMANCE_GUIDE.md)** - Comprehensive validator guide
* **[TEST_GUIDE.md](./TEST_GUIDE.md)** - Testing and E2E scenarios
* **[CHANGELOG_SINCE_RESTRUCTURE.md](./CHANGELOG_SINCE_RESTRUCTURE.md)** - Detailed changelog of recent improvements

Full documentation is available at **[ComputeChain Documentation](https://docs.computechain.space)**.

---

## 🛠 Repository Structure

```
.
├── blockchain/      # L1 node (consensus, state, networking, RPC API)
├── protocol/        # Protocol definitions (types, crypto, config)
│   ├── types/      # Transaction types, validator models, blocks
│   ├── crypto/     # ECDSA signatures, PQ-ready architecture
│   └── config/     # Network parameters and gas costs
├── cli/             # CLI wallet (cpc-cli)
│   └── main.py     # Commands: keys, query, tx (stake, delegate, etc.)
├── miner/           # GPU worker stack
├── validator/       # PoC validator/orchestrator
├── scripts/         # Devnet launchers & E2E tests
└── tests/           # Unit tests (11 tests, all passing ✅)
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.11+
python3 --version

# Install dependencies
pip install -r requirements.txt
```

### Run a Node

```bash
# Initialize and start node
./run_node.py --datadir .node_a init
./run_node.py --datadir .node_a start

# Open dashboard
open http://localhost:8000/
```

### CLI Wallet

```bash
# Create a key
python3 -m cli.main keys add mykey

# Check balance
python3 -m cli.main query balance cpc1...

# Stake to become validator
python3 -m cli.main tx stake 1000 --from mykey

# Update validator metadata
python3 -m cli.main tx update-validator --name "MyPool" --commission 0.15 --from mykey

# Delegate to validator
python3 -m cli.main tx delegate cpcvalcons1... 500 --from delegator

# Unjail validator (1000 CPC fee)
python3 -m cli.main tx unjail --from mykey
```

---

## 🧪 Development

### Run Unit Tests

```bash
# All tests (11 passing ✅)
PYTHONPATH=. pytest blockchain/tests/test_core.py -v

# Specific test
PYTHONPATH=. pytest blockchain/tests/test_core.py::test_delegate_undelegate_flow -v
```

### Test Coverage

✅ **Core Functionality**
- Account state management
- Stake/Unstake flow with penalties
- Validator performance tracking

✅ **New Features (Phase 1-3)**
- UPDATE_VALIDATOR metadata
- DELEGATE/UNDELEGATE system
- UNJAIL transaction
- Graduated slashing (5%, 10%, 100%)
- Min uptime score filter (0.75)

---

## 📊 Transaction Types & Gas Costs

| Transaction Type | Gas Cost | Description |
|-----------------|----------|-------------|
| TRANSFER | 21,000 | Standard token transfer |
| STAKE | 40,000 | Become validator or increase stake |
| UNSTAKE | 40,000 | Withdraw stake (10% penalty if jailed) |
| UPDATE_VALIDATOR | 30,000 | Update validator metadata |
| DELEGATE | 35,000 | Delegate tokens to validator |
| UNDELEGATE | 35,000 | Undelegate tokens from validator |
| UNJAIL | 50,000 | Request early jail release (+ 1000 CPC fee) |
| SUBMIT_RESULT | 80,000 | Submit PoC computation result |

---

## 🎯 Network Parameters (Devnet)

* **Block Time**: 10 seconds
* **Epoch Length**: 10 blocks
* **Max Validators**: 5
* **Min Validator Stake**: 1,000 CPC
* **Min Uptime Score**: 75%
* **Jail Duration**: 100 blocks
* **Slashing Rate**: 5% (first offense), 10% (second), 100% (third+)
* **Unjail Fee**: 1,000 CPC
* **Min Delegation**: 100 CPC
* **Max Commission**: 20%

---

## 🤝 Contributing

Contributions are welcome! Please ensure:
* All tests pass (`pytest blockchain/tests`)
* Code follows existing style
* Commit messages are descriptive

---

## 📄 License

**MIT License** - See LICENSE file for details

---

**Built with ❤️ by the ComputeChain Team**
