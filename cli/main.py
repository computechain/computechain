# MIT License
# Copyright (c) 2025 Hashborn

import argparse
import sys
import json
import requests
import os
from typing import Optional
from .keystore import KeyStore
from ..protocol.types.tx import Transaction, TxType
from ..protocol.types.poc import ComputeResult
from ..protocol.crypto.hash import sha256
from ..protocol.crypto.keys import sign, public_key_from_private
from ..protocol.config.params import CURRENT_NETWORK, DECIMALS, DENOM
import time

DEFAULT_NODE = "http://localhost:8000"

def get_node_url(args):
    return args.node or os.environ.get("CPC_NODE", DEFAULT_NODE)

# --- Keys Commands ---
def cmd_keys_add(args):
    ks = KeyStore()
    try:
        key = ks.create_key(args.name)
        print(f"Key '{args.name}' created.")
        print(f"Address: {key['address']}")
        print(f"Pubkey:  {key['public_key']}")
        print("Important: Private key saved unencrypted (MVP). Do not share!")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

def cmd_keys_import(args):
    ks = KeyStore()
    try:
        if not args.private_key:
             print("Error: --private-key required")
             sys.exit(1)
             
        key = ks.import_key(args.name, args.private_key)
        print(f"Key '{args.name}' imported.")
        print(f"Address: {key['address']}")
    except ValueError as e:
        print(f"Error: {e}")

def cmd_keys_list(args):
    ks = KeyStore()
    keys = ks.list_keys()
    if not keys:
        print("No keys found.")
        return
    
    print(f"{'Name':<15} {'Address':<45}")
    print("-" * 60)
    for k in keys:
        print(f"{k['name']:<15} {k['address']:<45}")

def cmd_keys_show(args):
    ks = KeyStore()
    key = ks.get_key(args.name)
    if not key:
        print(f"Key '{args.name}' not found.")
        sys.exit(1)
    print(json.dumps({k:v for k,v in key.items() if k != 'private_key'}, indent=2))

# --- Query Commands ---
def cmd_query_balance(args):
    url = get_node_url(args)
    try:
        resp = requests.get(f"{url}/balance/{args.address}")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            sys.exit(1)
        data = resp.json()
        balance = int(data['balance'])
        print(f"Balance: {balance / 10**DECIMALS} {DENOM}")
        print(f"Nonce: {data['nonce']}")
    except Exception as e:
        print(f"Connection error: {e}")
        sys.exit(1)

def cmd_query_block(args):
    url = get_node_url(args)
    try:
        resp = requests.get(f"{url}/block/{args.height}")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            sys.exit(1)
        print(json.dumps(resp.json(), indent=2))
    except Exception as e:
        print(f"Connection error: {e}")

def cmd_query_validators(args):
    url = get_node_url(args)
    try:
        resp = requests.get(f"{url}/validators")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            sys.exit(1)
        data = resp.json()
        print(f"Epoch: {data['epoch']}")
        print(f"{'Address':<45} {'Power':<10} {'Active'}")
        print("-" * 70)
        for v in data['validators']:
            print(f"{v['address']:<45} {v['power']:<10} {v['is_active']}")
    except Exception as e:
        print(f"Connection error: {e}")

# --- Tx Commands ---
def get_nonce(url, address):
    try:
        resp = requests.get(f"{url}/balance/{address}")
        if resp.status_code != 200:
             raise ValueError(f"Node error: {resp.text}")
        return resp.json()['nonce']
    except Exception as e:
        raise e

def broadcast_tx(url, tx):
    tx_json = tx.model_dump()
    tx_json['tx_type'] = tx.tx_type.value # Serialize Enum
    try:
        resp = requests.post(f"{url}/tx/send", json=tx_json)
        if resp.status_code == 200:
            res = resp.json()
            print(f"Success! TxHash: {res['tx_hash']}")
        else:
            print(f"Error broadcasting: {resp.text}")
    except Exception as e:
         print(f"Connection error: {e}")

