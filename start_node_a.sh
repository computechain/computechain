#!/bin/bash
set -e

# Configuration
DATA_DIR=".node_a"
PORT=8000
P2P_PORT=9000

echo "=========================================="
echo "🚀 Starting Node A (Primary Validator)"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "run_node.py" ]; then
    echo "❌ Error: run_node.py not found. Please run from computechain/ directory"
    exit 1
fi

# Clean old data if requested
if [ "$1" == "--clean" ]; then
    echo "🧹 Cleaning old data..."
    rm -rf $DATA_DIR
fi

# Initialize if needed
if [ ! -d "$DATA_DIR" ]; then
    echo "📦 Initializing Node A..."
    cd .. && python3 computechain/run_node.py --datadir computechain/$DATA_DIR init
    cd computechain
    echo ""
fi

echo "✅ Node A initialized"
echo "   Data dir: $DATA_DIR"
echo "   RPC: http://localhost:$PORT"
echo "   P2P: $P2P_PORT"
echo "   Dashboard: http://localhost:$PORT/"
echo ""

# Get validator address
if [ -f "$DATA_DIR/validator_key.hex" ]; then
    echo "🔑 Validator Key:"
    python3 -c "
from protocol.crypto.keys import public_key_from_private
from protocol.crypto.addresses import address_from_pubkey
with open('$DATA_DIR/validator_key.hex') as f:
    priv = bytes.fromhex(f.read().strip())
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub, prefix='cpcvalcons')
    print(f'   Address: {addr}')
    print(f'   PubKey: {pub.hex()[:32]}...')
"
    echo ""
fi

echo "🚀 Starting Node A..."
echo "   (Press Ctrl+C to stop)"
echo ""
echo "=========================================="
echo ""

# Start node
cd .. && python3 computechain/run_node.py --datadir computechain/$DATA_DIR run --port $PORT --p2p-port $P2P_PORT
