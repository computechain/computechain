#!/bin/bash
# 24-hour test with medium load

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "╔════════════════════════════════════════════════════════════╗"
echo "║      ComputeChain 24-Hour Test (Medium Load)              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Clean old data
echo "[1/5] Cleaning old data..."
rm -rf data/.validator_*
mkdir -p logs
echo "✓ Cleaned"

# Start validators
echo "[2/5] Starting validators..."
bash scripts/testing/run_validators.sh --count 5 --interval 30
echo "✓ Validators started"

# Wait for blockchain
echo "[3/5] Waiting for blockchain to start..."
sleep 30
for i in {1..30}; do
    HEIGHT=$(curl -s http://localhost:8000/status 2>/dev/null | grep -o '"height":[0-9]*' | cut -d':' -f2 || echo "0")
    if [ "$HEIGHT" -gt 0 ]; then
        echo "✓ Blockchain started (height: $HEIGHT)"
        break
    fi
    sleep 2
done

# Start TX generator (24 hours = 86400 seconds)
echo "[4/5] Starting TX generator (24 hours)..."
nohup python3 scripts/testing/tx_generator.py \
    --node http://localhost:8000 \
    --mode medium \
    --duration 86400 \
    > logs/tx_generator.log 2>&1 &
TX_PID=$!
echo "✓ TX generator started (PID: $TX_PID)"

# Start monitor
echo "[5/5] Starting monitor..."
METRICS_FILE="logs/metrics_$(date +%Y%m%d_%H%M%S).csv"
nohup python3 scripts/testing/monitor.py \
    --node http://localhost:8000 \
    --interval 60 \
    --duration 86400 \
    --output "$METRICS_FILE" \
    > logs/monitor.log 2>&1 &
MON_PID=$!
echo "✓ Monitor started (PID: $MON_PID)"

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║              24-Hour Test Running                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Running processes:"
echo "  Validators: 5 (ports 8000-8004)"
echo "  TX Generator: PID $TX_PID (medium mode, 24 hours)"
echo "  Monitor: PID $MON_PID"
echo ""
echo "Monitor logs:"
echo "  tail -f logs/tx_generator.log"
echo "  tail -f logs/monitor.log"
echo "  tail -f logs/validator_1.log"
echo ""
echo "Stop all:"
echo "  pkill -f 'run_node.py|tx_generator.py|monitor.py'"
echo ""
echo "Test will complete in 24 hours..."
echo "You can safely detach from screen (Ctrl+A, D)"
