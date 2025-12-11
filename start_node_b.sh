#!/bin/bash
set -e

# Configuration
DATA_DIR_A=".node_a"
DATA_DIR_B=".node_b"
PORT=8001
P2P_PORT=9001
NODE_A_RPC="http://localhost:8000"
NODE_A_P2P="127.0.0.1:9000"

echo "=========================================="
echo "🚀 Starting Node B (Secondary Validator)"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "run_node.py" ]; then
    echo "❌ Error: run_node.py not found. Please run from computechain/ directory"
    exit 1
fi

# Check if Node A is running
echo "🔍 Checking if Node A is running..."
if ! curl -s $NODE_A_RPC/status > /dev/null 2>&1; then
    echo "❌ Error: Node A is not running at $NODE_A_RPC"
    echo "   Please start Node A first: ./start_node_a.sh"
    exit 1
fi

echo "✅ Node A is running"
echo ""

# Clean old data if requested
if [ "$1" == "--clean" ]; then
    echo "🧹 Cleaning old data..."
    rm -rf $DATA_DIR_B
fi

# Check if we need to initialize
if [ ! -d "$DATA_DIR_B" ]; then
    echo "📦 Setting up Node B..."
    mkdir -p $DATA_DIR_B

    # Copy genesis from Node A
    if [ -f "$DATA_DIR_A/genesis.json" ]; then
        echo "   Copying genesis from Node A..."
        cp $DATA_DIR_A/genesis.json $DATA_DIR_B/genesis.json
    else
        echo "❌ Error: Node A genesis not found. Initialize Node A first!"
        exit 1
    fi

    # Ask if we should create new validator or use existing
    echo ""
    read -p "📝 Create NEW validator for Node B? (y/n): " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "🔐 Creating new validator for Node B..."

        # Import faucet key to CLI
        if [ ! -f "$DATA_DIR_A/faucet_key.hex" ]; then
            echo "❌ Error: Faucet key not found in Node A"
            exit 1
        fi

        # Remove old CLI keys
        rm -rf ~/.computechain/keys 2>/dev/null || true

        echo "   Importing faucet key..."
        cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.cli.keystore import KeyStore
ks = KeyStore()
with open('computechain/$DATA_DIR_A/faucet_key.hex') as f:
    priv_hex = f.read().strip()
ks.import_key('faucet', priv_hex)
print('   ✓ Faucet key imported')
" && cd computechain

        # Create Alice key
        echo "   Creating alice key..."
        cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.cli.keystore import KeyStore
ks = KeyStore()
try:
    ks.create_key('alice')
    print('   ✓ Alice key created')
except ValueError:
    print('   ✓ Alice key already exists')
