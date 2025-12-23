#!/usr/bin/env bash
#
# Integration test for Transaction Lifecycle Tracking (Phase 1.4)
#
# Tests event-based transaction tracking vs aggressive cleanup
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "═══════════════════════════════════════════════════════════════════"
echo "Transaction Lifecycle Tracking Integration Test (Phase 1.4)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Clean up any existing test processes
echo "Cleaning up existing processes..."
pkill -f "run_node.py.*test_event" || true
pkill -f "tx_generator.py.*test_event" || true
sleep 2

# Clean up test databases
rm -rf /tmp/test_event_chain.db* || true

echo "Starting validator node..."
cd "$PROJECT_DIR"

# Start validator in background
./run_node.py \
    --db /tmp/test_event_chain.db \
    --port 8100 \
    --validator validator_test \
    > /tmp/test_event_validator.log 2>&1 &

VALIDATOR_PID=$!
echo "Validator PID: $VALIDATOR_PID"

# Wait for validator to start
echo "Waiting for validator to start..."
sleep 5

# Check if validator is running
if ! kill -0 $VALIDATOR_PID 2>/dev/null; then
    echo "ERROR: Validator failed to start"
    cat /tmp/test_event_validator.log
    exit 1
fi

echo "Validator started successfully"
echo ""

# Test 1: Event-based mode (--use-events)
echo "═══════════════════════════════════════════════════════════════════"
echo "TEST 1: Event-based transaction tracking (--use-events)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

echo "Running tx_generator with --use-events for 60 seconds..."
timeout 60s python3 scripts/testing/tx_generator.py \
    --node http://localhost:8100 \
    --mode medium \
    --use-events \
    > /tmp/test_event_mode.log 2>&1 || true

echo "Event-based test completed. Checking statistics..."
grep -A 15 "NonceManager Statistics" /tmp/test_event_mode.log | tail -15

EVENT_CONFIRMATIONS=$(grep "Event confirmations:" /tmp/test_event_mode.log | awk '{print $3}' || echo "0")
AGGRESSIVE_CLEANUPS=$(grep "Aggressive cleanups:" /tmp/test_event_mode.log | awk '{print $3}' || echo "0")

echo ""
echo "Event-based mode results:"
echo "  Event confirmations: $EVENT_CONFIRMATIONS"
echo "  Aggressive cleanups: $AGGRESSIVE_CLEANUPS"

if [ "$EVENT_CONFIRMATIONS" -gt 0 ]; then
    echo "  ✅ Event-based tracking is working!"
else
    echo "  ❌ WARNING: No event confirmations recorded"
fi

if [ "$AGGRESSIVE_CLEANUPS" -eq 0 ]; then
    echo "  ✅ No aggressive cleanups (as expected in event mode)"
else
    echo "  ⚠️  Aggressive cleanups detected: $AGGRESSIVE_CLEANUPS"
fi

echo ""
sleep 5

# Test 2: Legacy mode (without --use-events)
echo "═══════════════════════════════════════════════════════════════════"
echo "TEST 2: Aggressive cleanup mode (legacy)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

echo "Running tx_generator WITHOUT --use-events for 60 seconds..."
timeout 60s python3 scripts/testing/tx_generator.py \
    --node http://localhost:8100 \
    --mode medium \
    > /tmp/test_legacy_mode.log 2>&1 || true

echo "Legacy test completed. Checking statistics..."
grep -A 15 "NonceManager Statistics" /tmp/test_legacy_mode.log | tail -15

EVENT_CONFIRMATIONS_LEGACY=$(grep "Event confirmations:" /tmp/test_legacy_mode.log | awk '{print $3}' || echo "0")
AGGRESSIVE_CLEANUPS_LEGACY=$(grep "Aggressive cleanups:" /tmp/test_legacy_mode.log | awk '{print $3}' || echo "0")

echo ""
echo "Legacy mode results:"
echo "  Event confirmations: $EVENT_CONFIRMATIONS_LEGACY"
echo "  Aggressive cleanups: $AGGRESSIVE_CLEANUPS_LEGACY"

if [ "$AGGRESSIVE_CLEANUPS_LEGACY" -gt 0 ]; then
    echo "  ✅ Aggressive cleanups working (as expected in legacy mode)"
else
    echo "  ⚠️  No aggressive cleanups detected"
fi

echo ""

# Cleanup
echo "Cleaning up..."
kill $VALIDATOR_PID || true
sleep 2

echo "═══════════════════════════════════════════════════════════════════"
echo "Integration Test Summary"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Event-based mode:"
echo "  - Event confirmations: $EVENT_CONFIRMATIONS"
echo "  - Aggressive cleanups: $AGGRESSIVE_CLEANUPS"
echo ""
echo "Legacy mode:"
echo "  - Event confirmations: $EVENT_CONFIRMATIONS_LEGACY"
echo "  - Aggressive cleanups: $AGGRESSIVE_CLEANUPS_LEGACY"
echo ""

# Determine overall result
if [ "$EVENT_CONFIRMATIONS" -gt 0 ] && [ "$AGGRESSIVE_CLEANUPS" -eq 0 ]; then
    echo "✅ TEST PASSED: Event-based tracking is working correctly!"
    echo ""
    echo "Full logs:"
    echo "  - Validator: /tmp/test_event_validator.log"
    echo "  - Event mode: /tmp/test_event_mode.log"
    echo "  - Legacy mode: /tmp/test_legacy_mode.log"
    exit 0
else
    echo "❌ TEST FAILED: Event-based tracking not functioning as expected"
    echo ""
    echo "Check logs for details:"
    echo "  - Validator: /tmp/test_event_validator.log"
    echo "  - Event mode: /tmp/test_event_mode.log"
    echo "  - Legacy mode: /tmp/test_legacy_mode.log"
    exit 1
fi
