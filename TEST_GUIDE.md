# 🧪 ComputeChain Testing Guide

**Last Updated:** December 25, 2025

## 📋 Overview

ComputeChain has comprehensive testing infrastructure:
- **Unit Tests**: Core functionality testing (25+ tests)
- **Load Testing**: Transaction throughput testing (configurable TPS)
- **Long-Duration Tests**: 24-hour stability tests
- **Event System Testing**: SSE event delivery verification

---

## 🧪 Unit Tests

### Run All Tests

```bash
# Run all unit tests
./run_tests.sh

# Run with verbose output
./run_tests.sh -v

# Run specific test file
./run_tests.sh computechain/tests/test_core.py -v

# Run specific test
./run_tests.sh computechain/tests/test_core.py::test_delegate_undelegate_flow -v
```

### Test Coverage

✅ **Core Blockchain**
- Account state management
- Transaction validation
- Block creation and validation
- State root calculation

✅ **Staking & Delegation**
- STAKE/UNSTAKE transactions
- DELEGATE/UNDELEGATE flow
- Unbonding period (21 days)
- Reward distribution to delegators
- Commission calculations

✅ **Validator System**
- Performance tracking (uptime, missed blocks)
- Graduated slashing (5% → 10% → 100%)
- Jailing and unjailing
- Validator metadata updates
- Min uptime requirement (75%)

✅ **Economic Invariants**
- Supply conservation
- Non-negative balances
- Staking limits enforcement
- Burn/mint tracking

---

## 🔥 Load Testing

### Quick Start

```bash
# Low load test (1-5 TPS) - 24 hours
./start_test.sh low 24

# Medium load test (10-50 TPS) - 24 hours
./start_test.sh medium 24

# High load test (100-500 TPS) - NOT RECOMMENDED
# Current architecture supports ~10 TPS sustained
# High load causes nonce gaps and mempool saturation
```

### Test Modes

| Mode | TPS Range | Use Case | Status |
|------|-----------|----------|--------|
| **low** | 1-5 | Long-duration stability test | ✅ Stable |
| **medium** | 10-50 | Finding performance limits | ⚠️ Testing needed |
| **high** | 100-500 | Stress test | ❌ Not supported yet |

### What start_test.sh Does

1. **Cleanup**: Stops all running validators and tx_generator
2. **Initialize**: Creates 5 validators with separate data directories
3. **Start Validators**: Launches validators on ports 8000-8004
4. **Start Generator**: Launches tx_generator with specified mode and duration
5. **Monitoring**: Outputs status and log locations

### Monitoring Test Progress

```bash
# Check validator logs
tail -f logs/validator_1.log

# Check tx_generator logs
tail -f logs/tx_generator_low_*.log

# View Prometheus metrics
curl http://localhost:8000/metrics

# Check specific metrics
curl http://localhost:8000/metrics | grep computechain_event_confirmations_total
curl http://localhost:8000/metrics | grep computechain_block_height
curl http://localhost:8000/metrics | grep computechain_tps
```

### Test Results Interpretation

**Successful Test Indicators:**
- ✅ `event_confirmations_total` increasing steadily
- ✅ No "Pending TX timeout" warnings
- ✅ `current_pending` stays low (<100)
- ✅ Blocks contain transactions (not empty)
- ✅ No crashes or errors in validator logs

**Problem Indicators:**
- ❌ `event_confirmations_total` stops increasing
- ❌ Many "Pending TX timeout" warnings
- ❌ `current_pending` grows continuously (>1000)
- ❌ Empty blocks being created
- ❌ Validator crashes or errors

---

## 📊 Performance Benchmarks

### Current Architecture (Phase 1 - Dec 2025)

**Measured Performance:**
- **Sustained TPS**: ~10 TPS
- **Block Time**: 10 seconds
- **Max TX/Block**: 100
- **Consensus**: Tendermint BFT (instant finality)
- **Validation**: Sequential (single-threaded)

**Test Results:**
- ✅ Low load (1-5 TPS): Stable for 12+ hours
- ⏳ Medium load (10-50 TPS): Testing in progress
- ❌ High load (100-500 TPS): Nonce gaps, mempool saturation

**User Capacity Estimates:**
- At 10 TPS: ~860K transactions/day
- 1 TX/user/day: supports ~860K users
- 10 TX/user/day: supports ~86K users

### Future Targets

| Phase | Target TPS | Key Improvements |
|-------|-----------|------------------|
| 1.4.1 | 100 TPS | Block time 5s, 500 TX/block, parallel validation |
| 1.4.2 | 300 TPS | Block time 3s, 1000 TX/block, state caching |
| 1.4.3 | 1000+ TPS | Parallelization, Layer 2, sharding |