def cmd_tx_send(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)
    
    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    amount_units = int(float(args.amount) * 10**DECIMALS)
    
    # Calculate fee
    fee = args.gas_limit * args.gas_price
    
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=from_addr,
        to_address=args.to_address,
        amount=amount_units,
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex  # Include pub_key for verification
    )
    
    tx.sign(priv_key_bytes)
    
    print(f"Sending {args.amount} {DENOM} to {args.to_address}...")
    broadcast_tx(url, tx)

def cmd_tx_stake(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)
    
    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    
    # Get pubkey for validator registration
    # Note: keystore stores pubkey as hex string usually
    pub_key_hex = sender_key['public_key'] 

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    amount_units = int(float(args.amount) * 10**DECIMALS)
    
    # Calculate fee
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.STAKE,
        from_address=from_addr,
        to_address=None, # Stake doesn't have a recipient in this model
        amount=amount_units,
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,  # Include pub_key for verification
        payload={"pub_key": pub_key_hex} # Pass pubkey for registration (legacy/payload usage)
    )
    
    tx.sign(priv_key_bytes)
    
    print(f"Staking {args.amount} {DENOM} from {from_addr}...")
    broadcast_tx(url, tx)

def cmd_tx_unstake(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)

    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])

    # Get pubkey for validator identification
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    amount_units = int(float(args.amount) * 10**DECIMALS)

    # Calculate fee
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=from_addr,
        to_address=None,  # Unstake doesn't have a recipient
        amount=amount_units,
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload={"pub_key": pub_key_hex}  # Pass pubkey to identify validator
    )

    tx.sign(priv_key_bytes)

    print(f"Unstaking {args.amount} {DENOM} from validator {from_addr}...")
    broadcast_tx(url, tx)

def cmd_tx_update_validator(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)

    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    # Build payload with only provided fields
    payload = {"pub_key": pub_key_hex}
    if args.name:
        payload["name"] = args.name
    if args.website:
        payload["website"] = args.website
    if args.description:
        payload["description"] = args.description
    if args.commission is not None:
        payload["commission_rate"] = args.commission

    # Calculate fee
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.UPDATE_VALIDATOR,
        from_address=from_addr,
        to_address=None,
        amount=0,  # No token transfer
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload=payload
    )

    tx.sign(priv_key_bytes)

    print(f"Updating validator metadata...")
    broadcast_tx(url, tx)

def cmd_tx_delegate(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)

    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    amount_units = int(float(args.amount) * 10**DECIMALS)
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.DELEGATE,
        from_address=from_addr,
        to_address=None,
        amount=amount_units,
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload={"validator": args.validator}
    )

    tx.sign(priv_key_bytes)

    print(f"Delegating {args.amount} {DENOM} to validator {args.validator}...")
    broadcast_tx(url, tx)

def cmd_tx_undelegate(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)

    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    amount_units = int(float(args.amount) * 10**DECIMALS)
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.UNDELEGATE,
        from_address=from_addr,
        to_address=None,
        amount=amount_units,
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload={"validator": args.validator}
    )

    tx.sign(priv_key_bytes)

    print(f"Undelegating {args.amount} {DENOM} from validator {args.validator}...")
    broadcast_tx(url, tx)

def cmd_tx_unjail(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)

    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    # Unjail fee: 1000 CPC
    unjail_amount = int(1000 * 10**DECIMALS)
    fee = args.gas_limit * args.gas_price

    tx = Transaction(
        tx_type=TxType.UNJAIL,
        from_address=from_addr,
        to_address=None,
        amount=unjail_amount,  # Unjail fee
        fee=fee,
        nonce=nonce,
        gas_price=args.gas_price,
        gas_limit=args.gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload={"pub_key": pub_key_hex}
    )

    tx.sign(priv_key_bytes)

    print(f"Requesting unjail (fee: 1000 {DENOM})...")
    broadcast_tx(url, tx)

