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
    # ===========================================
    # SHARED GENESIS MULTI-VALIDATOR SETUP
    # ===========================================
    # All validators share the same genesis.json
    # This ensures proper P2P consensus
    # ===========================================

    # Step 1: Clean previous test data
    echo "Cleaning previous test data..."
    rm -rf data/.validator_* data/shared_genesis.json data/keys

    # Step 2: Generate shared genesis with all 5 validators
    echo ""
    echo "Generating shared genesis with 5 validators..."
    python3 scripts/generate_genesis.py \
        --validators 5 \
        --genesis-output data/shared_genesis.json \
        --keys-dir data/keys \
        --stake 10000

    if [ ! -f "data/shared_genesis.json" ]; then
        echo "Error: Failed to generate shared genesis!"
        exit 1
    fi

    # Step 3: Initialize all validators with shared genesis
    echo ""
    echo "Initializing validators with shared genesis..."
    for i in {1..5}; do
        echo "  Initializing validator_$i..."
        ./run_node.py --datadir data/.validator_$i init \
            --genesis data/shared_genesis.json \
            --validator-key data/keys/validator_$i.hex \
            --faucet-key data/keys/faucet.hex \
            > /dev/null 2>&1

        if [ ! -f "data/.validator_$i/genesis.json" ]; then
            echo "Error: Failed to initialize validator_$i!"
            exit 1
        fi
    done

    # Step 4: Import keys to CLI keystore for later use
    echo ""
    echo "Importing keys to CLI keystore..."
    KEYS_DIR="$HOME/.computechain/keys"
    mkdir -p "$KEYS_DIR"

    for i in {1..5}; do
        KEY_NAME="validator_$i"
        PRIV_KEY=$(cat "data/keys/validator_$i.hex")
        ./cpc-cli keys import --private-key "$PRIV_KEY" "$KEY_NAME" > /dev/null 2>&1 || true
    done

    # Import faucet key
    FAUCET_PRIV=$(cat "data/keys/faucet.hex")
    ./cpc-cli keys import --private-key "$FAUCET_PRIV" "faucet" > /dev/null 2>&1 || true
    echo "  Keys imported to $KEYS_DIR"

    # Step 5: Start validators
    echo ""
    echo "Starting validators..."

    # Start validator 1 (bootstrap node - no peers)
    ./run_node.py --datadir data/.validator_1 run \
        --port 8000 --p2p-host 127.0.0.1 --p2p-port 26656 \
        > logs/validator_1.log 2>&1 &
    echo "  validator_1 started (PID: $!) - http://localhost:8000"
    sleep 2

    # Start validators 2-5 with validator_1 as peer
    for i in {2..5}; do
        RPC_PORT=$((8000 + i - 1))
        P2P_PORT=$((26656 + i - 1))
        ./run_node.py --datadir data/.validator_$i run \
            --port $RPC_PORT --p2p-host 127.0.0.1 --p2p-port $P2P_PORT \
            --peers "127.0.0.1:26656" \
            > logs/validator_$i.log 2>&1 &
        echo "  validator_$i started (PID: $!) - http://localhost:$RPC_PORT"
        sleep 1
    done

    sleep 3

    # Verify validators are running
    echo ""
    echo "Verifying validators..."
    VALIDATOR_COUNT=$(pgrep -f "run_node.py" | wc -l)
    if [ "$VALIDATOR_COUNT" -ne 5 ]; then
        echo "Error: Expected 5 validators, but only $VALIDATOR_COUNT running!"
        echo "Check logs/validator_*.log for errors"
        exit 1
    fi
    echo "  All 5 validators running"
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

# ============================================
# Verify validators are in shared genesis
# ============================================
echo ""
echo "Checking validators in genesis..."
VALIDATOR_COUNT=$(curl -s http://localhost:8000/validators 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(len([v for v in data.get('validators', []) if v.get('is_active')]))" 2>/dev/null || echo "0")
echo "  Active validators from genesis: $VALIDATOR_COUNT"

if [ "$VALIDATOR_COUNT" -ne 5 ]; then
    echo ""
    echo "Warning: Expected 5 active validators in genesis, got $VALIDATOR_COUNT"
    echo "Check data/shared_genesis.json for validator configuration"
fi

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

# Start transaction generator (Phase 1.4: Event-based tracking only, aggressive cleanup REMOVED)
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
