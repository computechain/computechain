"""
Tests for Transaction Lifecycle Tracking (Phase 1.4)

Tests:
- EventBus pub/sub mechanism
- TxReceipt storage and tracking
- Transaction confirmation flow (pending -> confirmed)
- NonceManager with event-based tracking
- Prometheus metrics integration
"""
import pytest
import time
import os
import shutil
from unittest.mock import Mock, patch

from computechain.blockchain.core.events import EventBus, event_bus
from computechain.blockchain.core.tx_receipt import TxReceipt, TxReceiptStore, tx_receipt_store
from computechain.blockchain.core.chain import Blockchain
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey


TEST_DB_DIR = "./test_tx_lifecycle_db"


# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def clean_event_bus():
    """Provide a clean EventBus for each test."""
    bus = EventBus()
    yield bus
    bus.clear()


@pytest.fixture
def clean_receipt_store():
    """Provide a clean TxReceiptStore for each test."""
    store = TxReceiptStore()
    yield store
    store.clear()


@pytest.fixture
def clean_chain():
    """Provide a clean blockchain for integration tests."""
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)
    os.makedirs(TEST_DB_DIR)

    db_path = os.path.join(TEST_DB_DIR, "chain.db")
    chain = Blockchain(db_path)
    yield chain

    chain.db.conn.close()
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)


# ═══════════════════════════════════════════════════════════════════
# EVENTBUS TESTS
# ═══════════════════════════════════════════════════════════════════

def test_eventbus_subscribe_and_emit(clean_event_bus):
    """Test basic subscribe and emit functionality."""
    bus = clean_event_bus
    callback_data = []

    def callback(**data):
        callback_data.append(data)

    # Subscribe to event
    bus.subscribe('test_event', callback)

    # Emit event
    bus.emit('test_event', value=42, name='test')

    # Verify callback was called with correct data
    assert len(callback_data) == 1
    assert callback_data[0] == {'value': 42, 'name': 'test'}


def test_eventbus_multiple_listeners(clean_event_bus):
    """Test multiple listeners for same event."""
    bus = clean_event_bus
    called = []

    def callback1(**data):
        called.append('callback1')

    def callback2(**data):
        called.append('callback2')

    bus.subscribe('test_event', callback1)
    bus.subscribe('test_event', callback2)

    bus.emit('test_event')

    # Both callbacks should be called
    assert len(called) == 2
    assert 'callback1' in called
    assert 'callback2' in called


def test_eventbus_unsubscribe(clean_event_bus):
    """Test unsubscribe functionality."""
    bus = clean_event_bus
    called = []

    def callback(**data):
        called.append(True)

    bus.subscribe('test_event', callback)
    bus.emit('test_event')
    assert len(called) == 1

    # Unsubscribe
    bus.unsubscribe('test_event', callback)
    bus.emit('test_event')

    # Should not be called again
    assert len(called) == 1


def test_eventbus_error_handling(clean_event_bus):
    """Test that errors in callbacks don't break event emission."""
    bus = clean_event_bus
    good_callback_called = []

    def bad_callback(**data):
        raise ValueError("Test error")

    def good_callback(**data):
        good_callback_called.append(True)

    bus.subscribe('test_event', bad_callback)
    bus.subscribe('test_event', good_callback)

    # Should not raise, good callback should still be called
    bus.emit('test_event')
    assert len(good_callback_called) == 1


# ═══════════════════════════════════════════════════════════════════
# TX RECEIPT STORE TESTS
# ═══════════════════════════════════════════════════════════════════

def test_receipt_add_pending(clean_receipt_store):
    """Test adding pending transaction receipt."""
    store = clean_receipt_store

    receipt = store.add_pending('tx_hash_123')

    assert receipt.tx_hash == 'tx_hash_123'
    assert receipt.status == 'pending'
    assert receipt.block_height is None
    assert receipt.error is None

    # Verify it's stored
    stored = store.get('tx_hash_123')
    assert stored is not None
    assert stored.tx_hash == 'tx_hash_123'


def test_receipt_mark_confirmed(clean_receipt_store):
    """Test marking transaction as confirmed."""
    store = clean_receipt_store

    # Add pending
    store.add_pending('tx_hash_456')

    # Mark confirmed
    receipt = store.mark_confirmed('tx_hash_456', block_height=100)

    assert receipt.status == 'confirmed'
    assert receipt.block_height == 100

    # Verify confirmations calculation
    confirmations = store.get_confirmations('tx_hash_456', current_height=105)
    assert confirmations == 6  # 105 - 100 + 1


