import sys
import os
import tempfile
import shutil
import pytest
from computechain.blockchain.core.state import AccountState
from computechain.blockchain.storage.db import StorageDB
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private, sign
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.blockchain.core.accounts import Account

# Setup temporary DB
@pytest.fixture
def db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_chain.db")
    db = StorageDB(db_path)
    yield db
    shutil.rmtree(temp_dir)

def test_tx_signature_verification(db):
    state = AccountState(db)
    
    # Create Sender
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    pub_hex = pub.hex()
    
    # Fund sender
    state.set_account(Account(address=addr, balance=100_000_000, nonce=0))
    
    # 1. Happy Path
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address="cpc1recipient...",
        amount=100,
        nonce=0,
        pub_key=pub_hex,
        gas_limit=21000,
        gas_price=1000,
        fee=21000 * 1000
    )
    tx.sign(priv)
    
    assert state.apply_transaction(tx) is True
    
    # Check nonce increased
    updated_sender = state.get_account(addr)
    assert updated_sender.nonce == 1
    fee = 21000 * 1000
    assert updated_sender.balance == 100_000_000 - 100 - fee

def test_tx_missing_pubkey(db):
    state = AccountState(db)
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    state.set_account(Account(address=addr, balance=100_000_000))
    
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address="cpc1recipient...",
        amount=100,
        nonce=0,
        gas_limit=21000,
        gas_price=1000
        # No pub_key
    )
    tx.sign(priv)
    
    with pytest.raises(ValueError, match="Missing signature or pub_key"):
        state.apply_transaction(tx)

def test_tx_invalid_signature(db):
    state = AccountState(db)
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    state.set_account(Account(address=addr, balance=100_000_000))
    
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address="cpc1recipient...",
        amount=100,
        nonce=0,
        pub_key=pub.hex(),
        gas_limit=21000,
        gas_price=1000
    )
    # Sign with WRONG key
    wrong_priv = generate_private_key()
    tx.sign(wrong_priv)
    
    with pytest.raises(ValueError, match="Invalid signature"):
        state.apply_transaction(tx)

def test_tx_tampered_amount(db):
    state = AccountState(db)
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    state.set_account(Account(address=addr, balance=100_000_000))
    
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr,
        to_address="cpc1recipient...",
        amount=100,
        nonce=0,
        pub_key=pub.hex(),
        gas_limit=21000,
        gas_price=1000
    )
    tx.sign(priv)
    
    # Tamper amount AFTER signing
    tx.amount = 500 
    # Note: state.apply_transaction recalculates hash from fields. 
    # So hash will change, and signature will not match the new hash.
    
    with pytest.raises(ValueError, match="Invalid signature"):
        state.apply_transaction(tx)

def test_tx_wrong_pubkey(db):
    state = AccountState(db)
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    # Another person's key
    priv2 = generate_private_key()
    pub2 = public_key_from_private(priv2)
    
    state.set_account(Account(address=addr, balance=100_000_000))
    
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr, # Claim to be addr
        to_address="cpc1recipient...",
        amount=100,
        nonce=0,
        pub_key=pub2.hex(), # But provide pub2
        gas_limit=21000,
        gas_price=1000
    )
    # If we sign with priv2, signature matches pub2.
    # But pub2 does not derive to addr.
    tx.sign(priv2)
    
    with pytest.raises(ValueError, match="pub_key mismatch"):
        state.apply_transaction(tx)
