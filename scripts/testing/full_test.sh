#!/bin/bash
# Phase 1.4 - Full Test Suite
# Автоматический запуск полного тестового стека

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
MODE="quick"  # quick, full
CLEAN=false
VALIDATORS=5
NODE_URL="http://localhost:8000"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        --validators)
            VALIDATORS="$2"
            shift 2
            ;;
        --node)
            NODE_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║        ComputeChain Phase 1.4 - Full Test Suite           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo "Mode: $MODE"
echo "Validators: $VALIDATORS"
echo "Clean start: $CLEAN"
echo ""

# Create directories
mkdir -p logs
mkdir -p reports
mkdir -p data

# Step 1: Clean if requested
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}[1/6] Cleaning old data...${NC}"
    rm -rf data/*.db
    rm -rf logs/*.log
    rm -rf snapshots/*
    echo -e "${GREEN}✓ Cleaned${NC}"
else
    echo -e "${YELLOW}[1/6] Skipping clean (use --clean to enable)${NC}"
fi

# Step 2: Start validators
echo -e "${YELLOW}[2/6] Starting validators...${NC}"

if [ "$MODE" = "quick" ]; then
    # Quick mode: all validators at once with 30s interval
    ./scripts/testing/run_validators.sh --count $VALIDATORS --interval 30
elif [ "$MODE" = "full" ]; then
    # Full mode: staggered start over time
    ./scripts/testing/run_validators.sh --count $VALIDATORS --staggered
fi

echo -e "${GREEN}✓ Validators started${NC}"
sleep 10

# Step 3: Wait for first block
echo -e "${YELLOW}[3/6] Waiting for blockchain to start...${NC}"

MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s "$NODE_URL/status" > /dev/null 2>&1; then
        HEIGHT=$(curl -s "$NODE_URL/status" | python3 -c "import sys, json; print(json.load(sys.stdin).get('height', 0))")
        if [ "$HEIGHT" -gt 0 ]; then
            echo -e "${GREEN}✓ Blockchain started (height: $HEIGHT)${NC}"
            break
        fi
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    echo -n "."
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}✗ Blockchain failed to start${NC}"
    exit 1
fi

# Step 4: Start TX generator
echo -e "${YELLOW}[4/6] Starting transaction generator...${NC}"

if [ "$MODE" = "quick" ]; then
    # Quick mode: medium load for 1 hour
    DURATION=3600
    TX_MODE="medium"
elif [ "$MODE" = "full" ]; then
    # Full mode: low load for 7 days
    DURATION=604800
    TX_MODE="low"
fi

nohup python3 scripts/testing/tx_generator.py \
    --node "$NODE_URL" \
    --mode "$TX_MODE" \
    --duration "$DURATION" \
    > logs/tx_generator.log 2>&1 &

TX_GEN_PID=$!
echo "$TX_GEN_PID" > logs/tx_generator.pid
echo -e "${GREEN}✓ TX generator started (PID: $TX_GEN_PID, mode: $TX_MODE, duration: ${DURATION}s)${NC}"

# Step 5: Start monitor
echo -e "${YELLOW}[5/6] Starting system monitor...${NC}"

nohup python3 scripts/testing/monitor.py \
    --node "$NODE_URL" \
    --interval 60 \
    --duration "$DURATION" \
    --output "logs/metrics_$(date +%Y%m%d_%H%M%S).csv" \
    --alert-cpu 80 \
    --alert-ram 90 \
    > logs/monitor.log 2>&1 &

MONITOR_PID=$!
echo "$MONITOR_PID" > logs/monitor.pid
echo -e "${GREEN}✓ Monitor started (PID: $MONITOR_PID)${NC}"

# Step 6: Summary
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                  Test Suite Running                        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Running processes:${NC}"
echo "  Validators: $VALIDATORS"
echo "  TX Generator: PID $TX_GEN_PID (mode: $TX_MODE, duration: ${DURATION}s)"
echo "  Monitor: PID $MONITOR_PID"
echo ""
echo -e "${GREEN}Useful commands:${NC}"
echo "  Check status:      curl $NODE_URL/status | jq"
echo "  List validators:   curl $NODE_URL/validators | jq"
echo "  View TX gen logs:  tail -f logs/tx_generator.log"
echo "  View monitor logs: tail -f logs/monitor.log"
echo "  View validator:    tail -f logs/validator_1.log"
echo "  Check metrics:     curl $NODE_URL/metrics"
echo ""
echo -e "${GREEN}Stop all:${NC}"
echo "  pkill -f 'run_node.py|tx_generator.py|monitor.py'"
echo ""

if [ "$MODE" = "quick" ]; then
    echo -e "${YELLOW}Quick test will run for ~1 hour${NC}"
    echo "Monitor output in logs/monitor.log"
elif [ "$MODE" = "full" ]; then
    echo -e "${YELLOW}Full test will run for 7 days${NC}"
    echo "Check progress with: tail -f logs/monitor.log"
fi

echo ""
echo -e "${GREEN}✓ Test suite successfully started!${NC}"
echo ""

# Optional: wait for test completion (quick mode only)
if [ "$MODE" = "quick" ]; then
    echo "Waiting for test to complete..."
    wait $TX_GEN_PID $MONITOR_PID

    echo ""
    echo -e "${GREEN}✓ Test completed!${NC}"
    echo ""
    echo "Generating report..."
    # TODO: Add report generation script

    echo "Results saved in:"
    echo "  Logs: logs/"
    echo "  Metrics: logs/metrics_*.csv"
fi
