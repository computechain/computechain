#!/bin/bash
# Phase 1.4 - Multiple Validator Launcher
# Запуск множественных валидаторов для stress testing

set -e

# Default values
COUNT=5
INTERVAL=30
START_INDEX=1
STAGGERED=false
CLEAN=false
BASE_RPC_PORT=8000
BASE_P2P_PORT=9000

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0;33m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --count)
            COUNT="$2"
            shift 2
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --start-index)
            START_INDEX="$2"
            shift 2
            ;;
        --staggered)
            STAGGERED=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        --base-port)
            BASE_RPC_PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== ComputeChain Multi-Validator Launcher ===${NC}"
echo "Validators to start: $COUNT"
echo "Start index: $START_INDEX"
echo "Interval: $INTERVAL seconds"
echo "Staggered: $STAGGERED"
echo "Clean start: $CLEAN"
echo ""

# Clean data if requested
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}Cleaning old data...${NC}"
    rm -rf data/.validator_*
    rm -rf logs/validator_*.log
    echo -e "${GREEN}Cleaned!${NC}"
fi

# Create necessary directories
mkdir -p data
mkdir -p logs

# Function to generate random interval (1 min to 6 hours)
random_interval() {
    echo $(( RANDOM % 21600 + 60 ))
}

# Function to initialize and start a validator
start_validator() {
    local INDEX=$1
    local VALIDATOR_NAME="validator_${INDEX}"
    local DATA_DIR="data/.${VALIDATOR_NAME}"
    local LOG_PATH="logs/${VALIDATOR_NAME}.log"
    local RPC_PORT=$((BASE_RPC_PORT + INDEX - 1))
    local P2P_PORT=$((BASE_P2P_PORT + INDEX - 1))

    echo -e "${GREEN}[$(date '+%H:%M:%S')] Starting ${VALIDATOR_NAME} on RPC:${RPC_PORT}, P2P:${P2P_PORT}...${NC}"

    # Check if validator already running
    if pgrep -f "datadir.*${VALIDATOR_NAME}" > /dev/null; then
        echo -e "${YELLOW}Validator ${VALIDATOR_NAME} already running, skipping...${NC}"
        return
    fi

    # Initialize if needed
    if [ ! -d "$DATA_DIR" ]; then
        echo -e "${YELLOW}Initializing ${VALIDATOR_NAME}...${NC}"
        python3 run_node.py --datadir "$DATA_DIR" init >> "$LOG_PATH" 2>&1
    fi

    # Start validator in background
    nohup python3 -u run_node.py \
        --datadir "$DATA_DIR" \
        run \
        --port "$RPC_PORT" \
        --p2p-port "$P2P_PORT" \
        >> "${LOG_PATH}" 2>&1 &

    local PID=$!
    echo -e "${GREEN}Started ${VALIDATOR_NAME} (PID: ${PID}, RPC: ${RPC_PORT}, P2P: ${P2P_PORT})${NC}"
    echo "${PID}" > "logs/${VALIDATOR_NAME}.pid"
}

# Main loop
for i in $(seq $START_INDEX $((START_INDEX + COUNT - 1))); do
    start_validator $i

    # Wait before starting next validator
    if [ $i -lt $((START_INDEX + COUNT - 1)) ]; then
        if [ "$STAGGERED" = true ]; then
            WAIT_TIME=$(random_interval)
            echo -e "${YELLOW}Waiting ${WAIT_TIME} seconds before next validator (staggered mode)...${NC}"
            sleep $WAIT_TIME
        else
            echo -e "${YELLOW}Waiting ${INTERVAL} seconds before next validator...${NC}"
            sleep $INTERVAL
        fi
    fi
done

echo ""
echo -e "${GREEN}=== All validators started! ===${NC}"
echo ""
echo "Running validators:"
ps aux | grep "run_node.py.*datadir" | grep -v grep | head -10

echo ""
echo -e "${GREEN}Useful commands:${NC}"
echo "  Check status:     curl http://localhost:${BASE_RPC_PORT}/status"
echo "  List validators:  curl http://localhost:${BASE_RPC_PORT}/validators"
echo "  View logs:        tail -f logs/validator_1.log"
echo "  Stop all:         pkill -f 'run_node.py.*datadir'"
echo ""
