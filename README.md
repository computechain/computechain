# ComputeChain

> ✅ **Live Testnet** | ⚠️ Use at your own risk

**ComputeChain** is a Layer-1 blockchain built around a novel consensus and incentive model called **Proof-of-Compute (PoC)** — designed to execute *useful* GPU computations (targeting RTX 4090/5090 and later).

The network features a production-ready validator system with performance tracking, automated slashing, delegation support, and comprehensive test coverage. Built with post-quantum-ready cryptography and an Ethereum-like gas model.

---

## ✨ Key Features

### 🔐 **Consensus & Security**
* **Tendermint-style PoA Consensus** with instant finality (5s block time)
* **Deterministic Slot-based Block Production** with genesis_time reference
* **Post-Quantum Signature Architecture** (Dilithium-ready)
* **Validator Performance Tracking** with automated jailing and slashing
* **Real-time Event System** (SSE) for transaction tracking and monitoring

### 💸 **Economics & Staking**
* **Ethereum-like Gas Model** for anti-spam protection
* **Comprehensive Staking System**: STAKE, UNSTAKE with penalties
* **Delegation Support**: Delegate tokens to validators with 21-day unbonding period
* **Commission-based Rewards**: Validators earn commission from delegations (max 20%)
* **Graduated Slashing**: Progressive penalties (5% → 10% → 100% ejection)
* **Economic Invariants**: Supply conservation, burn/mint tracking, treasury management

### 👥 **Validator System**
* **Metadata Support**: Validators can set name, website, description
* **Performance Monitoring**: Uptime score, missed blocks, jail count
* **Configurable Uptime Threshold**: min_uptime_score parameter (default 50%)
* **Early Unjail**: Pay 1000 CPC to exit jail early
* **Dashboard**: Real-time web dashboard with validator leaderboard

### 🧠 **Proof-of-Compute (PoC)**
* **ComputeTask / ComputeResult** native types
* **Merkle verification** of compute results in block headers
* **ZK-based verification** for off-chain weight calculation

### 🛠 **Infrastructure & Observability**
* **State Snapshots**: Fast sync from snapshots (<5 min sync time)
* **Prometheus Metrics**: Block metrics, validator stats, economic tracking
* **Upgrade Protocol**: Versioning, state migration framework
* **Transaction TTL**: Auto-cleanup of expired transactions (1 hour)
* **Performance**: 50-60 TPS sustained, roadmap to 100+ TPS

---

## 📖 Documentation

* **[ROADMAP.md](./ROADMAP.md)** - Development roadmap with performance & scalability targets
* **[QUICK_START.md](./QUICK_START.md)** - Quick start guide for running nodes
* **[VALIDATOR_PERFORMANCE_GUIDE.md](./VALIDATOR_PERFORMANCE_GUIDE.md)** - Comprehensive validator guide
* **[TEST_GUIDE.md](./TEST_GUIDE.md)** - Testing and E2E scenarios
* **[GAS_MODEL.md](./GAS_MODEL.md)** - Gas costs and economic parameters
* **[FINALITY_GUARANTEES.md](./FINALITY_GUARANTEES.md)** - Tendermint instant finality

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
├── scripts/         # Devnet launchers, testing tools (tx_generator, SSE client)
└── tests/           # Unit tests (25+ tests, all passing ✅)
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
# All tests (25+ passing ✅)
./run_tests.sh

# Specific test
./run_tests.sh computechain/tests/test_core.py::test_delegate_undelegate_flow -v

# Run specific test file
./run_tests.sh computechain/tests/test_core.py -v
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
- Deterministic slot-based consensus
- Configurable performance thresholds

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

* **Block Time**: 5 seconds
* **Epoch Length**: 100 blocks (~8 minutes)
* **Max Validators**: 5
* **Max Rounds per Height**: 10
* **Min Validator Stake**: 1,000 CPC
* **Min Uptime Score**: 50% (configurable)
* **Max Missed Blocks**: 20 (before jail)
* **Jail Duration**: 100 blocks
* **Slashing Rate**: 5% (first offense), 10% (second), 100% (third+)
* **Unjail Fee**: 1,000 CPC
* **Min Delegation**: 100 CPC
* **Max Commission**: 20%

---

## 🤝 Contributing

Contributions are welcome! Please ensure:
* All tests pass (`./run_tests.sh`)
* Code follows existing style
* Commit messages are descriptive

---

## 📄 License

**MIT License** - See LICENSE file for details

---

**Built with ❤️ by the ComputeChain Team**