def cmd_tx_submit_result(args):
    ks = KeyStore()
    sender_key = ks.get_key(args.from_name)
    if not sender_key:
        print(f"Key '{args.from_name}' not found.")
        sys.exit(1)
    
    url = get_node_url(args)
    from_addr = sender_key['address']
    priv_key_bytes = bytes.fromhex(sender_key['private_key'])
    pub_key_hex = sender_key['public_key']

    try:
        nonce = get_nonce(url, from_addr)
    except Exception as e:
        print(e)
        sys.exit(1)

    # Create payload
    res = ComputeResult(
        task_id=args.task_id,
        worker_address=from_addr,
        result_hash=args.result_hash,
        proof=args.proof or "",
        nonce=args.nonce or 0,
        signature="" # Worker signature could be here, but Tx signature covers it
    )
    
    gas_price = 1000
    gas_limit = 100000
    fee = gas_limit * gas_price

    tx = Transaction(
        tx_type=TxType.SUBMIT_RESULT,
        from_address=from_addr,
        to_address=None,
        amount=0,
        fee=fee,
        nonce=nonce,
        gas_price=gas_price,
        gas_limit=gas_limit,
        timestamp=int(time.time()),
        pub_key=pub_key_hex,
        payload=res.model_dump()
    )
    
    tx.sign(priv_key_bytes)
    
    print(f"Submitting result for task {args.task_id}...")
    broadcast_tx(url, tx)