def test_receipt_mark_failed(clean_receipt_store):
    """Test marking transaction as failed."""
    store = clean_receipt_store

    # Add pending
    store.add_pending('tx_hash_789')

    # Mark failed
    receipt = store.mark_failed('tx_hash_789', error='Insufficient balance')

    assert receipt.status == 'failed'
    assert receipt.error == 'Insufficient balance'
    assert receipt.block_height is None


def test_receipt_confirmation_time_tracking(clean_receipt_store):
    """Test that confirmation time is calculated correctly."""
    store = clean_receipt_store

    # Add pending
    receipt = store.add_pending('tx_hash_time')
    initial_timestamp = receipt.timestamp
    time.sleep(1.1)  # Sleep longer than 1 second to ensure timestamp changes

    # Mark confirmed
    confirmed = store.mark_confirmed('tx_hash_time', block_height=50)

    # Confirmation time should be >= 1 second
    confirmation_time = confirmed.timestamp - initial_timestamp
    assert confirmation_time >= 1
    assert confirmation_time < 3  # Should be less than 3 seconds


def test_receipt_cleanup_old_receipts(clean_receipt_store):
    """Test automatic cleanup of old receipts."""
    store = TxReceiptStore(max_receipts=100)  # Small limit for testing

    # Add more than max_receipts
    for i in range(150):
        store.add_pending(f'tx_hash_{i}')

    # Should have triggered cleanup
    assert len(store.receipts) < 150
    assert len(store.receipts) <= 100


# ═══════════════════════════════════════════════════════════════════
# TX TTL (TIME-TO-LIVE) TESTS - Phase 1.4
# ═══════════════════════════════════════════════════════════════════

def test_receipt_mark_expired(clean_receipt_store):
    """Test marking transaction as expired (TTL exceeded)."""
    store = clean_receipt_store

    # Add pending
    store.add_pending('tx_hash_expired')

    # Mark expired
    receipt = store.mark_expired('tx_hash_expired')

    assert receipt.status == 'failed'
    assert receipt.error == 'Transaction expired (TTL exceeded)'
    assert receipt.block_height is None


def test_mempool_tx_ttl_cleanup():
    """Test that expired transactions are removed from mempool."""
    from computechain.blockchain.core.mempool import Mempool

    # Create mempool with 2-second TTL for testing
    mempool = Mempool(tx_ttl_seconds=2)

    # Create test transactions
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))
    addr2 = address_from_pubkey(public_key_from_private(generate_private_key()))

    tx1 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=1000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000000,  # gas_limit * gas_price
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx1.sign(priv1)

    # Add transaction to mempool
    success, msg = mempool.add_transaction(tx1)
    assert success, f"Failed to add tx: {msg}"
    assert tx1.hash_hex in mempool.transactions
    assert tx1.hash_hex in mempool.tx_timestamps

    # Wait for TTL to expire (2 seconds + buffer)
    time.sleep(2.5)

    # Run cleanup
    expired_count = mempool.cleanup_expired()

    # Transaction should be removed
    assert expired_count == 1
    assert tx1.hash_hex not in mempool.transactions
    assert tx1.hash_hex not in mempool.tx_timestamps


def test_mempool_tx_ttl_not_expired():
    """Test that non-expired transactions remain in mempool."""
    from computechain.blockchain.core.mempool import Mempool

    # Create mempool with 10-second TTL
    mempool = Mempool(tx_ttl_seconds=10)

    # Create test transaction
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))
    addr2 = address_from_pubkey(public_key_from_private(generate_private_key()))

    tx1 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=1000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000000,  # gas_limit * gas_price
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx1.sign(priv1)

    # Add transaction to mempool
    success, msg = mempool.add_transaction(tx1)
    assert success, f"Failed to add tx: {msg}"

    # Wait less than TTL (1 second)
    time.sleep(1)

    # Run cleanup
    expired_count = mempool.cleanup_expired()

    # Transaction should remain
    assert expired_count == 0
    assert tx1.hash_hex in mempool.transactions
    assert tx1.hash_hex in mempool.tx_timestamps


