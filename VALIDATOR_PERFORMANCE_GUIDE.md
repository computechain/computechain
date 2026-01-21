# Validator Performance & Slashing System - User Guide

## 🎯 Overview

ComputeChain includes a comprehensive Validator Performance & Slashing System with advanced features:
- **Phase 0**: Performance tracking, jailing, and slashing
- **Phase 1**: Validator metadata (name, website, description, commission)
- **Phase 2**: Delegation support with commission-based rewards
- **Phase 3**: Graduated slashing and early unjail mechanism

This guide covers all validator features from performance monitoring to delegation management.

## ✨ Key Features

### 1. **Validator Metadata** (Phase 1)
- Set human-readable name for your validator
- Add website URL and description
- Configure commission rate (0-20%, default 10%)
- Visible in dashboard and API

### 2. **Performance Tracking** (Phase 0)
- Tracks blocks proposed vs expected for each validator
- Monitors consecutive missed blocks
- Records last seen activity
- Minimum uptime requirement: 50% (configurable)

### 3. **Performance Scoring**
Formula:
```
performance_score =
  60% × uptime_score +
  20% × stake_ratio +
  20% × (1 - penalty_ratio)
```

### 4. **Graduated Slashing** (Phase 3)
- **1st Jail**: 5% stake slashed (base rate)
- **2nd Jail**: 10% stake slashed (double penalty)
- **3rd+ Jail**: 100% stake slashed (permanent ejection)
- Progressive penalties discourage repeated violations

### 5. **Delegation System** (Phase 2)
- Users can delegate tokens to validators
- Validators earn commission from block rewards
- Commission distributed automatically
- Delegators can undelegate at any time

### 6. **Early Unjail** (Phase 3)
- Pay 1000 CPC fee to exit jail immediately
- Automatically reactivates validator
- Resets missed blocks counter

### 7. **Smart Epoch Transitions**
- Active validators selected by performance_score (not just stake)
- Inactive validators automatically removed
- New validators can join if they have sufficient stake and performance

## 🚀 Quick Start

### 1. Create and Configure Your Validator

```bash
# Create key
python3 -m cli.main keys add myvalidator

# Stake to become validator
python3 -m cli.main tx stake 1000 --from myvalidator

# Update validator metadata
python3 -m cli.main tx update-validator \
  --name "MyAwesomePool" \
  --website "https://mypool.com" \
  --description "High-performance validator" \
  --commission 0.12 \
  --from myvalidator
```

### 2. Start Your Node

```bash
./run_node.py --datadir .node_a init
./run_node.py --datadir .node_a start
```

### 3. Open Dashboard

Open your browser and navigate to:
```
http://localhost:8000/
```

You'll see:
- Current blockchain status (height, epoch)
- Validators leaderboard with performance scores
- Jailed validators (if any)
- Real-time updates every 10 seconds

### 4. Enable Delegation (Optional)

If you want to accept delegations, ensure your commission is set:

```bash
python3 -m cli.main tx update-validator --commission 0.10 --from myvalidator
```

Delegators can now delegate to your validator:
```bash
# Delegator delegates 500 CPC
python3 -m cli.main tx delegate cpcvalcons1your... 500 --from delegator

# Delegator undelegates 200 CPC
python3 -m cli.main tx undelegate cpcvalcons1your... 200 --from delegator
```

### 5. Monitor Validators via API

Query validator performance:
```bash
# Get all validators
curl http://localhost:8000/validators/leaderboard

# Get specific validator
curl http://localhost:8000/validator/{address}/performance

# Get jailed validators
curl http://localhost:8000/validators/jailed
```

## 📊 Dashboard Features

The web dashboard shows:

### Validator Leaderboard
- **Rank**: Position by performance score
- **Name / Address**: Validator name (if set) or abbreviated address
- **Status**: Active / Inactive / Jailed
- **Performance Score**: 0-100% (color-coded)
- **Uptime**: Blocks proposed / expected
- **Power**: Current stake (self + delegated)
- **Delegated**: Total tokens delegated by others
- **Commission**: Validator commission rate %
- **Blocks**: Proposed / Expected
- **Missed Blocks**: Consecutive misses
- **Jail Count**: Times jailed

### Jailed Validators Section
- Shows validators currently in jail
- Blocks remaining until release
- Total penalties applied
- Remaining stake/power

## 🧪 Testing the System

### Scenario 1: Test Metadata Updates

1. Create validator and stake
2. Update metadata with name and commission
3. Check dashboard - name should appear
4. Verify via API: `curl http://localhost:8000/validators/leaderboard`

