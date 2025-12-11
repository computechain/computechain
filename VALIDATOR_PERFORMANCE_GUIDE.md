# Validator Performance & Slashing System - User Guide

## 🎯 Overview

ComputeChain now includes a comprehensive Validator Performance & Slashing System (Phase 0) that automatically monitors validator uptime, jails inactive validators, and ensures only active validators participate in block production.

## ✨ Key Features

### 1. **Performance Tracking**
- Tracks blocks proposed vs expected for each validator
- Monitors consecutive missed blocks
- Records last seen activity

### 2. **Performance Scoring**
Formula:
```
performance_score =
  60% × uptime_score +
  20% × stake_ratio +
  20% × (1 - penalty_ratio)
```

### 3. **Jail & Slashing**
- **Jail Trigger**: Missing 10+ consecutive blocks
- **Penalty**: 5% of stake slashed per jail
- **Jail Duration**: 100 blocks
- **Ejection**: After 3 jails, validator is permanently ejected with full slash

### 4. **Smart Epoch Transitions**
- Active validators selected by performance_score (not just stake)
- Inactive validators automatically removed
- New validators can join if they have sufficient stake and performance

## 🚀 Quick Start

### 1. Start Your Node

```bash
./run_node.py --datadir .node_a init
./run_node.py --datadir .node_a start
```

### 2. Open Dashboard

Open your browser and navigate to:
```
http://localhost:8000/
```

You'll see:
- Current blockchain status (height, epoch)
- Validators leaderboard with performance scores
- Jailed validators (if any)
- Real-time updates every 10 seconds

### 3. Monitor Validators via API

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
- **Address**: Validator consensus address
- **Status**: Active / Inactive / Jailed
- **Performance Score**: 0-100% (color-coded)
- **Uptime**: Blocks proposed / expected
- **Power**: Current stake
- **Missed Blocks**: Consecutive misses
- **Jail Count**: Times jailed

### Jailed Validators Section
- Shows validators currently in jail
- Blocks remaining until release
- Total penalties applied
- Remaining stake/power

## 🧪 Testing the System

### Scenario 1: Test Missed Blocks Detection

1. Start 2 nodes (Node A and Node B)
2. Stake 4 validators total
3. Stop Node B (2 validators go offline)
4. Wait for epoch transition (10 blocks)
5. **Expected Result**: Offline validators get marked with missed_blocks

### Scenario 2: Test Jailing

1. Start nodes with multiple validators
2. Stop one node completely
3. Wait until that validator misses 10 blocks
4. **Expected Result**: Validator gets jailed, slashed 5%, removed from active set
5. Check dashboard to see jailed validator

### Scenario 3: Test Ejection

1. Let a validator get jailed 3 times
2. **Expected Result**: After 3rd jail, validator is permanently ejected, stake fully slashed

## ⚙️ Configuration Parameters

Edit `protocol/config/params.py` to customize:

```python
# In NetworkConfig.__init__:
min_uptime_score=0.75,              # Minimum uptime for active set
max_missed_blocks_sequential=10,    # Missed blocks before jail
jail_duration_blocks=100,           # Jail duration
slashing_penalty_rate=0.05,         # 5% slash per jail
ejection_threshold_jails=3,         # Jails before permanent ejection
```

## 📡 API Endpoints

### GET /status
Returns blockchain status including epoch

### GET /validators
Returns all validators with full stats

### GET /validators/leaderboard
Returns validators sorted by performance_score

### GET /validator/{address}
Returns detailed validator info

### GET /validator/{address}/performance
Returns performance-specific stats

### GET /validators/jailed
Returns currently jailed validators

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

## 📝 Best Practices

1. **High Uptime**: Keep your node running 24/7
2. **Monitor Dashboard**: Check regularly for warnings
3. **Sufficient Stake**: Maintain power above minimum
4. **Backup Strategy**: Have failover nodes ready
5. **Alert on Jails**: Set up monitoring for jail events

## 🔮 Future Enhancements

- [ ] Email/Telegram alerts for jail events
- [ ] Historical performance charts
- [ ] Validator reputation score
- [ ] Delegation support
- [ ] Unjail transaction (early release with fee)
- [ ] Graduated slashing based on severity

## 📚 References

- System Design: `DEV_PLAN.md` (Phase 0 section)
- Code: `blockchain/core/chain.py` (performance methods)
- Dashboard: `dashboard.html`
- API: `blockchain/rpc/api.py`

---

**Generated**: 2025-12-11
**Version**: Phase 0 - Initial Release