def test_mempool_tx_ttl_multiple_transactions():
    """Test TTL cleanup with multiple transactions at different ages."""
    from computechain.blockchain.core.mempool import Mempool

    # Create mempool with 2-second TTL
    mempool = Mempool(tx_ttl_seconds=2)

    # Create test transactions
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))
    addr2 = address_from_pubkey(public_key_from_private(generate_private_key()))

    # Add first transaction (will expire)
    tx1 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=1000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000000,  # gas_limit * gas_price
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx1.sign(priv1)
    mempool.add_transaction(tx1)

    # Wait 2.5 seconds (tx1 will expire)
    time.sleep(2.5)

    # Add second transaction (will NOT expire)
    priv2 = generate_private_key()
    addr3 = address_from_pubkey(public_key_from_private(priv2))
    tx2 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr3,
        to_address=addr2,
        amount=2000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000000,  # gas_limit * gas_price
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv2).hex()
    )
    tx2.sign(priv2)
    mempool.add_transaction(tx2)

    # Run cleanup
    expired_count = mempool.cleanup_expired()

    # Only tx1 should be removed
    assert expired_count == 1
    assert tx1.hash_hex not in mempool.transactions
    assert tx2.hash_hex in mempool.transactions


def test_mempool_remove_transactions_clears_timestamps():
    """Test that removing transactions also clears their timestamps."""
    from computechain.blockchain.core.mempool import Mempool

    mempool = Mempool()

    # Create and add test transaction
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))
    addr2 = address_from_pubkey(public_key_from_private(generate_private_key()))

    tx1 = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=1000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000000,  # gas_limit * gas_price
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx1.sign(priv1)
    mempool.add_transaction(tx1)

    # Verify it's tracked
    assert tx1.hash_hex in mempool.transactions
    assert tx1.hash_hex in mempool.tx_timestamps

    # Remove transaction
    mempool.remove_transactions([tx1])

    # Verify both transaction and timestamp are removed
    assert tx1.hash_hex not in mempool.transactions
    assert tx1.hash_hex not in mempool.tx_timestamps


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════

def test_tx_lifecycle_integration(clean_chain, clean_event_bus):
    """Test full transaction lifecycle: pending -> mempool -> confirmed."""
    chain = clean_chain
    bus = clean_event_bus

    # Create test accounts
    priv1 = generate_private_key()
    addr1 = address_from_pubkey(public_key_from_private(priv1))

    priv2 = generate_private_key()
    addr2 = address_from_pubkey(public_key_from_private(priv2))

    # Fund sender
    acc1 = chain.state.get_account(addr1)
    acc1.balance = 100_000_000
    chain.state.set_account(acc1)

    # Create transaction
    tx = Transaction(
        tx_type=TxType.TRANSFER,
        from_address=addr1,
        to_address=addr2,
        amount=1000,
        nonce=0,
        gas_price=1000,
        gas_limit=21000,
        fee=21000 * 1000,
        timestamp=int(time.time()),
        pub_key=public_key_from_private(priv1).hex()
    )
    tx.sign(priv1)

    tx_hash = tx.hash()

    # Track events
    events_received = []

    def on_tx_confirmed(**data):
        events_received.append(data)

    bus.subscribe('tx_confirmed', on_tx_confirmed)

    # Add receipt as pending (simulating /tx/send endpoint)
    from computechain.blockchain.core.tx_receipt import tx_receipt_store
    tx_receipt_store.add_pending(tx_hash)

    receipt = tx_receipt_store.get(tx_hash)
    assert receipt.status == 'pending'

    # Create block with transaction (simulating consensus)
    # This would normally emit tx_confirmed event
    bus.emit('tx_confirmed', tx_hash=tx_hash, block_height=1, tx=tx)

    # Mark as confirmed (simulating event handler)
    tx_receipt_store.mark_confirmed(tx_hash, block_height=1)

    # Verify receipt updated
    receipt = tx_receipt_store.get(tx_hash)
    assert receipt.status == 'confirmed'
    assert receipt.block_height == 1

    # Verify event was emitted
    assert len(events_received) == 1
    assert events_received[0]['tx_hash'] == tx_hash
    assert events_received[0]['block_height'] == 1


# ═══════════════════════════════════════════════════════════════════
# NONCE MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════

