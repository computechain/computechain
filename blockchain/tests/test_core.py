import pytest
import os
import shutil
import time
from computechain.blockchain.core.chain import Blockchain
from computechain.blockchain.core.state import AccountState
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey

TEST_DB_DIR = "./test_db"

@pytest.fixture
def clean_chain():
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)
    os.makedirs(TEST_DB_DIR)
    
    db_path = os.path.join(TEST_DB_DIR, "chain.db")
    chain = Blockchain(db_path)
    yield chain
    
    chain.db.conn.close()
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)

def test_account_state_logic(clean_chain):
    chain = clean_chain
    state = chain.state
    
    # Setup Accounts
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))
    
    priv2 = generate_private_key()
    addr2 = address_from_pubkey(public_key_from_private(priv2))
    
    # 1. Initial Balance 0
    assert state.get_account(addr1).balance == 0
    
    # 2. Set Balance
    acc1 = state.get_account(addr1)
    acc1.balance = 100_000_000  # High balance to cover gas
    state.set_account(acc1)
    assert state.get_account(addr1).balance == 100_000_000
    
    # 3. Transfer success
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=100,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000 * 1000,
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx.sign(priv1)
    
    state.apply_transaction(tx)
    
    fee = 21000 * 1000
    assert state.get_account(addr1).balance == 100_000_000 - 100 - fee
    assert state.get_account(addr2).balance == 100
    assert state.get_account(addr1).nonce == 1
    
    # 4. Insufficient Balance
    tx2 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=200_000_000, # > balance
        nonce=1,
        gas_price=1000,
        gas_limit=21000,
        fee=21000 * 1000,
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx2.sign(priv1)
    
    with pytest.raises(ValueError, match="Insufficient balance"):
        state.apply_transaction(tx2)
        
    # 5. Invalid Nonce
    tx3 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=10,
        nonce=5, # Expected 1
        gas_price=1000,
        gas_limit=21000,
        fee=21000 * 1000,
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx3.sign(priv1)
    
    with pytest.raises(ValueError, match="Invalid nonce"):
        state.apply_transaction(tx3)

def test_stake_unstake_flow(clean_chain):
    """Test complete stake/unstake lifecycle."""
    chain = clean_chain
    state = chain.state

    # Generate key for validator
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)

    # Give initial balance
    acc = state.get_account(addr)
    acc.balance = 200_000_000  # 200 CPC
    state.set_account(acc)

    # 1. Stake 100 CPC
    stake_amount = 100_000_000  # 100 CPC
    fee = 40_000 * 1000  # base_gas * gas_price (STAKE uses 40k gas)

    tx_stake = Transaction(
        tx_type=TxType.STAKE,
        from_address=addr,
        to_address=None,
        amount=stake_amount,
        nonce=0,
        gas_price=1000,
        gas_limit=100000,
        fee=fee,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_stake.sign(priv)
    state.apply_transaction(tx_stake)

    # Check balance decreased by amount + fee
    expected_balance = 200_000_000 - stake_amount - fee
    assert state.get_account(addr).balance == expected_balance
    assert state.get_account(addr).nonce == 1

    # Check validator created
    val_addr = address_from_pubkey(pub, prefix="cpcvalcons")
    val = state.get_validator(val_addr)
    assert val is not None
    assert val.power == stake_amount
    assert val.is_active == False  # Not active until epoch transition

    # 2. Unstake 50 CPC
    unstake_amount = 50_000_000  # 50 CPC
    fee2 = 40_000 * 1000  # base_gas * gas_price (UNSTAKE uses 40k gas)

    tx_unstake = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=addr,
        to_address=None,
        amount=unstake_amount,
        nonce=1,
        gas_price=1000,
        gas_limit=100000,
        fee=fee2,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_unstake.sign(priv)
    state.apply_transaction(tx_unstake)

    # Check balance increased by unstake_amount (minus fee)
    expected_balance = expected_balance - fee2 + unstake_amount
    assert state.get_account(addr).balance == expected_balance
    assert state.get_account(addr).nonce == 2

    # Check validator power decreased
    val = state.get_validator(val_addr)
    assert val.power == stake_amount - unstake_amount
    assert val.is_active == False

def test_unstake_nonexistent_validator(clean_chain):
    """Test unstaking from non-existent validator."""
    chain = clean_chain
    state = chain.state

    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)

    # Give balance
    acc = state.get_account(addr)
    acc.balance = 100_000_000
    state.set_account(acc)

    # Try to unstake without staking first
    tx = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=addr,
        to_address=None,
        amount=10_000_000,
        nonce=0,
        gas_price=1000,
        gas_limit=100000,
        fee=100000 * 1000,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx.sign(priv)

    with pytest.raises(ValueError, match="Validator.*not found"):
        state.apply_transaction(tx)