### Scenario 2: Test Delegation

1. Create delegator account with balance
2. Delegate tokens to validator
3. Check validator's `total_delegated` increased
4. Check validator's `power` = self_stake + delegated
5. Undelegate some tokens
6. Verify tokens returned to delegator

### Scenario 3: Test Missed Blocks Detection

1. Start 2 nodes (Node A and Node B)
2. Stake 4 validators total
3. Stop Node B (2 validators go offline)
4. Wait for epoch transition (100 blocks on devnet)
5. **Expected Result**: Offline validators get marked with missed_blocks

### Scenario 4: Test Jailing

1. Start nodes with multiple validators
2. Stop one node completely
3. Wait until that validator misses 20 blocks
4. **Expected Result**: Validator gets jailed, slashed 5%, removed from active set
5. Check dashboard to see jailed validator

### Scenario 5: Test Graduated Slashing

1. Jail validator first time - 5% penalty
2. Unjail and jail again - 10% penalty (double)
3. Jail third time - 100% penalty (ejection)
4. Verify progressive penalties applied

### Scenario 6: Test Unjail Transaction

1. Get validator jailed
2. Send UNJAIL transaction with 1000 CPC fee
3. **Expected Result**: Validator immediately unjailed and reactivated
4. Verify via dashboard

### Scenario 7: Test Ejection

1. Let a validator get jailed 3 times
2. **Expected Result**: After 3rd jail, validator is permanently ejected, stake fully slashed

## ⚙️ Configuration Parameters

Edit `protocol/config/params.py` to customize:

```python
# In NetworkConfig.__init__:
# Epoch & Slots
epoch_length_blocks=100,            # Blocks per epoch (devnet)
block_time_sec=5,                   # Block time in seconds
max_rounds_per_height=10,           # Max rounds before timeout

# Performance & Slashing
min_uptime_score=0.5,               # Minimum uptime for active set (50%)
max_missed_blocks_sequential=20,    # Missed blocks before jail
jail_duration_blocks=100,           # Jail duration in blocks
slashing_penalty_rate=0.05,         # Base slashing rate (5%)
ejection_threshold_jails=3,         # Jails before permanent ejection

# Delegation
min_delegation=100 * 10**18,        # Minimum delegation amount (100 CPC)
max_commission_rate=0.20,           # Maximum commission rate (20%)

# Unjail
unjail_fee=1000 * 10**18,          # Fee to unjail early (1000 CPC)
```

## 📋 Transaction Types & Gas Costs

| Transaction | Gas Cost | Additional Fee | Description |
|------------|----------|----------------|-------------|
| STAKE | 40,000 | - | Become validator or add stake |
| UNSTAKE | 40,000 | -10% if jailed | Withdraw stake |
| UPDATE_VALIDATOR | 30,000 | - | Update name, website, description, commission |
| DELEGATE | 35,000 | - | Delegate tokens to validator |
| UNDELEGATE | 35,000 | - | Undelegate tokens from validator |
| UNJAIL | 50,000 | +1000 CPC | Request early jail release |

## 📡 API Endpoints

### GET /status
Returns blockchain status including epoch

### GET /validators
Returns all validators with full stats including metadata

### GET /validators/leaderboard
Returns validators sorted by performance_score with rank

Response includes:
- `name`: Validator name (if set)
- `commission_rate`: Commission percentage
- `total_delegated`: Total tokens delegated
- `power`: Total voting power (self + delegated)
- All performance metrics

### GET /validator/{address}
Returns detailed validator info

### GET /validator/{address}/performance
Returns performance-specific stats

### GET /validators/jailed
Returns currently jailed validators with blocks remaining

## 🔍 Monitoring Tips

### Check Validator Health
```bash
# Get performance for specific validator
VALIDATOR_ADDR="cpcvalcons1..."
curl http://localhost:8000/validator/$VALIDATOR_ADDR/performance | python3 -m json.tool
```

### Watch for Warnings in Logs
```bash
# Node logs will show:
⚠️  Validator cpcvalcons1xxx missed block at height 123 (total consecutive: 5)
⚠️  JAILED: Validator cpcvalcons1xxx | Penalty: 150 | Jail #1 until block 223
❌ EJECTED: Validator cpcvalcons1xxx (too many jails: 3)
```

