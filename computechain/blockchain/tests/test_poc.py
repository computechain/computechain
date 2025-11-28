import pytest
import time
import tempfile
import shutil
import os
from computechain.blockchain.core.state import AccountState
from computechain.blockchain.storage.db import StorageDB
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.types.poc import ComputeResult
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.blockchain.core.accounts import Account

@pytest.fixture
def db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_poc.db")
    db = StorageDB(db_path)
    yield db
    shutil.rmtree(temp_dir)

def test_submit_result_valid(db):
    state = AccountState(db)
    
    # Sender
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    # Fund sender (for gas)
    state.set_account(Account(address=addr, balance=200_000_000))
    
    # Create Result
    res = ComputeResult(
        task_id="task_123",
        worker_address=addr,
        result_hash="cafe1234",
        proof="0xdeadbeef",
        nonce=42,
        signature=""
    )
    
    tx = Transaction(
        tx_type=TxType.SUBMIT_RESULT,
        from_address=addr,
        to_address=None,
        amount=0,
        nonce=0,
        pub_key=pub.hex(),
        payload=res.model_dump(),
        gas_limit=80000,
        gas_price=1000,
        fee=80000 * 1000
    )
    tx.sign(priv)
    
    assert state.apply_transaction(tx) is True
    
    # Nonce should increase
    assert state.get_account(addr).nonce == 1

def test_submit_result_invalid_worker(db):
    state = AccountState(db)
    
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    state.set_account(Account(address=addr, balance=200_000_000))
    
    res = ComputeResult(
        task_id="task_123",
        worker_address="cpc1otheruser...", # Mismatch
        result_hash="cafe1234",
        proof="0xdeadbeef",
        nonce=42,
        signature=""
    )
    
    tx = Transaction(
        tx_type=TxType.SUBMIT_RESULT,
        from_address=addr,
        pub_key=pub.hex(),
        amount=0,
        nonce=0,
        payload=res.model_dump(),
        gas_limit=80000,
        gas_price=1000,
        fee=80000 * 1000
    )
    tx.sign(priv)
    
    with pytest.raises(ValueError, match="Worker address mismatch"):
        state.apply_transaction(tx)

def test_submit_result_bad_payload(db):
    state = AccountState(db)
    
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub)
    
    state.set_account(Account(address=addr, balance=200_000_000))
    
    tx = Transaction(
        tx_type=TxType.SUBMIT_RESULT,
        from_address=addr,
        pub_key=pub.hex(),
        amount=0,
        nonce=0,
        payload={"junk": "data"}, # Invalid ComputeResult
        gas_limit=80000,
        gas_price=1000,
        fee=80000 * 1000
    )
    tx.sign(priv)
    
    with pytest.raises(ValueError, match="Invalid ComputeResult"):
        state.apply_transaction(tx)
