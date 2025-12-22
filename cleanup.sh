#!/bin/bash
# ComputeChain Test Cleanup Script
# Stops all validators, tx_generator, and cleans data

set -e

echo "========================================"
echo "ComputeChain Test Cleanup"
echo "========================================"

# Stop transaction generator
echo "Stopping transaction generator..."
pkill -f "tx_generator.py" 2>/dev/null || echo "  (tx_generator not running)"

# Stop all validators
echo "Stopping validators..."
pkill -f "run_node.py" 2>/dev/null || echo "  (validators not running)"

# Wait for processes to stop
sleep 3

# Verify all stopped
REMAINING=$(ps aux | grep -E "(tx_generator|run_node.py)" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "Warning: Some processes still running. Force killing..."
    pkill -9 -f "tx_generator.py" 2>/dev/null || true
    pkill -9 -f "run_node.py" 2>/dev/null || true
    sleep 2
fi

# Clean data directories
echo "Cleaning data directories..."
if [ -d "data" ]; then
    rm -rf data/*
    echo "  ✓ data/* cleaned"
else
    echo "  (no data directory)"
fi

# Clean log files (optional)
read -p "Clean log files? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "logs" ]; then
        rm -f logs/*.log
        echo "  ✓ logs/*.log cleaned"
    fi
fi

echo ""
echo "========================================"
echo "Cleanup completed!"
echo "========================================"
echo ""
echo "To start a new test, run:"
echo "  ./start_test.sh low     # Low intensity (1-5 TPS)"
echo "  ./start_test.sh medium  # Medium intensity (10-50 TPS)"
echo "  ./start_test.sh high    # High intensity (50-200 TPS)"
echo ""
