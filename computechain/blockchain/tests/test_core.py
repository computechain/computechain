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

