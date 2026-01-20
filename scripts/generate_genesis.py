#!/usr/bin/env python3
"""
Generate shared genesis for multi-validator ComputeChain testnet.

This script creates a single genesis.json with ALL validators pre-configured,
ensuring all nodes start with identical state for proper P2P consensus.

Usage:
    python scripts/generate_genesis.py \
        --validators 5 \
        --genesis-output data/shared_genesis.json \
        --keys-dir data/keys \
        --stake 10000
"""

import argparse
import os
import sys
import json
import time

# Add parent to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from protocol.crypto.keys import generate_private_key, public_key_from_private
from protocol.crypto.addresses import address_from_pubkey
from protocol.config.params import CURRENT_NETWORK, DECIMALS


def generate_genesis(
    num_validators: int,
    stake_amount: float,
    keys_dir: str,
    genesis_output: str,
    faucet_balance: int = None
):
    """
    Generate shared genesis file with multiple validators.

    Args:
        num_validators: Number of validators to create
        stake_amount: Initial stake per validator in CPC
        keys_dir: Directory to save validator and faucet keys
        genesis_output: Path for output genesis.json
        faucet_balance: Faucet balance (uses network default if None)
    """
    os.makedirs(keys_dir, exist_ok=True)
    os.makedirs(os.path.dirname(genesis_output) or '.', exist_ok=True)

    validators = []
    stake_units = int(stake_amount * 10**DECIMALS)

    print(f"Generating shared genesis with {num_validators} validators...")
    print(f"Stake per validator: {stake_amount} CPC ({stake_units} units)")
    print()

    # Generate validator keys
    for i in range(1, num_validators + 1):
        priv = generate_private_key()
        pub = public_key_from_private(priv)
        val_addr = address_from_pubkey(pub, prefix="cpcvalcons")
        reward_addr = address_from_pubkey(pub, prefix="cpc")

        # Save private key
        key_path = os.path.join(keys_dir, f"validator_{i}.hex")
        with open(key_path, "w") as f:
            f.write(priv.hex())
        os.chmod(key_path, 0o600)  # Restrict permissions

        validators.append({
            "address": val_addr,
            "pub_key": pub.hex(),
            "power": stake_units,
            "is_active": True,
            "reward_address": reward_addr
        })

        print(f"  Validator {i}:")
        print(f"    Consensus: {val_addr}")
        print(f"    Reward:    {reward_addr}")

    # Generate faucet key (deterministic for devnet)
    if CURRENT_NETWORK.faucet_priv_key:
        faucet_priv = bytes.fromhex(CURRENT_NETWORK.faucet_priv_key)
        print(f"\n  Using DETERMINISTIC devnet faucet key")
    else:
        faucet_priv = generate_private_key()
        print(f"\n  Generated new faucet key")

    faucet_pub = public_key_from_private(faucet_priv)
    faucet_addr = address_from_pubkey(faucet_pub, prefix="cpc")

    # Save faucet key
    faucet_path = os.path.join(keys_dir, "faucet.hex")
    with open(faucet_path, "w") as f:
        f.write(faucet_priv.hex())
    os.chmod(faucet_path, 0o600)

    print(f"  Faucet: {faucet_addr}")

    # Determine faucet balance
    if faucet_balance is None:
        faucet_balance = CURRENT_NETWORK.genesis_premine

    # Create genesis
    genesis_time = int(time.time())
    genesis_data = {
        "alloc": {
            faucet_addr: faucet_balance
        },
        "validators": validators,
        "genesis_time": genesis_time
    }

    # Write genesis
    with open(genesis_output, "w") as f:
        json.dump(genesis_data, f, indent=2)

    print(f"\n--- Genesis Summary ---")
    print(f"Validators: {num_validators}")
    print(f"Faucet balance: {faucet_balance / 10**DECIMALS:,.0f} CPC")
    print(f"Genesis file: {genesis_output}")
    print(f"Keys directory: {keys_dir}/")
    print(f"\nFiles created:")
    print(f"  {genesis_output}")
    for i in range(1, num_validators + 1):
        print(f"  {keys_dir}/validator_{i}.hex")
    print(f"  {keys_dir}/faucet.hex")


def main():
    parser = argparse.ArgumentParser(
        description="Generate shared genesis for ComputeChain multi-validator testnet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 5-validator testnet
  python scripts/generate_genesis.py --validators 5

  # Custom stake and output paths
  python scripts/generate_genesis.py \\
      --validators 3 \\
      --stake 50000 \\
      --genesis-output ./testnet/genesis.json \\
      --keys-dir ./testnet/keys
"""
    )
    parser.add_argument(
        "--validators", "-n",
        type=int,
        default=5,
        help="Number of validators (default: 5)"
    )
    parser.add_argument(
        "--stake", "-s",
        type=float,
        default=10000,
        help="Initial stake per validator in CPC (default: 10000)"
    )
    parser.add_argument(
        "--keys-dir", "-k",
        default="./data/keys",
        help="Output directory for validator keys (default: ./data/keys)"
    )
    parser.add_argument(
        "--genesis-output", "-o",
        default="./data/shared_genesis.json",
        help="Genesis file output path (default: ./data/shared_genesis.json)"
    )

    args = parser.parse_args()

    if args.validators < 1:
        parser.error("Number of validators must be at least 1")

    if args.stake < 1000:
        print(f"Warning: Stake {args.stake} CPC is below minimum validator stake (1000 CPC)")

    generate_genesis(
        num_validators=args.validators,
        stake_amount=args.stake,
        keys_dir=args.keys_dir,
        genesis_output=args.genesis_output
    )


if __name__ == "__main__":
    main()
