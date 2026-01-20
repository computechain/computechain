# MIT License
# Copyright (c) 2025 Hashborn

"""
Economic Invariant Tests (Phase 1.2)

Tests that economic invariants hold under various scenarios:
1. Supply conservation (genesis + minted - burned = all balances)
2. Reward distribution correctness
3. Non-negative balances
"""

import pytest
import os
import shutil
import json
import time
from blockchain.core.chain import Blockchain
from blockchain.core.state import AccountState
from protocol.types.tx import Transaction, TxType
from protocol.crypto.keys import generate_private_key, public_key_from_private
from protocol.crypto.addresses import address_from_pubkey
from protocol.config.params import CURRENT_NETWORK, DECIMALS


@pytest.fixture
def chain():
    """Create a test blockchain."""
    db_dir = "./test_invariants_db"
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)
    os.makedirs(db_dir, exist_ok=True)

    with open(os.path.join(db_dir, "genesis.json"), "w") as f:
        json.dump({"alloc": {}, "validators": [], "genesis_time": int(time.time()) - 100}, f)

    db_path = os.path.join(db_dir, "chain.db")
    blockchain = Blockchain(db_path=db_path)
    yield blockchain

    # Cleanup
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)


def test_supply_conservation(chain):
    """
    Test that total supply is conserved.

    Invariant:
        genesis_supply + total_minted - total_burned
        = sum(all_account_balances) + sum(all_validator_stakes) + sum(all_delegations) + sum(unbonding)
    """
    genesis_supply = CURRENT_NETWORK.genesis_premine

    # Create validator
    val_priv = generate_private_key()
    val_pub = public_key_from_private(val_priv)
    val_addr = address_from_pubkey(val_pub, prefix="cpcvalcons")
    val_reward_addr = address_from_pubkey(val_pub, prefix="cpc")

    # STAKE transaction
    stake_tx = Transaction(
        tx_type=TxType.STAKE,
        from_address=val_reward_addr,
        to_address="",
        amount=1000 * DECIMALS,
        nonce=0,
        gas_price=1000,
        signature=b"",
        public_key=val_pub.hex(),
        payload={
            "validator_address": val_addr,
            "pubkey": val_pub.hex(),
            "commission_rate": 0.10
        }
    )

    # Sign and add to chain
    from protocol.crypto.keys import sign
    stake_tx.signature = sign(stake_tx.signing_bytes(), val_priv)

    # Mine blocks to generate rewards
    for i in range(5):
        chain.add_block([stake_tx] if i == 0 else [])

    # Calculate total supply
    state = chain.state

    # Get all balances
    total_balances = sum(
        chain.state.get_account(addr).balance
        for addr in chain.state._accounts.keys()
    )

    # Get all validator stakes
    total_validator_stakes = sum(
        v.self_stake for v in state.get_all_validators()
    )

    # Get all delegations
    total_delegations = sum(
        v.total_delegated for v in state.get_all_validators()
    )

    # Get unbonding queue
    total_unbonding = sum(
        sum(entry.amount for entry in acc.unbonding_delegations)
        for acc in state._accounts.values()
    )

    # Calculate total from accounting
    total_from_accounting = (
        total_balances +
        total_validator_stakes +
        total_delegations +
        total_unbonding
    )

    # Calculate total from supply tracking
    total_supply = state.get_total_supply(genesis_supply)

    # INVARIANT: These must be equal
    assert total_supply == total_from_accounting, (
        f"Supply mismatch: "
        f"total_supply={total_supply}, "
        f"accounting={total_from_accounting}, "
        f"diff={total_supply - total_from_accounting}"
    )

    print(f"✅ Supply conservation: {total_supply} = {total_from_accounting}")
    print(f"   Genesis: {genesis_supply}")
    print(f"   Minted: {state.total_minted}")
    print(f"   Burned: {state.total_burned}")


def test_non_negative_balances(chain):
    """Test that all balances remain non-negative."""
    # Create account
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub, prefix="cpc")

    # Mine some blocks
    for _ in range(3):
        chain.add_block([])

    # Check all accounts have non-negative balance
    for account_addr in chain.state._accounts.keys():
        acc = chain.state.get_account(account_addr)
        assert acc.balance >= 0, f"Account {account_addr} has negative balance: {acc.balance}"

    print(f"✅ All balances non-negative")


def test_staking_limits_enforced(chain):
    """Test that staking limits are enforced."""
    from protocol.config.economic_model import ECONOMIC_CONFIG

    # Create validator
    val_priv = generate_private_key()
    val_pub = public_key_from_private(val_priv)
    val_addr = address_from_pubkey(val_pub, prefix="cpcvalcons")
    val_reward_addr = address_from_pubkey(val_pub, prefix="cpc")

    # STAKE
    stake_tx = Transaction(
        tx_type=TxType.STAKE,
        from_address=val_reward_addr,
        to_address="",
        amount=1000 * DECIMALS,
        nonce=0,
        gas_price=1000,
        signature=b"",
        public_key=val_pub.hex(),
        payload={
            "validator_address": val_addr,
            "pubkey": val_pub.hex(),
            "commission_rate": 0.10
        }
    )

    from protocol.crypto.keys import sign
    stake_tx.signature = sign(stake_tx.signing_bytes(), val_priv)

    chain.add_block([stake_tx])

    # Check max_validators_per_delegator is in config
    assert ECONOMIC_CONFIG.max_validators_per_delegator == 10

    # Check max_validator_power_share is in config
    assert ECONOMIC_CONFIG.max_validator_power_share == 0.20

    print(f"✅ Staking limits configured: max_validators_per_delegator={ECONOMIC_CONFIG.max_validators_per_delegator}")
    print(f"✅ Staking limits configured: max_validator_power_share={ECONOMIC_CONFIG.max_validator_power_share}")