def test_unstake_insufficient_stake(clean_chain):
    """Test unstaking more than staked."""
    chain = clean_chain
    state = chain.state

    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)

    # Give balance and stake
    acc = state.get_account(addr)
    acc.balance = 200_000_000
    state.set_account(acc)

    # Stake 50 CPC
    stake_amount = 50_000_000
    tx_stake = Transaction(
        tx_type=TxType.STAKE,
        from_address=addr,
        to_address=None,
        amount=stake_amount,
        nonce=0,
        gas_price=1000,
        gas_limit=100000,
        fee=100000 * 1000,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_stake.sign(priv)
    state.apply_transaction(tx_stake)

    # Try to unstake 100 CPC (more than staked)
    tx_unstake = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=addr,
        to_address=None,
        amount=100_000_000,
        nonce=1,
        gas_price=1000,
        gas_limit=100000,
        fee=100000 * 1000,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_unstake.sign(priv)

    with pytest.raises(ValueError, match="Insufficient stake"):
        state.apply_transaction(tx_unstake)

def test_unstake_full_deactivates_validator(clean_chain):
    """Test that unstaking all power deactivates validator."""
    chain = clean_chain
    state = chain.state

    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)

    # Give balance and stake
    acc = state.get_account(addr)
    acc.balance = 200_000_000
    state.set_account(acc)

    # Stake 50 CPC
    stake_amount = 50_000_000
    tx_stake = Transaction(
        tx_type=TxType.STAKE,
        from_address=addr,
        to_address=None,
        amount=stake_amount,
        nonce=0,
        gas_price=1000,
        gas_limit=100000,
        fee=100000 * 1000,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_stake.sign(priv)
    state.apply_transaction(tx_stake)

    val_addr = address_from_pubkey(pub, prefix="cpcvalcons")
    val = state.get_validator(val_addr)
    assert val.is_active == False

    # Unstake full amount
    tx_unstake = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=addr,
        to_address=None,
        amount=stake_amount,
        nonce=1,
        gas_price=1000,
        gas_limit=100000,
        fee=100000 * 1000,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_unstake.sign(priv)
    state.apply_transaction(tx_unstake)

    # Validator should have 0 power and be deactivated
    val = state.get_validator(val_addr)
    assert val.power == 0
    assert val.is_active == False

def test_unstake_with_penalty_when_jailed(clean_chain):
    """Test that unstaking while jailed applies penalty."""
    chain = clean_chain
    state = chain.state

    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)

    # Give balance and stake
    acc = state.get_account(addr)
    acc.balance = 200_000_000
    state.set_account(acc)

    # Stake 100 CPC
    stake_amount = 100_000_000
    tx_stake = Transaction(
        tx_type=TxType.STAKE,
        from_address=addr,
        to_address=None,
        amount=stake_amount,
        nonce=0,
        gas_price=1000,
        gas_limit=100000,
        fee=40_000 * 1000,  # base_gas * gas_price (STAKE uses 40k gas)
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_stake.sign(priv)
    state.apply_transaction(tx_stake)

    # Manually jail the validator
    val_addr = address_from_pubkey(pub, prefix="cpcvalcons")
    val = state.get_validator(val_addr)
    val.jailed_until_height = 1000  # Jail until block 1000
    state.set_validator(val)

    # Try to unstake while jailed - should apply 10% penalty
    unstake_amount = 50_000_000  # 50 CPC
    fee2 = 40_000 * 1000  # base_gas * gas_price (UNSTAKE uses 40k gas)
    balance_before = state.get_account(addr).balance

    tx_unstake = Transaction(
        tx_type=TxType.UNSTAKE,
        from_address=addr,
        to_address=None,
        amount=unstake_amount,
        nonce=1,
        gas_price=1000,
        gas_limit=100000,
        fee=fee2,
        timestamp=int(time.time()),
        pub_key=pub.hex(),
        payload={"pub_key": pub.hex()}
    )
    tx_unstake.sign(priv)
    state.apply_transaction(tx_unstake)

    # Check penalty applied (10% of unstake_amount)
    penalty = int(unstake_amount * 0.10)
    return_amount = unstake_amount - penalty
    expected_balance = balance_before - fee2 + return_amount

    assert state.get_account(addr).balance == expected_balance
    assert state.get_account(addr).nonce == 2

    # Validator power should decrease by full unstake_amount (not just return_amount)
    val = state.get_validator(val_addr)
    assert val.power == stake_amount - unstake_amount