def main():
    parser = argparse.ArgumentParser(prog="computechain-cli", description="ComputeChain Client CLI")
    parser.add_argument("--node", help="Node URL (default: http://localhost:8000)")
    
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")
    
    # keys
    p_keys = subparsers.add_parser("keys", help="Manage keys")
    sp_keys = p_keys.add_subparsers(dest="subcommand")
    
    pk_add = sp_keys.add_parser("add", help="Create new key")
    pk_add.add_argument("name", help="Key name")
    
    pk_imp = sp_keys.add_parser("import", help="Import private key")
    pk_imp.add_argument("name", help="Key name")
    pk_imp.add_argument("--private-key", required=True, help="Hex private key")

    pk_list = sp_keys.add_parser("list", help="List keys")
    
    pk_show = sp_keys.add_parser("show", help="Show key details")
    pk_show.add_argument("name", help="Key name")

    # query
    p_query = subparsers.add_parser("query", help="Query blockchain state")
    sp_query = p_query.add_subparsers(dest="subcommand")
    
    pq_bal = sp_query.add_parser("balance", help="Get account balance")
    pq_bal.add_argument("address", help="Account address")
    
    pq_block = sp_query.add_parser("block", help="Get block by height")
    pq_block.add_argument("height", type=int, help="Block height")

    pq_vals = sp_query.add_parser("validators", help="Get active validators")

    # tx
    p_tx = subparsers.add_parser("tx", help="Create and send transactions")
    sp_tx = p_tx.add_subparsers(dest="subcommand")
    
    pt_send = sp_tx.add_parser("send", help="Send CPC tokens")
    pt_send.add_argument("to_address", help="Recipient address")
    pt_send.add_argument("amount", type=float, help="Amount in CPC")
    pt_send.add_argument("--from", dest="from_name", required=True, help="Sender key name")
    pt_send.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_send.add_argument("--gas-limit", type=int, default=21000, help="Gas limit")

    pt_stake = sp_tx.add_parser("stake", help="Become validator or increase stake")
    pt_stake.add_argument("amount", type=float, help="Amount to stake in CPC")
    pt_stake.add_argument("--from", dest="from_name", required=True, help="Sender key name")
    pt_stake.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_stake.add_argument("--gas-limit", type=int, default=100000, help="Gas limit")

    pt_unstake = sp_tx.add_parser("unstake", help="Withdraw stake from validator")
    pt_unstake.add_argument("amount", type=float, help="Amount to unstake in CPC")
    pt_unstake.add_argument("--from", dest="from_name", required=True, help="Sender key name")
    pt_unstake.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_unstake.add_argument("--gas-limit", type=int, default=100000, help="Gas limit")

    pt_update_val = sp_tx.add_parser("update-validator", help="Update validator metadata")
    pt_update_val.add_argument("--name", help="Validator name (max 64 chars)")
    pt_update_val.add_argument("--website", help="Website URL (max 128 chars)")
    pt_update_val.add_argument("--description", help="Description (max 256 chars)")
    pt_update_val.add_argument("--commission", type=float, help="Commission rate (0.0-1.0)")
    pt_update_val.add_argument("--from", dest="from_name", required=True, help="Validator key name")
    pt_update_val.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_update_val.add_argument("--gas-limit", type=int, default=50000, help="Gas limit")

    pt_delegate = sp_tx.add_parser("delegate", help="Delegate tokens to validator")
    pt_delegate.add_argument("validator", help="Validator address (cpcvalcons...)")
    pt_delegate.add_argument("amount", type=float, help="Amount to delegate in CPC")
    pt_delegate.add_argument("--from", dest="from_name", required=True, help="Delegator key name")
    pt_delegate.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_delegate.add_argument("--gas-limit", type=int, default=50000, help="Gas limit")

    pt_undelegate = sp_tx.add_parser("undelegate", help="Undelegate tokens from validator")
    pt_undelegate.add_argument("validator", help="Validator address (cpcvalcons...)")
    pt_undelegate.add_argument("amount", type=float, help="Amount to undelegate in CPC")
    pt_undelegate.add_argument("--from", dest="from_name", required=True, help="Delegator key name")
    pt_undelegate.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_undelegate.add_argument("--gas-limit", type=int, default=50000, help="Gas limit")

    pt_unjail = sp_tx.add_parser("unjail", help="Request early release from jail")
    pt_unjail.add_argument("--from", dest="from_name", required=True, help="Validator key name")
    pt_unjail.add_argument("--gas-price", type=int, default=1000, help="Gas price")
    pt_unjail.add_argument("--gas-limit", type=int, default=100000, help="Gas limit")

    pt_res = sp_tx.add_parser("submit-result", help="Submit PoC result")
    pt_res.add_argument("--task-id", required=True)
    pt_res.add_argument("--result-hash", required=True)
    pt_res.add_argument("--proof", default="")
    pt_res.add_argument("--nonce", type=int, default=0)
    pt_res.add_argument("--from", dest="from_name", required=True, help="Worker key name")

    args = parser.parse_args()
    
    if args.command == "keys":
        if args.subcommand == "add": cmd_keys_add(args)
        elif args.subcommand == "import": cmd_keys_import(args)
        elif args.subcommand == "list": cmd_keys_list(args)
        elif args.subcommand == "show": cmd_keys_show(args)
        else: p_keys.print_help()
        
    elif args.command == "query":
        if args.subcommand == "balance": cmd_query_balance(args)
        elif args.subcommand == "block": cmd_query_block(args)
        elif args.subcommand == "validators": cmd_query_validators(args)
        else: p_query.print_help()
        
    elif args.command == "tx":
        if args.subcommand == "send": cmd_tx_send(args)
        elif args.subcommand == "stake": cmd_tx_stake(args)
        elif args.subcommand == "unstake": cmd_tx_unstake(args)
        elif args.subcommand == "update-validator": cmd_tx_update_validator(args)
        elif args.subcommand == "delegate": cmd_tx_delegate(args)
        elif args.subcommand == "undelegate": cmd_tx_undelegate(args)
        elif args.subcommand == "unjail": cmd_tx_unjail(args)
        elif args.subcommand == "submit-result": cmd_tx_submit_result(args)
        else: p_tx.print_help()
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
