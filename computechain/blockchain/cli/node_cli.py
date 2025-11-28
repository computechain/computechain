import argparse
import os
import sys
import logging
import asyncio
import json
from uvicorn import Config, Server
from ...protocol.crypto.keys import generate_private_key, public_key_from_private
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.config.params import NETWORKS, NetworkConfig, CURRENT_NETWORK, DECIMALS
from ..core.chain import Blockchain
from ..core.mempool import Mempool
from ..consensus.proposer import BlockProposer
from ..rpc.api import app as rpc_app, chain as rpc_chain, mempool as rpc_mempool # Need to inject deps
# Note: rpc_app deps are globals in api.py, we need to set them.
from ..rpc import api # import module to set globals
from ..p2p.node import P2PNode, SyncState

logger = logging.getLogger(__name__)

def cmd_init(args):
    """Initialize node: create keys, genesis (mock), data dir."""
    data_dir = args.datadir
    os.makedirs(data_dir, exist_ok=True)
    
    # Generate Validator Key if not exists
    key_path = os.path.join(data_dir, "validator_key.hex")
    if not os.path.exists(key_path):
        priv = generate_private_key()
        with open(key_path, "w") as f:
            f.write(priv.hex())
        
        pub = public_key_from_private(priv)
        addr = address_from_pubkey(pub, prefix="cpcvalcons")
        print(f"Generated new validator key.")
        print(f"Address: {addr}")
        print(f"PubKey Hex: {pub.hex()}")
    else:
        print(f"Key already exists at {key_path}")
        # Read existing to print info
        with open(key_path, "r") as f:
            priv_hex = f.read().strip()
        pub = public_key_from_private(bytes.fromhex(priv_hex))
        addr = address_from_pubkey(pub, prefix="cpcvalcons")

    # Generate Faucet/Premine Key
    faucet_path = os.path.join(data_dir, "faucet_key.hex")
    if not os.path.exists(faucet_path):
        
        # Using global CURRENT_NETWORK imported from params
        if CURRENT_NETWORK.faucet_priv_key:
            # Use deterministic key for Devnet
            priv_hex = CURRENT_NETWORK.faucet_priv_key
            priv = bytes.fromhex(priv_hex)
            print("\nUsing DETERMINISTIC Devnet Faucet Key.")
        else:
            # Generate random for other networks
            priv = generate_private_key()
            
        with open(faucet_path, "w") as f:
            f.write(priv.hex())
        
        pub = public_key_from_private(priv)
        addr = address_from_pubkey(pub, prefix="cpc")
        print(f"Generated FAUCET key (with premine).")
        print(f"Address: {addr}")
        print(f"SAVE THIS KEY TO SPEND COINS!")
        
        # Save genesis allocation config
        # For MVP Consensus: We also dump current local validator to genesis validators list
        # In real world, genesis is pre-built. Here we build it dynamically for local test.
        with open(os.path.join(data_dir, "genesis.json"), "w") as f:
            import json
            
            # Get local validator info
            with open(key_path, "r") as kf:
                val_priv_hex = kf.read().strip()
            val_pub = public_key_from_private(bytes.fromhex(val_priv_hex))
            val_addr = address_from_pubkey(val_pub, prefix="cpcvalcons")
            
            # Initial Stake for Genesis Validator
            # Must be >= MIN_VALIDATOR_STAKE (1000)
            # We multiply by DECIMALS because state expects raw units
            genesis_stake = 2000 * 10**DECIMALS
            
            genesis_data = {
                "alloc": {
                    addr: CURRENT_NETWORK.genesis_premine
                },
                "validators": [
                    {
                        "address": val_addr,
                        "pub_key": val_pub.hex(),
                        "power": genesis_stake,
                        "is_active": True
                    }
                ]
            }
            f.write(json.dumps(genesis_data, indent=2))
    else:
        print(f"Faucet key already exists at {faucet_path}")

    print(f"\nNode initialized in {data_dir}")

