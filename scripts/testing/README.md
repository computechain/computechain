# Phase 1.4 Testing Scripts

Load testing and monitoring tools for ComputeChain.

## 🚀 Quick Start

**For 24-hour tests, use the root-level scripts:**

```bash
# From /home/pc205/128/computechain directory:

# Clean everything and start fresh 24h test
./cleanup.sh
./start_test.sh low      # 1-5 TPS
./start_test.sh medium   # 10-50 TPS
./start_test.sh high     # 50-200 TPS
```

See root `cleanup.sh` and `start_test.sh` for details.

---

## 📁 Files in this directory

### `tx_generator.py`
Transaction generator for load testing (used by `start_test.sh`)

**Direct usage:**
```bash
# Low load (1-5 TPS)
python3 scripts/testing/tx_generator.py --mode low --duration 3600

# Medium load (10-50 TPS)
python3 scripts/testing/tx_generator.py --mode medium --duration 7200

# High load (50-200 TPS)
python3 scripts/testing/tx_generator.py --mode high --duration 1800
```

**Features:**
- Automatically creates and funds 100 test accounts
- Tracks pending transactions with NonceManager
- Generates TRANSFER, STAKE, UNSTAKE, UNDELEGATE transactions
- Real-time statistics and logging

### `nonce_manager.py`
Nonce management system with pending transaction tracking

**Used by:** `tx_generator.py`

**Features:**
- Prevents nonce race conditions
- Tracks pending transactions
- Auto-syncs with blockchain state
- Transaction timeout detection

### `monitor.py`
System and blockchain metrics monitoring

**Usage:**
```bash
# Monitor every 60 seconds
python3 scripts/testing/monitor.py --interval 60

# With CSV output
python3 scripts/testing/monitor.py --interval 60 --output logs/metrics.csv

# Custom alert thresholds
python3 scripts/testing/monitor.py --alert-cpu 85 --alert-ram 95
```

---

## 📊 Monitoring

### Check Status

```bash
# Blockchain status
curl http://localhost:8000/status | python3 -m json.tool

# Validators
curl http://localhost:8000/validators | python3 -m json.tool

# Metrics (Prometheus format)
curl http://localhost:8000/metrics

# Grafana Dashboard
http://localhost:3000
```

### Logs

```bash
# TX Generator
tail -f logs/tx_generator_*.log

# Monitor
tail -f logs/monitor.log

# Validator 1
tail -f logs/validator_1.log

# All validators
tail -f logs/validator_*.log
```

### Processes

```bash
# Check running processes
ps aux | grep -E "run_node|tx_generator"

# Stop all
pkill -f 'run_node.py|tx_generator.py'

# Or use cleanup script
./cleanup.sh
```

---

## 🎯 Test Results

After test completion:

**Logs:** `logs/`
- `validator_*.log` - Validator logs
- `tx_generator_*.log` - TX generator logs
- `monitor.log` - Monitoring logs

**Metrics:** Prometheus + Grafana
- Real-time dashboards: http://localhost:3000
- Raw metrics: http://localhost:9090

**Data:** `data/`
- `.validator_*/chain.db` - Blockchain databases
- Snapshots (if enabled)

---

## ⚠️ Troubleshooting

### Validator won't start

```bash
# Check logs
tail -50 logs/validator_1.log

# Check port conflicts
lsof -i :8000

# Kill and restart
pkill -f validator_1
./start_test.sh low
```

### Transactions stuck in mempool

```bash
# Check mempool size
curl -s http://localhost:8000/status | grep mempool

# Restart validators to clear mempool
./cleanup.sh
./start_test.sh low
```

### High CPU/RAM usage

```bash
# Stop TX generator
pkill -f tx_generator.py

# Restart with lower load
python3 scripts/testing/tx_generator.py --mode low --duration 3600
```

### Database locked

```bash
# Stop all processes
pkill -f run_node.py
sleep 5

# Restart
./start_test.sh low
```

---

## 📚 Architecture

### NonceManager (Phase 1.3)
Prevents nonce race conditions by tracking pending transactions:
- Each account has local pending nonce counter
- Syncs with blockchain periodically
- Detects and recovers from timeouts
- Thread-safe operation

### TX Generator Modes
- **LOW**: 1-5 TPS, 80% transfers, 15% stake, 5% unstake
- **MEDIUM**: 10-50 TPS, similar distribution
- **HIGH**: 50-200 TPS, stress testing

### Monitoring Stack
- **Prometheus**: Metrics collection (http://localhost:9090)
- **Grafana**: Visualization (http://localhost:3000)
- **Custom monitor.py**: Additional system metrics

---

## 🔧 Development

Run unit tests:
```bash
# All tests
./run_tests.sh

# Specific test
./run_tests.sh tests/test_core.py

# With coverage
python3 -m pytest tests/ --cov=blockchain --cov=protocol
```

---

For complete testing guide, see project documentation.
