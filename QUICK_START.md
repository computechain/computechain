# ⚡ Quick Start Guide

## 🚀 Start a Single Node (3 minutes)

### Step 1: Initialize and Start Node

```bash
cd ~/128/computechain

# Initialize node
./run_node.py --datadir .node_a init

# Start node
./run_node.py --datadir .node_a start
```

**Expected output:**
```
✅ Node initialized at .node_a
🚀 Starting RPC server on http://localhost:8000
📊 Prometheus metrics: http://localhost:8000/metrics
📡 SSE events: http://localhost:8000/events/stream
```

**Wait for:** Several lines showing "Block X added to chain"

---

### Step 2: Open Dashboard

Option A - Automated:
```bash
./open_dashboard.sh
```

Option B - Manual:
```
Open in browser: http://localhost:8000/
```

**What you'll see:**
- Current Height: increasing
- Active Validators: 1
- Performance Score: 100%
- Real-time updates every 10 seconds

---

### Step 3: Create a Wallet and Stake

```bash
# Create validator key
python3 -m cli.main keys add myvalidator

# Get some tokens (genesis account has balance)
# Or request from faucet in multi-node setup

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

---

## 🧪 Multi-Validator Load Testing

For testing with multiple validators and transaction load:

```bash
# Low load test (1-5 TPS) - stable for long duration
./start_test.sh low 24  # 24 hours

# Medium load test (10-50 TPS) - testing performance limits
./start_test.sh medium 24

# High load test (100-500 TPS) - stress testing
# Current architecture supports 50-60 TPS sustained
```

**What this does:**
1. Initializes 5 validators (ports 8000-8004)
2. Starts all validators
3. Launches tx_generator with specified load mode
4. Generates transactions for the specified duration

**Monitor progress:**
```bash
# Check validator logs
tail -f logs/validator_1.log

# Check tx_generator logs
tail -f logs/tx_generator_low_*.log

# View Prometheus metrics
curl http://localhost:8000/metrics | grep computechain_tps
curl http://localhost:8000/metrics | grep computechain_block_height
```

See `TEST_GUIDE.md` for detailed load testing instructions.

---

## 📊 CLI Commands

### Query Commands

```bash
# Check blockchain status
curl http://localhost:8000/chain/info

# Get validators
curl http://localhost:8000/validators/leaderboard

# Check balance
python3 -m cli.main query balance cpc1...

# Check account info
python3 -m cli.main query account cpc1...
```

### Transaction Commands

```bash
# Transfer tokens
python3 -m cli.main tx transfer cpc1recipient... 100 --from mykey

# Stake (become validator)
python3 -m cli.main tx stake 1000 --from mykey

# Unstake (withdraw stake)
python3 -m cli.main tx unstake 500 --from mykey

# Update validator metadata
python3 -m cli.main tx update-validator \
  --name "MyPool" \
  --commission 0.15 \
  --from mykey

# Delegate to validator
python3 -m cli.main tx delegate cpcvalcons1... 500 --from delegator

# Undelegate from validator
python3 -m cli.main tx undelegate cpcvalcons1... 200 --from delegator

# Unjail (1000 CPC fee)
python3 -m cli.main tx unjail --from mykey
```

---

## 📡 Real-time Events (SSE)

ComputeChain provides Server-Sent Events for real-time blockchain updates:

```bash
# Connect to event stream
curl -N http://localhost:8000/events/stream

# You'll see:
# : ping (keep-alive every 15 seconds)
# data: {"type":"tx_confirmed","tx_hash":"...","block_height":123}
# data: {"type":"block_created","block_height":124,"block_hash":"..."}
```

**Event types:**
- `tx_confirmed` - Transaction included in block
- `tx_failed` - Transaction failed or expired
- `block_created` - New block created

---

## 🧪 Testing Validator Features

### Test Jailing Mechanism

1. **Start multi-validator setup:**
   ```bash
   ./start_test.sh low 1  # 1 hour test
   ```

2. **Stop one validator:**
   ```bash
   # Find validator process
   ps aux | grep "run_node.py.*validator_2"

   # Kill it
   pkill -f "run_node.py.*validator_2"
   ```

3. **Watch the dashboard:**
   - Missed blocks will increase
   - After 20 consecutive misses → JAIL! 🔒
   - Validator removed from active set
   - 5% stake penalty applied

4. **Check jailed validators:**
   ```bash
   curl http://localhost:8000/validators/jailed | python3 -m json.tool
   ```

### Test Delegation

1. **Create delegator account:**
   ```bash
   python3 -m cli.main keys add delegator
   # Fund account with tokens
   ```

2. **Delegate to validator:**
   ```bash
   python3 -m cli.main tx delegate cpcvalcons1... 500 --from delegator
   ```

3. **Verify delegation:**
   ```bash
   curl http://localhost:8000/validators/leaderboard
   # Check validator's "total_delegated" and "power" increased
   ```

4. **Undelegate:**
   ```bash
   python3 -m cli.main tx undelegate cpcvalcons1... 200 --from delegator
   # Note: 21-day unbonding period applies
   ```

---

## 📊 Performance Metrics

**Current Architecture (Phase 1.5):**
- **Sustained TPS**: 50-60 TPS
- **Block Time**: 5 seconds
- **Epoch Length**: 100 blocks (~8 minutes)
- **Max TX/Block**: 500
- **Consensus**: Tendermint-style PoA (instant finality)

**Future Targets:**
- Phase 2: 100 TPS (parallel validation)
- Phase 3: 300 TPS (state caching)
- Phase 4+: 1000+ TPS (Layer 2, sharding)

See `ROADMAP.md` for detailed scalability roadmap.

---

## 🔧 Troubleshooting

### Node won't start?
```bash
# Kill old processes
pkill -f run_node.py

# Clean data directories
rm -rf .node_a .test_node

# Restart
./run_node.py --datadir .node_a init
./run_node.py --datadir .node_a start
```

### Dashboard not loading?
```bash
# Check node is running
curl http://localhost:8000/status

# If working, open manually
firefox http://localhost:8000/
```

### Port already in use?
```bash
# Check what's using port 8000
ss -tlnp | grep 8000

# Kill the process or use different port
./run_node.py --datadir .node_a start --port 8001
```

### Transactions not confirming?
```bash
# Check mempool size
curl http://localhost:8000/metrics | grep mempool_size

# Check event stream working
curl -N http://localhost:8000/events/stream

# Check validator logs for errors
tail -f logs/validator_1.log | grep -i error
```

---

## 📚 Next Steps

- **Load Testing**: See `TEST_GUIDE.md` for comprehensive testing guide
- **Validator Guide**: See `VALIDATOR_PERFORMANCE_GUIDE.md` for validator optimization
- **Gas Model**: See `GAS_MODEL.md` for transaction costs
- **Development Roadmap**: See `ROADMAP.md` for future features

---

## 🎯 Success Checklist

- [ ] Node starts without errors
- [ ] Dashboard accessible at http://localhost:8000/
- [ ] Blocks being created (height increasing)
- [ ] Can create wallet and check balance
- [ ] Can send transactions
- [ ] SSE event stream working
- [ ] Prometheus metrics accessible

**Everything working?** Congratulations! Your ComputeChain node is fully operational! 🎉

---

**Last Updated:** January 21, 2026
**Current Version:** Phase 1.5 (Deterministic Slots, 50-60 TPS)