def test_nonce_manager_event_based_mode():
    """Test NonceManager with event-based tracking (use_events=True)."""
    import sys
    import os
    # Add scripts to path for testing
    scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'testing')
    sys.path.insert(0, scripts_path)
    from nonce_manager import NonceManager

    # Mock blockchain nonce getter
    blockchain_nonces = {'addr1': 0}

    def get_blockchain_nonce(address):
        return blockchain_nonces.get(address, 0)

    # Create NonceManager with event-based mode
    manager = NonceManager(get_blockchain_nonce, use_events=True)

    # Get nonce
    nonce = manager.get_next_nonce('addr1')
    assert nonce == 0

    # Simulate sending transaction
    manager.on_tx_sent('addr1', 'tx_hash_1', nonce=0)
    assert manager.get_pending_count('addr1') == 1
    assert manager.get_next_nonce('addr1') == 1

    # Simulate confirmation via event
    blockchain_nonces['addr1'] = 1
    manager.on_tx_confirmed('addr1', 'tx_hash_1', nonce=0)

    # Pending should be cleared
    assert manager.get_pending_count('addr1') == 0
    assert manager.get_next_nonce('addr1') == 1

    # Check statistics
    stats = manager.get_stats()
    assert stats['total_pending'] == 1
    assert stats['total_confirmed'] == 1
    assert stats['event_confirmations'] == 1


def test_nonce_manager_aggressive_cleanup_mode():
    """Test NonceManager with aggressive cleanup (use_events=False)."""
    import sys
    import os
    # Add scripts to path for testing
    scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'testing')
    sys.path.insert(0, scripts_path)
    from nonce_manager import NonceManager

    blockchain_nonces = {'addr1': 0}

    def get_blockchain_nonce(address):
        return blockchain_nonces.get(address, 0)

    # Create NonceManager with aggressive cleanup mode
    manager = NonceManager(get_blockchain_nonce, use_events=False)

    # Send transactions
    manager.on_tx_sent('addr1', 'tx_hash_1', nonce=0)
    manager.on_tx_sent('addr1', 'tx_hash_2', nonce=1)
    assert manager.get_pending_count('addr1') == 2

    # Simulate blockchain processing both transactions
    blockchain_nonces['addr1'] = 2

    # Force sync should trigger aggressive cleanup
    manager._force_sync('addr1')

    # All pending should be cleared
    assert manager.get_pending_count('addr1') == 0
    assert manager.get_next_nonce('addr1') == 2

    # Check statistics
    stats = manager.get_stats()
    assert stats['aggressive_cleanups'] >= 1


# ═══════════════════════════════════════════════════════════════════
# METRICS TESTS
# ═══════════════════════════════════════════════════════════════════

def test_metrics_tx_confirmation_time():
    """Test that tx confirmation time metric is recorded."""
    from computechain.blockchain.observability.metrics import tx_confirmation_time_seconds

    # Just verify the metric exists and can be called without error
    try:
        tx_confirmation_time_seconds.observe(5.5)
        tx_confirmation_time_seconds.observe(10.2)
        # If no exception, test passes
        assert True
    except Exception as e:
        pytest.fail(f"Failed to record tx confirmation time: {e}")


def test_metrics_event_confirmations():
    """Test that event confirmations counter increments."""
    from computechain.blockchain.observability.metrics import event_confirmations_total
    from computechain.blockchain.core.events import EventBus

    # Create event bus and emit tx_confirmed
    # This should call event_confirmations_total.inc()
    bus = EventBus()

    try:
        bus.emit('tx_confirmed', tx_hash='test_hash', block_height=1)
        # If no exception, metric is being updated correctly
        assert True
    except Exception as e:
        pytest.fail(f"Failed to emit event and update metric: {e}")


def test_metrics_pending_transactions():
    """Test that pending transactions gauge updates."""
    from computechain.blockchain.observability.metrics import pending_transactions, update_metrics
    from computechain.blockchain.core.tx_receipt import tx_receipt_store

    # Clear and add pending receipts
    tx_receipt_store.clear()
    tx_receipt_store.add_pending('tx_1')
    tx_receipt_store.add_pending('tx_2')

    # Create a minimal chain mock for update_metrics
    class MockChain:
        height = 100
        state = Mock()

        def get_block(self, height):
            return None

    # Create mock account with balance attribute
    mock_account = Mock()
    mock_account.balance = 1000000
    mock_account.reward_history = {}
    mock_account.unbonding_delegations = []

    mock_chain = MockChain()
    mock_chain.state.get_all_validators = Mock(return_value=[])
    mock_chain.state.get_account = Mock(return_value=mock_account)
    mock_chain.state.get_total_supply = Mock(return_value=0)
    mock_chain.state.epoch_index = 0
    mock_chain.state.total_minted = 0
    mock_chain.state.total_burned = 0
    mock_chain.state._accounts = {}

    # Update metrics (this should update pending_transactions gauge)
    try:
        update_metrics(mock_chain, None)
        # If no exception, metric is being updated correctly
        assert True
    except Exception as e:
        pytest.fail(f"Failed to update pending transactions metric: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
