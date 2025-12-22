#!/bin/bash
# ComputeChain 24-Hour Test Starter
# Initializes validators and starts load test

set -e

# Check arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 <mode> [duration_hours]"
    echo ""
    echo "Modes:"
    echo "  low     - Low intensity (1-5 TPS)"
    echo "  medium  - Medium intensity (10-50 TPS)"
    echo "  high    - High intensity (50-200 TPS)"
    echo ""
    echo "Duration (optional, default 24 hours):"
    echo "  Example: $0 low 48"
    echo ""
    exit 1
fi

MODE=$1
DURATION_HOURS=${2:-24}
DURATION_SECONDS=$((DURATION_HOURS * 3600))

# Validate mode
if [[ ! "$MODE" =~ ^(low|medium|high)$ ]]; then
    echo "Error: Invalid mode '$MODE'"
    echo "Valid modes: low, medium, high"
    exit 1
fi

echo "========================================"
echo "ComputeChain 24-Hour Test"
echo "========================================"
echo "Mode: $MODE"
echo "Duration: $DURATION_HOURS hours ($DURATION_SECONDS seconds)"
echo ""

# Create directories
mkdir -p data logs

# Check if validators are already running
if pgrep -f "run_node.py" > /dev/null; then
    echo "Warning: Validators already running!"
    read -p "Stop and restart? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopping existing validators..."
        pkill -f "run_node.py" 2>/dev/null || true
        sleep 3
    else
        echo "Keeping existing validators. Skipping initialization..."
        SKIP_INIT=1
    fi
fi

if [ -z "$SKIP_INIT" ]; then
    # Initialize validators
    echo "Initializing 5 validators..."
    for i in {1..5}; do
        if [ ! -d "data/.validator_$i" ]; then
            echo "  Initializing validator_$i..."
            ./run_node.py --validator validator_$i init --datadir data/.validator_$i > /dev/null 2>&1
        else
            echo "  validator_$i already initialized"
        fi
    done

    echo ""
    echo "Starting validators..."

    # Start validator 1
    ./run_node.py --datadir data/.validator_1 run --port 8000 --p2p-port 26656 > logs/validator_1.log 2>&1 &
    echo "  validator_1 started (PID: $!) - http://localhost:8000"
    sleep 3

    # Start validator 2
    ./run_node.py --datadir data/.validator_2 run --port 8001 --p2p-port 26657 > logs/validator_2.log 2>&1 &
    echo "  validator_2 started (PID: $!) - http://localhost:8001"
    sleep 3

    # Start validator 3
    ./run_node.py --datadir data/.validator_3 run --port 8002 --p2p-port 26658 > logs/validator_3.log 2>&1 &
    echo "  validator_3 started (PID: $!) - http://localhost:8002"
    sleep 3

    # Start validator 4
    ./run_node.py --datadir data/.validator_4 run --port 8003 --p2p-port 26659 > logs/validator_4.log 2>&1 &
    echo "  validator_4 started (PID: $!) - http://localhost:8003"
    sleep 3

    # Start validator 5
    ./run_node.py --datadir data/.validator_5 run --port 8004 --p2p-port 26660 > logs/validator_5.log 2>&1 &
    echo "  validator_5 started (PID: $!) - http://localhost:8004"
    sleep 5

    # Verify validators are running
    echo ""
    echo "Verifying validators..."
    VALIDATOR_COUNT=$(pgrep -f "run_node.py" | wc -l)
    if [ "$VALIDATOR_COUNT" -ne 5 ]; then
        echo "Error: Expected 5 validators, but only $VALIDATOR_COUNT running!"
        echo "Check logs/validator_*.log for errors"
        exit 1
    fi
    echo "  ✓ All 5 validators running"
fi

# Wait for blockchain to sync
echo ""
echo "Waiting for blockchain to initialize..."
sleep 10

# Check node status
HEIGHT=$(curl -s http://localhost:8000/status 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['height'])" 2>/dev/null || echo "0")
if [ "$HEIGHT" = "0" ]; then
    echo "Warning: Could not connect to node. Waiting 10 more seconds..."
    sleep 10
    HEIGHT=$(curl -s http://localhost:8000/status 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['height'])" 2>/dev/null || echo "0")
fi

echo "  Current blockchain height: $HEIGHT"

# Check if tx_generator is already running
if pgrep -f "tx_generator.py" > /dev/null; then
    echo ""
    echo "Warning: Transaction generator already running!"
    read -p "Stop and restart? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill -f "tx_generator.py" 2>/dev/null || true
        sleep 2
    else
        echo "Keeping existing tx_generator. Exiting..."
        exit 0
    fi
fi

# Start transaction generator
echo ""
echo "Starting transaction generator ($MODE mode)..."
python3 scripts/testing/tx_generator.py \
    --mode "$MODE" \
    --duration "$DURATION_SECONDS" \
    --node http://localhost:8000 \
    > logs/tx_generator_${MODE}_$(date +%Y%m%d_%H%M%S).log 2>&1 &

TX_GEN_PID=$!
echo "  tx_generator started (PID: $TX_GEN_PID)"

# Wait a bit and verify it started
sleep 5
if ! ps -p $TX_GEN_PID > /dev/null; then
    echo ""
    echo "Error: tx_generator failed to start!"
    echo "Check logs/tx_generator_*.log for details"
    exit 1
fi

echo ""
echo "========================================"
echo "Test Started Successfully!"
echo "========================================"
echo ""
echo "Running Processes:"
ps aux | grep -E "(run_node.py|tx_generator.py)" | grep -v grep | awk '{printf "  PID %-7s %s\n", $2, $NF}'
echo ""
echo "Monitoring:"
echo "  Grafana:    http://localhost:3000"
echo "  Prometheus: http://localhost:9090"
echo "  Node API:   http://localhost:8000"
echo ""
echo "Logs:"
echo "  Validators: logs/validator_*.log"
echo "  TxGen:      logs/tx_generator_*.log"
echo ""
echo "Duration: $DURATION_HOURS hours"
echo "Expected completion: $(date -d "+${DURATION_HOURS} hours" '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "To monitor progress:"
echo "  tail -f logs/tx_generator_*.log"
echo "  curl http://localhost:8000/status"
echo ""
echo "To stop test:"
echo "  pkill -f tx_generator.py"
echo "  pkill -f run_node.py"
echo ""