" && cd computechain

        # Get Alice address
        ALICE_ADDR=$(cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.cli.keystore import KeyStore
ks = KeyStore()
key = ks.get_key('alice')
print(key['address'])
" && cd computechain)

        echo "   Alice address: $ALICE_ADDR"
        echo ""
        echo "💸 Funding Alice from faucet..."

        # Fund Alice
        cd .. && python3 -c "
import sys, requests, time
sys.path.append('.')
from computechain.cli.keystore import KeyStore
from computechain.protocol.types.tx import Transaction
from computechain.protocol.types.common import TxType
from computechain.protocol.crypto.keys import public_key_from_private

ks = KeyStore()
faucet = ks.get_key('faucet')
alice_addr = '$ALICE_ADDR'

# Get faucet nonce
resp = requests.get('$NODE_A_RPC/balance/' + faucet['address'])
nonce = resp.json()['nonce']

# Create transfer tx
tx = Transaction(
    tx_type=TxType.TRANSFER,
    from_address=faucet['address'],
    to_address=alice_addr,
    amount=3000 * 10**18,  # 3000 CPC
    fee=21000 * 1000,      # gas * gas_price
    nonce=nonce,
    pub_key=faucet['public_key'],
    gas_limit=21000,
    gas_price=1000
)

# Sign
priv_bytes = bytes.fromhex(faucet['private_key'])
tx.sign(priv_bytes)

# Send
resp = requests.post('$NODE_A_RPC/tx/send', json=tx.model_dump())
print(f\"   ✓ Transfer sent: {resp.json()}\")
" && cd computechain

        echo ""
        echo "⏳ Waiting for transaction to be mined (10 seconds)..."
        sleep 12

        echo ""
        echo "🔒 Staking Alice as validator..."

        # Stake Alice
        cd .. && python3 -c "
import sys, requests, time
sys.path.append('.')
from computechain.cli.keystore import KeyStore
from computechain.protocol.types.tx import Transaction
from computechain.protocol.types.common import TxType

ks = KeyStore()
alice = ks.get_key('alice')

# Get alice nonce
resp = requests.get('$NODE_A_RPC/balance/' + alice['address'])
nonce = resp.json()['nonce']

# Create stake tx
tx = Transaction(
    tx_type=TxType.STAKE,
    from_address=alice['address'],
    to_address=None,
    amount=2000 * 10**18,  # 2000 CPC stake
    fee=40000 * 1000,
    nonce=nonce,
    pub_key=alice['public_key'],
    gas_limit=40000,
    gas_price=1000,
    payload={'pub_key': alice['public_key']}
)

# Sign
priv_bytes = bytes.fromhex(alice['private_key'])
tx.sign(priv_bytes)

# Send
resp = requests.post('$NODE_A_RPC/tx/send', json=tx.model_dump())
print(f\"   ✓ Stake sent: {resp.json()}\")
" && cd computechain

        echo ""
        echo "⏳ Waiting for stake transaction (10 seconds)..."
        sleep 12

        # Export Alice key to Node B
        echo ""
        echo "📤 Exporting Alice key to Node B..."
        cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.cli.keystore import KeyStore
ks = KeyStore()
alice = ks.get_key('alice')
with open('computechain/$DATA_DIR_B/validator_key.hex', 'w') as f:
    f.write(alice['private_key'])
print('   ✓ Key exported')
" && cd computechain

    else
        echo ""
        echo "⚠️  Skipping validator creation, will generate new key for node"

        # Generate new validator key for Node B
        echo "   Generating new validator key..."
        cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.protocol.crypto.keys import generate_private_key
priv_key = generate_private_key()
with open('computechain/$DATA_DIR_B/validator_key.hex', 'w') as f:
    f.write(priv_key.hex())
print('   ✓ New validator key generated')
print('   ⚠️  Note: This validator has NO stake, will not participate in consensus')
" && cd computechain
    fi
fi

# Verify key file is not empty
if [ -f "$DATA_DIR_B/validator_key.hex" ]; then
    KEY_SIZE=$(wc -c < "$DATA_DIR_B/validator_key.hex")
    if [ "$KEY_SIZE" -lt 32 ]; then
        echo ""
        echo "❌ Error: Validator key file is empty or corrupted"
        echo "   Generating new key..."
        cd .. && python3 -c "
import sys
sys.path.append('.')
from computechain.protocol.crypto.keys import generate_private_key
priv_key = generate_private_key()
with open('computechain/$DATA_DIR_B/validator_key.hex', 'w') as f:
    f.write(priv_key.hex())
print('   ✓ New validator key generated')
" && cd computechain
    fi
fi

echo ""
echo "✅ Node B configured"
echo "   Data dir: $DATA_DIR_B"
echo "   RPC: http://localhost:$PORT"
echo "   P2P: $P2P_PORT"
echo "   Connecting to: $NODE_A_P2P"
echo ""

# Get validator address if exists
if [ -f "$DATA_DIR_B/validator_key.hex" ]; then
    echo "🔑 Validator Key:"
    python3 -c "
from protocol.crypto.keys import public_key_from_private
from protocol.crypto.addresses import address_from_pubkey
with open('$DATA_DIR_B/validator_key.hex') as f:
    priv = bytes.fromhex(f.read().strip())
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub, prefix='cpcvalcons')
    print(f'   Address: {addr}')
    print(f'   PubKey: {pub.hex()[:32]}...')
"
    echo ""
fi

echo "🚀 Starting Node B..."
echo "   (Press Ctrl+C to stop)"
echo ""
echo "=========================================="
echo ""

# Start node
cd .. && python3 computechain/run_node.py --datadir computechain/$DATA_DIR_B run --port $PORT --p2p-port $P2P_PORT --peers $NODE_A_P2P