---

## 🔍 Event System Testing

### SSE Event Verification

The blockchain emits real-time events via Server-Sent Events (SSE):

**Verify SSE endpoint:**
```bash
# Connect to SSE stream (will show events as they occur)
curl -N http://localhost:8000/events/stream

# You should see:
# : ping (keep-alive every 15 seconds)
# data: {"type":"tx_confirmed","tx_hash":"...","block_height":123}
# data: {"type":"block_created","block_height":124,"block_hash":"..."}
```

**Check event metrics:**
```bash
# Total events emitted
curl http://localhost:8000/metrics | grep event_confirmations_total

# Should increase with each confirmed transaction
```

### Transaction Lifecycle

```
1. TX Sent → mempool
   ↓
2. TX Included in Block
   ↓
3. Event: tx_confirmed emitted
   ↓
4. SSE clients receive event
   ↓
5. NonceManager updates state
```

**TTL (Time-To-Live):**
- Transactions expire after 1 hour in mempool
- Expired TX emit `tx_failed` event
- NonceManager receives event and unblocks nonce

---

## 🛠 Manual Testing Scenarios

### Scenario 1: Basic Node Operation

```bash
# 1. Start a single validator
./run_node.py --datadir data/validator_1 init
./run_node.py --datadir data/validator_1 run

# 2. Check it's working
curl http://localhost:8000/chain/info
curl http://localhost:8000/validators

# 3. View dashboard
open http://localhost:8000/
```

### Scenario 2: Multi-Validator Setup

```bash
# Start 5 validators (automated)
./start_test.sh low 1  # 1 hour test

# Check P2P connectivity
curl http://localhost:8000/peers
curl http://localhost:8001/peers

# Verify all validators are active
curl http://localhost:8000/validators | jq '.[] | {address, is_active}'
```

### Scenario 3: Transaction Stress Test

```bash
# Generate transactions manually
python3 scripts/testing/tx_generator.py --mode medium --duration 3600

# Monitor in real-time
watch -n 1 'curl -s http://localhost:8000/metrics | grep tps'
```

---

## 🐛 Troubleshooting

### Issue: No transactions confirmed

**Symptoms:**
- `event_confirmations_total` stays at 0
- Blocks are empty
- `current_pending` grows

**Solutions:**
```bash
# 1. Check EventBus bridge initialized
grep "EventBus → HTTP SSE bridge initialized" logs/validator_1.log

# 2. Check SSE client connected
grep "Connected to SSE stream" logs/tx_generator_*.log

# 3. Verify events are emitted
grep "tx_confirmed callback called" logs/validator_1.log
```

### Issue: Nonce gaps

**Symptoms:**
- Many "Pending TX timeout" warnings
- TPS drops to 0
- Transactions stuck

**Solutions:**
- Use lower TPS mode (low instead of medium)
- Current architecture limit is ~10 TPS
- See ROADMAP.md Phase 1.4 for scalability improvements

### Issue: Validator crashes

**Symptoms:**
- Process exits unexpectedly
- "Connection refused" errors

**Solutions:**
```bash
# Check logs for errors
tail -100 logs/validator_1.log | grep -i error

# Check system resources
htop  # CPU/RAM usage
df -h # Disk space
```

---

## 📚 Related Documentation

- **[ROADMAP.md](./ROADMAP.md)** - Performance targets and scalability roadmap
- **[QUICK_START.md](./QUICK_START.md)** - Basic node setup
- **[VALIDATOR_PERFORMANCE_GUIDE.md](./VALIDATOR_PERFORMANCE_GUIDE.md)** - Validator optimization
- **[GAS_MODEL.md](./GAS_MODEL.md)** - Gas costs and economics

---

## 🔬 Advanced Testing

### Custom Transaction Generator

```python
from scripts.testing.tx_generator import TransactionGenerator

# Create custom generator
generator = TransactionGenerator(
    node_url="http://localhost:8000",
    mode="custom"  # 1-100 TPS random
)

# Run for specific duration
generator.run(duration_seconds=3600)  # 1 hour
```

### Load Test Analysis

After running a 24-hour test:

```bash
# 1. Count total transactions
grep "TX confirmed via SSE" logs/tx_generator_*.log | wc -l

# 2. Calculate average TPS
# total_tx / duration_seconds

# 3. Check for issues
grep "WARNING\|ERROR" logs/*.log | wc -l

# 4. Verify no crashes
ps aux | grep run_node.py
```

---

**Built with ❤️ by the ComputeChain Team**
