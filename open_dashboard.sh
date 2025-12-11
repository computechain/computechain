#!/bin/bash

# Configuration
NODE_URL="http://localhost:8000"

echo "=========================================="
echo "📊 ComputeChain Dashboard Launcher"
echo "=========================================="
echo ""

# Check if node is running
echo "🔍 Checking if node is running..."
if curl -s $NODE_URL/status > /dev/null 2>&1; then
    echo "✅ Node is running at $NODE_URL"

    # Get current status
    STATUS=$(curl -s $NODE_URL/status)
    echo ""
    echo "📊 Current Status:"
    echo "$STATUS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"   Height: {data['height']}\")
print(f\"   Epoch: {data['epoch']}\")
print(f\"   Network: {data['network']}\")
"
    echo ""
else
    echo "❌ Node is not running at $NODE_URL"
    echo ""
    echo "💡 Start a node first:"
    echo "   Terminal 1: ./start_node_a.sh"
    echo ""
    exit 1
fi

# Dashboard URL
DASHBOARD_URL="$NODE_URL/"

echo "🌐 Opening dashboard in browser..."
echo "   URL: $DASHBOARD_URL"
echo ""

# Try to open in browser (works on most Linux systems)
if command -v xdg-open > /dev/null 2>&1; then
    xdg-open "$DASHBOARD_URL" 2>/dev/null &
    echo "✅ Browser opened!"
elif command -v gnome-open > /dev/null 2>&1; then
    gnome-open "$DASHBOARD_URL" 2>/dev/null &
    echo "✅ Browser opened!"
elif command -v firefox > /dev/null 2>&1; then
    firefox "$DASHBOARD_URL" 2>/dev/null &
    echo "✅ Firefox opened!"
elif command -v google-chrome > /dev/null 2>&1; then
    google-chrome "$DASHBOARD_URL" 2>/dev/null &
    echo "✅ Chrome opened!"
else
    echo "⚠️  Could not auto-open browser"
    echo ""
    echo "📋 Manual instructions:"
    echo "   1. Open your web browser"
    echo "   2. Navigate to: $DASHBOARD_URL"
    echo ""
fi

echo ""
echo "=========================================="
echo "📱 Dashboard Features:"
echo "   • Real-time validator monitoring"
echo "   • Performance leaderboard"
echo "   • Jailed validators tracking"
echo "   • Auto-refresh every 10 seconds"
echo ""
echo "🔗 API Endpoints:"
echo "   • Status:      $NODE_URL/status"
echo "   • Validators:  $NODE_URL/validators/leaderboard"
echo "   • Jailed:      $NODE_URL/validators/jailed"
echo ""
echo "=========================================="
