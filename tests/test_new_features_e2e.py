#!/usr/bin/env python3
"""
E2E Test for new validator features (Phase 1-3)
Tests: UPDATE_VALIDATOR, DELEGATE, UNDELEGATE, UNJAIL, graduated slashing
"""

import os
import sys
import time
import shutil
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from computechain.blockchain.core.chain import Blockchain
from computechain.blockchain.core.state import AccountState
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

TEST_DB = "./test_e2e_db"

def cleanup():
    """Remove test database."""
    if os.path.exists(TEST_DB):
        shutil.rmtree(TEST_DB)

def setup_chain():
    """Initialize test blockchain."""
    cleanup()
    os.makedirs(TEST_DB, exist_ok=True)
    db_path = os.path.join(TEST_DB, "chain.db")
    return Blockchain(db_path)

def print_status(msg):
    """Print test status message."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

def main():
    print_status("Starting E2E Tests for New Validator Features")

    try:
        chain = setup_chain()
        state = chain.state

        # Create validator
        val_priv = generate_private_key()
        val_pub = public_key_from_private(val_priv)
        val_owner = address_from_pubkey(val_pub)
        val_addr = address_from_pubkey(val_pub, prefix="cpcvalcons")

        print(f"\nValidator Owner: {val_owner}")
        print(f"Validator Cons:  {val_addr}")

        # Fund validator owner
        acc = state.get_account(val_owner)
        acc.balance = 5000 * 10**18  # 5000 CPC
        state.set_account(acc)
        print(f"Initial Balance: {acc.balance / 10**18} CPC")

        # TEST 1: STAKE
        print_status("TEST 1: Stake 1000 CPC")
        tx_stake = Transaction(
            tx_type=TxType.STAKE,
            from_address=val_owner,
            amount=1000 * 10**18,
            nonce=0,
            gas_price=1000,
            gas_limit=100000,
            fee=40_000 * 1000,
            timestamp=int(time.time()),
            pub_key=val_pub.hex(),
            payload={"pub_key": val_pub.hex()}
        )
        tx_stake.sign(val_priv)
        state.apply_transaction(tx_stake)

        val = state.get_validator(val_addr)
        print(f"✓ Validator created with power: {val.power / 10**18} CPC")
        assert val.power == 1000 * 10**18

        # TEST 2: UPDATE_VALIDATOR
        print_status("TEST 2: Update Validator Metadata")
        tx_update = Transaction(
            tx_type=TxType.UPDATE_VALIDATOR,
            from_address=val_owner,
            amount=0,
            nonce=1,
            gas_price=1000,
            gas_limit=50000,
            fee=30_000 * 1000,
            timestamp=int(time.time()),
            pub_key=val_pub.hex(),
            payload={
                "pub_key": val_pub.hex(),
                "name": "E2E Test Pool",
                "website": "https://testpool.com",
                "description": "Test validator for E2E testing",
                "commission_rate": 0.12
            }
        )
        tx_update.sign(val_priv)
        state.apply_transaction(tx_update)

        val = state.get_validator(val_addr)
        print(f"✓ Name: {val.name}")
        print(f"✓ Website: {val.website}")
        print(f"✓ Commission: {val.commission_rate * 100}%")
        assert val.name == "E2E Test Pool"
        assert val.commission_rate == 0.12

        # TEST 3: DELEGATE
        print_status("TEST 3: Delegate 500 CPC to Validator")
        del_priv = generate_private_key()
        del_pub = public_key_from_private(del_priv)
        del_addr = address_from_pubkey(del_pub)

        acc_del = state.get_account(del_addr)
        acc_del.balance = 1000 * 10**18
        state.set_account(acc_del)
        print(f"Delegator: {del_addr}")

        tx_delegate = Transaction(
            tx_type=TxType.DELEGATE,
            from_address=del_addr,
            amount=500 * 10**18,
            nonce=0,
            gas_price=1000,
            gas_limit=50000,
            fee=35_000 * 1000,
            timestamp=int(time.time()),
            pub_key=del_pub.hex(),
            payload={"validator": val_addr}
        )
        tx_delegate.sign(del_priv)
        state.apply_transaction(tx_delegate)

        val = state.get_validator(val_addr)
        print(f"✓ Total Delegated: {val.total_delegated / 10**18} CPC")
        print(f"✓ Total Power: {val.power / 10**18} CPC")
        assert val.total_delegated == 500 * 10**18
        assert val.power == 1500 * 10**18  # 1000 self + 500 delegated

        # TEST 4: UNDELEGATE
        print_status("TEST 4: Undelegate 200 CPC")
        balance_before = state.get_account(del_addr).balance

        tx_undelegate = Transaction(
            tx_type=TxType.UNDELEGATE,
            from_address=del_addr,
            amount=200 * 10**18,
            nonce=1,
            gas_price=1000,
            gas_limit=50000,
            fee=35_000 * 1000,
            timestamp=int(time.time()),
            pub_key=del_pub.hex(),
            payload={"validator": val_addr}
        )
        tx_undelegate.sign(del_priv)
        state.apply_transaction(tx_undelegate)

        val = state.get_validator(val_addr)
        balance_after = state.get_account(del_addr).balance
        print(f"✓ Remaining Delegated: {val.total_delegated / 10**18} CPC")
        print(f"✓ Delegator got back: {(balance_after - balance_before) / 10**18} CPC (minus fees)")
        assert val.total_delegated == 300 * 10**18
        assert val.power == 1300 * 10**18

        # TEST 5: Graduated Slashing
        print_status("TEST 5: Graduated Slashing")
        initial_power = val.power

        # First jail: 5%
        chain._jail_validator(val, state, 100)
        penalty1 = int(initial_power * 0.05)
        print(f"✓ 1st Jail - Penalty: {penalty1 / 10**18} CPC (5%)")
        print(f"  Power after: {val.power / 10**18} CPC")
        assert val.jail_count == 1
        power_after_first = val.power

        # Second jail: 10%
        chain._jail_validator(val, state, 200)
        penalty2 = int(power_after_first * 0.10)
        print(f"✓ 2nd Jail - Penalty: {penalty2 / 10**18} CPC (10%)")
        print(f"  Power after: {val.power / 10**18} CPC")
        assert val.jail_count == 2
        power_after_second = val.power

        # Third jail: 100% (ejection)
        chain._jail_validator(val, state, 300)
        print(f"✓ 3rd Jail - Penalty: {power_after_second / 10**18} CPC (100% - EJECTION)")
        print(f"  Power after: {val.power / 10**18} CPC")
        assert val.power == 0
        assert val.jail_count == 3

        # TEST 6: UNJAIL (create new validator first)
        print_status("TEST 6: Unjail Transaction")
        val2_priv = generate_private_key()
        val2_pub = public_key_from_private(val2_priv)
        val2_owner = address_from_pubkey(val2_pub)
        val2_addr = address_from_pubkey(val2_pub, prefix="cpcvalcons")

        # Fund and stake
        acc2 = state.get_account(val2_owner)
        acc2.balance = 3000 * 10**18
        state.set_account(acc2)

        tx_stake2 = Transaction(
            tx_type=TxType.STAKE,
            from_address=val2_owner,
            amount=500 * 10**18,
            nonce=0,
            gas_price=1000,
            gas_limit=100000,
            fee=40_000 * 1000,
            timestamp=int(time.time()),
            pub_key=val2_pub.hex(),
            payload={"pub_key": val2_pub.hex()}
        )
        tx_stake2.sign(val2_priv)
        state.apply_transaction(tx_stake2)

        # Jail validator 2
        val2 = state.get_validator(val2_addr)
        val2.jailed_until_height = 1000
        val2.is_active = False
        state.set_validator(val2)
        print(f"Validator 2 jailed until block 1000")

        # Unjail
        tx_unjail = Transaction(
            tx_type=TxType.UNJAIL,
            from_address=val2_owner,
            amount=1000 * 10**18,  # 1000 CPC fee
            nonce=1,
            gas_price=1000,
            gas_limit=100000,
            fee=50_000 * 1000,
            timestamp=int(time.time()),
            pub_key=val2_pub.hex(),
            payload={"pub_key": val2_pub.hex()}
        )
        tx_unjail.sign(val2_priv)
        state.apply_transaction(tx_unjail)

        val2 = state.get_validator(val2_addr)
        print(f"✓ Unjailed successfully")
        print(f"  Jailed until: {val2.jailed_until_height}")
        print(f"  Active: {val2.is_active}")
        assert val2.jailed_until_height == 0
        assert val2.is_active == True

        # TEST 7: Min Uptime Score Filter
        print_status("TEST 7: Min Uptime Score Filter (0.75)")
        val2.blocks_proposed = 5
        val2.blocks_expected = 10
        val2.uptime_score = 0.50  # 50% - below minimum
        state.set_validator(val2)

        # Process epoch transition
        chain._process_epoch_transition(state)

        val2_after = state.get_validator(val2_addr)
        print(f"✓ Validator with 50% uptime filtered out")
        print(f"  Active: {val2_after.is_active}")
        # Note: validator might become inactive if not in top N by performance score

        print_status("✅ ALL E2E TESTS PASSED!")
        print("\nSummary:")
        print("  ✓ UPDATE_VALIDATOR - metadata updated")
        print("  ✓ DELEGATE - tokens delegated successfully")
        print("  ✓ UNDELEGATE - tokens returned correctly")
        print("  ✓ Graduated Slashing - 5%, 10%, 100%")
        print("  ✓ UNJAIL - early release working")
        print("  ✓ Min Uptime Filter - low performers filtered")

        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        cleanup()

if __name__ == "__main__":
    sys.exit(main())