### Epoch Transition Logs
```bash
=== Epoch 5 Transition (Block 50) ===
  Validator cpcvalcons1...: score=0.950 uptime=0.980 proposed=10/10
  Validator cpcvalcons2...: score=0.750 uptime=0.800 proposed=8/10
  ❌ Validator cpcvalcons3... removed from active set (low performance)
New Active Set (2/5):
  - cpcvalcons1... | score=0.950 | power=3000
  - cpcvalcons2... | score=0.750 | power=2000
```

## 🐛 Troubleshooting

### Validator Stuck in Jail?
- Wait for jail duration to expire (100 blocks by default)
- If jailed 3 times, validator is permanently ejected
- Need to create new validator with fresh stake

### Performance Score Too Low?
- Ensure node uptime is high (>90%)
- Don't stop node during active epochs
- Increase stake to improve score component

### Validator Not Appearing in Active Set?
- Check: `power >= min_validator_stake` (default: 1000)
- Check: Not in jail (`jailed_until_height`)
- Check: Performance score competitive with other validators

## 📊 Real-time Monitoring via SSE

ComputeChain provides Server-Sent Events (SSE) for real-time blockchain updates:

```bash
# Connect to event stream
curl -N http://localhost:8000/events/stream

# Monitor events in real-time:
# - tx_confirmed: Transaction included in block
# - tx_failed: Transaction failed or expired (TTL)
# - block_created: New block produced
```

**Integration with monitoring tools:**
- Use SSE to build custom alerting systems
- Track validator performance in real-time
- Monitor transaction confirmation rates
- Detect jail events immediately

**Prometheus metrics:**
```bash
# Check event emission rate
curl http://localhost:8000/metrics | grep computechain_event_confirmations_total

# Check TPS
curl http://localhost:8000/metrics | grep computechain_tps

# Check mempool health
curl http://localhost:8000/metrics | grep mempool
```

## 📈 Performance Benchmarks

**Current Architecture (Phase 1.4):**
- **Sustained TPS**: ~10 TPS
- **Block Time**: 5 seconds
- **Max TX/Block**: 100
- **Consensus**: Tendermint BFT (instant finality)
- **Validation**: Sequential (single-threaded)

**Capacity Estimates:**
- At 10 TPS: ~860K transactions/day
- 1 TX/user/day: supports ~860K users
- 10 TX/user/day: supports ~86K active users

**Future Performance Targets:**
- Phase 1.4.1: 100 TPS (5s blocks, parallel validation)
- Phase 1.4.2: 300 TPS (3s blocks, state caching)
- Phase 1.4.3: 1000+ TPS (Layer 2, sharding)

See `ROADMAP.md` and `TEST_GUIDE.md` for detailed scalability roadmap.

## 📝 Best Practices

1. **High Uptime**: Keep your node running 24/7
2. **Monitor Dashboard**: Check regularly for warnings
3. **Monitor SSE Events**: Set up real-time alerting for jail/slashing events
4. **Sufficient Stake**: Maintain power above minimum
5. **Backup Strategy**: Have failover nodes ready
6. **Track Metrics**: Use Prometheus to monitor node health

## ✅ Implemented Features

- [x] Performance tracking and scoring
- [x] Automated jailing and slashing
- [x] Validator metadata (name, website, description)
- [x] Delegation support (DELEGATE/UNDELEGATE)
- [x] Commission-based reward distribution
- [x] Unjail transaction (early release with 1000 CPC fee)
- [x] Graduated slashing (5% → 10% → 100%)
- [x] Min uptime score filter (configurable)
- [x] Real-time web dashboard

## 🔮 Future Enhancements

- [x] **Real-time event system (SSE)** - Phase 1.4 ✅
- [x] **Transaction TTL auto-cleanup** - Phase 1.4 ✅
- [ ] Individual delegation tracking (proportional rewards)
- [x] **Unbonding period for undelegations** (21 days) ✅
- [ ] Email/Telegram alerts for jail events (SSE integration available)
- [ ] Historical performance charts
- [ ] Validator reputation score
- [ ] Export dashboard data to CSV
- [ ] Validator self-unjail after jail duration expires

## 📚 References

- **Testing Guide**: `TEST_GUIDE.md` - Load testing and performance benchmarks
- **Quick Start**: `QUICK_START.md` - Getting started with validators
- **Roadmap**: `ROADMAP.md` - Performance targets and scalability plans
- **Gas Model**: `GAS_MODEL.md` - Transaction costs and economics
- **Code**: `blockchain/core/chain.py` - Performance tracking implementation
- **API**: `blockchain/rpc/api.py` - RPC endpoints and SSE bridge

---

**Last Updated:** December 25, 2025
**Current Version:** Phase 1.4 (SSE Events, TX TTL, Performance Benchmarks)