async def run_node_async(args):
    data_dir = args.datadir
    db_path = os.path.join(data_dir, "chain.db")
    key_path = os.path.join(data_dir, "validator_key.hex")
    
    # Persistence for Peers
    peers_file = os.path.join(data_dir, "peers.json")
    
    print(f"Starting ComputeChain node...")
    print(f"Data DB: {db_path}")
    print(f"RPC: {args.host}:{args.port}")
    print(f"P2P: {args.p2p_host}:{args.p2p_port}")
    
    # 1. Initialize Core Components
    chain = Blockchain(db_path)
    
    if args.rebuild_state:
        print("Rebuilding state from blocks as requested...")
        chain.rebuild_state_from_blocks()
        
    mempool = Mempool()
    
    # Inject into RPC module (global vars)
    api.chain = chain
    api.mempool = mempool
    
    # 2. Initialize P2P
    # Load persisted peers
    initial_peers = []
    if os.path.exists(peers_file):
        try:
            with open(peers_file, "r") as f:
                initial_peers = json.load(f)
                logging.info(f"Loaded {len(initial_peers)} persisted peers.")
        except Exception as e:
            logging.warning(f"Failed to load peers.json: {e}")

    # Merge with CLI peers
    if args.peers:
        cli_peers = [p.strip() for p in args.peers.split(",") if p.strip()]
        for p in cli_peers:
            if p not in initial_peers:
                initial_peers.append(p)
    
    p2p_node = P2PNode(
        host=args.p2p_host, 
        port=args.p2p_port, 
        initial_peers=initial_peers,
        network_id=CURRENT_NETWORK.network_id
    )
    
    # 3. Initialize Proposer (if key exists)
    proposer = None
    if os.path.exists(key_path):
        with open(key_path, "r") as f:
            priv_hex = f.read().strip()
        if len(priv_hex) != 64:
            logging.error(f"Invalid validator key length in {key_path}: {len(priv_hex)} chars (expected 64 hex). Check file content.")
        else:
            # Pass P2P Node to Proposer for sync awareness
            proposer = BlockProposer(chain, mempool, priv_hex, p2p_node)
    else:
        logging.warning("No validator key found. Running as read-only node.")

    # 4. Bind Callbacks (The Glue)
    loop = asyncio.get_running_loop()
    
    # Proposer -> P2P
    if proposer:
        def on_block_created_sync(block):
            # Bridge from Thread to Async
            asyncio.run_coroutine_threadsafe(p2p_node.broadcast_block(block), loop)
        proposer.on_block_created = on_block_created_sync

    # P2P -> Chain
    async def on_p2p_block(block):
        try:
            # Idempotency check
            existing = chain.get_block(block.header.height)
            if existing:
                if existing.hash() == block.hash():
                    return # Already have this exact block
                # Different block at same height - fork detected!
                if p2p_node.sync_state == SyncState.SYNCING:
                    logger.info(f"Fork detected at height {block.header.height} during sync. Rolling back...")
                    chain.rollback_last_block()
                    # After rollback, P2P sync will retry from new height
                    return
            
            if chain.add_block(block):
                mempool.remove_transactions(block.txs)
        except ValueError as e:
            # Catch specific validation errors
            logging.warning(f"Rejected P2P block: {e}")
            # If it's a prev_hash mismatch during sync, try to rollback
            if "Invalid prev_hash" in str(e) and p2p_node.sync_state == SyncState.SYNCING:
                logger.info(f"Attempting rollback due to prev_hash mismatch at height {chain.height}")
                chain.rollback_last_block()
                # The sync logic in P2PNode will re-request from the new height
        except Exception as e:
            logging.warning(f"Rejected P2P block: {e}")

    async def on_p2p_tx(tx):
        try:
            mempool.add_transaction(tx)
        except Exception as e:
            logger.warning(f"Rejected P2P tx: {e}")
    
    p2p_node.on_new_block = on_p2p_block
    p2p_node.on_new_tx = on_p2p_tx
    p2p_node.get_current_height = lambda: chain.height
    p2p_node.get_last_hash = lambda: chain.last_block_hash if chain.last_block_hash else ("0"*64)
    p2p_node.get_genesis_hash = lambda: chain.genesis_hash
    p2p_node.get_blocks_range = chain.get_blocks_range

    # 5. Start Services
    
    # Start Proposer (Thread)
    if proposer:
        proposer.start()
        
    # Start RPC (Async Task)
    config = Config(app=rpc_app, host=args.host, port=args.port, log_level="info")
    server = Server(config)
    rpc_task = asyncio.create_task(server.serve())
    
    # Start P2P (Async Task / Main Await)
    try:
        await p2p_node.start()
    except asyncio.CancelledError:
        pass
    finally:
        # Save Peers on Shutdown
        try:
            # Access peers from P2PNode property
            active_peers = p2p_node.peers 
            
            # Combine with initial to not lose offline peers
            all_known = list(set(initial_peers + active_peers))
            with open(peers_file, "w") as f:
                json.dump(all_known, f, indent=2)
            logging.info(f"Saved {len(all_known)} peers to {peers_file}")
        except Exception as e:
            logging.error(f"Failed to save peers: {e}")

        if proposer: proposer.stop()
        rpc_task.cancel()

def cmd_run(args):
    """Wrapper to run async main."""
    try:
        asyncio.run(run_node_async(args))
    except KeyboardInterrupt:
        pass

def main():
    parser = argparse.ArgumentParser(description="ComputeChain Node CLI")
    parser.add_argument("--datadir", default="./.computechain", help="Data directory")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize node configuration")
    
    # Run command
    run_parser = subparsers.add_parser("run", help="Run the node")
    run_parser.add_argument("--host", default="0.0.0.0", help="RPC Host")
    run_parser.add_argument("--port", type=int, default=8000, help="RPC Port")
    
    # P2P Args
    run_parser.add_argument("--p2p-host", default="0.0.0.0", help="P2P Host")
    run_parser.add_argument("--p2p-port", type=int, default=9000, help="P2P Port")
    run_parser.add_argument("--peers", default="", help="Comma-separated list of peers (host:port)")
    
    # State Args
    run_parser.add_argument("--rebuild-state", action="store_true", help="Rebuild state from blocks on startup")

    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)

if __name__ == "__main__":
    main()
