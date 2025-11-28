import sys
import os
import time
import requests
import threading
import json

# Add project root to path
sys.path.append(os.getcwd())

from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

# Configuration
NODE_A_URL = "http://localhost:8000"
NODE_B_URL = "http://localhost:8001"
FAUCET_KEY_FILE = ".node_a/faucet_key.hex"

def get_private_key():
    with open(FAUCET_KEY_FILE, "r") as f:
        return f.read().strip()

def get_validators(node_url):
    try:
        resp = requests.get(f"{node_url}/validators")
        data = resp.json()
        # Return the list under 'validators' key
        return data.get("validators", [])
    except:
        return []

def get_balance(node_url, address):
    try:
        resp = requests.get(f"{node_url}/balance/{address}")
        return resp.json().get("balance", 0)
    except:
        return 0

def get_nonce(node_url, address):
    try:
        resp = requests.get(f"{node_url}/balance/{address}")
        return resp.json().get("nonce", 0)
    except:
        return 0

def wait_for_two_validators():
    print("--- Step 1: Waiting for Node B (Alice) to become ACTIVE ---")
    print(f"Polling {NODE_A_URL}/validators every 2s...")
    
    while True:
        vals = get_validators(NODE_A_URL)
        active_count = sum(1 for v in vals if v['is_active'])
        print(f"Current Active Validators: {active_count} / {len(vals)}")
        
        if active_count >= 2:
            print("✅ Success! We have 2 active validators.")
            print("Validators:", [v['address'] for v in vals if v['is_active']])
            break
        
        time.sleep(2)

def test_gas_logic():
    print("\n--- Step 2: Testing Gas & Fee Logic (Anti-Spam) ---")
    
    priv_hex = get_private_key()
    priv_bytes = bytes.fromhex(priv_hex)
    pub_bytes = public_key_from_private(priv_bytes)
    addr = address_from_pubkey(pub_bytes)
    
    nonce = get_nonce(NODE_A_URL, addr)
    recipient = "cpc1testsomenonexistingaddress12345"
    
    # 2.1 Low Gas Price
    print(f"[Test] Sending Tx with Gas Price 1 (Min is 1000)...")
    tx_low_price = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address=recipient,
        amount=100,
        nonce=nonce,
        gas_limit=21000,
        gas_price=1,      # TOO LOW
        fee=21000 * 1,
        pub_key=pub_bytes.hex(),
        timestamp=int(time.time())
    )
    tx_low_price.sign(priv_bytes)
    
    try:
        resp = requests.post(f"{NODE_A_URL}/tx/send", json=tx_low_price.model_dump())
        data = resp.json()
        if resp.status_code != 200:
             print(f"✅ Rejected (HTTP error): {resp.text}")
        elif data.get("status") == "rejected":
             print(f"✅ Rejected (Mempool validation): {data.get('error')}")
        else:
             print(f"❌ ERROR: Tx accepted unexpectedly! Status: {data.get('status')}")
    except Exception as e:
        print(f"Error: {e}")

    # 2.2 Low Fee
    print(f"[Test] Sending Tx with Fee 0 (Need ~21M)...")
    tx_low_fee = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address=recipient,
        amount=100,
        nonce=nonce,
        gas_limit=21000,
        gas_price=1000,
        fee=0,           # TOO LOW
        pub_key=pub_bytes.hex(),
        timestamp=int(time.time())
    )
    tx_low_fee.sign(priv_bytes)
    
    try:
        resp = requests.post(f"{NODE_A_URL}/tx/send", json=tx_low_fee.model_dump())
        data = resp.json()
        if resp.status_code != 200:
             print(f"✅ Rejected (HTTP error): {resp.text}")
        elif data.get("status") == "rejected":
             print(f"✅ Rejected (Mempool validation): {data.get('error')}")
        else:
             print(f"❌ ERROR: Tx accepted unexpectedly! Status: {data.get('status')}")
    except Exception as e:
        print(f"Error: {e}")

    # 2.3 Valid Tx
    print(f"[Test] Sending VALID Tx...")
    tx_valid = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address=recipient,
        amount=1000,
        nonce=nonce,
        gas_limit=21000,
        gas_price=1000,
        fee=21000 * 1000, # Correct Fee
        pub_key=pub_bytes.hex(),
        timestamp=int(time.time())
    )
    tx_valid.sign(priv_bytes)
    
    try:
        resp = requests.post(f"{NODE_A_URL}/tx/send", json=tx_valid.model_dump())
        if resp.status_code == 200 and resp.json().get("status") == "received":
             print(f"✅ Accepted: {resp.json()}")
        else:
             print(f"❌ ERROR: Valid tx rejected! {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    if not os.path.exists(FAUCET_KEY_FILE):
        print("Error: Faucet key not found. Did you run ./start_node_a.sh?")
        return

    # 1. Wait for network to stabilize with 2 validators
    wait_for_two_validators()
    
    # 2. Run spam/gas tests
    test_gas_logic()
    
    print("\n✅ E2E Battle Test Complete.")

if __name__ == "__main__":
    main()

