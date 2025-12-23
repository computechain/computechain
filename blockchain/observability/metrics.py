# MIT License
# Copyright (c) 2025 Hashborn

"""
Prometheus Metrics Exporter (Phase 1.3)

Exports blockchain metrics in Prometheus format.

Metrics:
- Block height, block time
- Transaction count, TPS
- Transaction lifecycle (confirmation time, pending count) (Phase 1.4)
- Validator count, uptime, performance
- Mempool size
- Economic metrics (total supply, burned, minted)
"""

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry
import time

# Create registry for metrics
metrics_registry = CollectorRegistry()

# ═══════════════════════════════════════════════════════════════════
# BLOCKCHAIN METRICS
# ═══════════════════════════════════════════════════════════════════

# Block metrics
block_height = Gauge(
    'computechain_block_height',
    'Current block height',
    registry=metrics_registry
)

block_time_seconds = Histogram(
    'computechain_block_time_seconds',
    'Time between blocks in seconds',
    buckets=[1, 5, 10, 15, 20, 30, 60],
    registry=metrics_registry
)

blocks_total = Counter(
    'computechain_blocks_total',
    'Total number of blocks produced',
    registry=metrics_registry
)

# Transaction metrics
transactions_total = Counter(
    'computechain_transactions_total',
    'Total number of transactions processed',
    ['tx_type'],
    registry=metrics_registry
)

transactions_per_block = Histogram(
    'computechain_transactions_per_block',
    'Number of transactions per block',
    buckets=[0, 1, 5, 10, 20, 50, 100],
    registry=metrics_registry
)

mempool_size = Gauge(
    'computechain_mempool_size',
    'Current mempool size',
    registry=metrics_registry
)

# Transaction lifecycle metrics (Phase 1.4)
tx_confirmation_time_seconds = Histogram(
    'computechain_tx_confirmation_time_seconds',
    'Time from transaction submission to confirmation',
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
    registry=metrics_registry
)

pending_transactions = Gauge(
    'computechain_pending_transactions',
    'Number of pending transactions',
    registry=metrics_registry
)

event_confirmations_total = Counter(
    'computechain_event_confirmations_total',
    'Total transaction confirmations via events',
    registry=metrics_registry
)

# ═══════════════════════════════════════════════════════════════════
# VALIDATOR METRICS
# ═══════════════════════════════════════════════════════════════════

validator_count_total = Gauge(
    'computechain_validator_count_total',
    'Total number of validators',
    registry=metrics_registry
)

validator_count_active = Gauge(
    'computechain_validator_count_active',
    'Number of active validators',
    registry=metrics_registry
)

validator_count_jailed = Gauge(
    'computechain_validator_count_jailed',
    'Number of jailed validators',
    registry=metrics_registry
)

validator_uptime_score = Gauge(
    'computechain_validator_uptime_score',
    'Validator uptime score',
    ['validator_address'],
    registry=metrics_registry
)

validator_performance_score = Gauge(
    'computechain_validator_performance_score',
    'Validator performance score',
    ['validator_address'],
    registry=metrics_registry
)

validator_power = Gauge(
    'computechain_validator_power',
    'Validator voting power',
    ['validator_address'],
    registry=metrics_registry
)

validator_missed_blocks = Counter(
    'computechain_validator_missed_blocks_total',
    'Total missed blocks per validator',
    ['validator_address'],
    registry=metrics_registry
)

# ═══════════════════════════════════════════════════════════════════
# ECONOMIC METRICS
# ═══════════════════════════════════════════════════════════════════

total_supply = Gauge(
    'computechain_total_supply',
    'Total token supply (genesis + minted - burned)',
    registry=metrics_registry
)

total_minted = Counter(
    'computechain_total_minted',
    'Total tokens minted (block rewards)',
    registry=metrics_registry
)

total_burned = Counter(
    'computechain_total_burned',
    'Total tokens burned (slashing, penalties, dust)',
    registry=metrics_registry
)

total_staked = Gauge(
    'computechain_total_staked',
    'Total tokens staked by validators',
    registry=metrics_registry
)

total_delegated = Gauge(
    'computechain_total_delegated',
    'Total tokens delegated',
    registry=metrics_registry
)

treasury_balance = Gauge(
    'computechain_treasury_balance',
    'Treasury account balance',
    registry=metrics_registry
)

# ═══════════════════════════════════════════════════════════════════
# NETWORK METRICS
# ═══════════════════════════════════════════════════════════════════

epoch_index = Gauge(
    'computechain_epoch_index',
    'Current epoch index',
    registry=metrics_registry
)

network_id = Gauge(
    'computechain_network_id',
    'Network ID (1=devnet, 2=testnet, 3=mainnet)',
    ['network'],
    registry=metrics_registry
)

accounts_total = Gauge(
    'computechain_accounts_total',
    'Total number of accounts in the network',
    registry=metrics_registry
)


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

# Track last block time for block_time calculation
_last_block_timestamp = None


def update_block_metrics(chain):
    """
    Update block-related metrics (counters/histograms).
    Should only be called when a new block is actually added.

    Args:
        chain: Blockchain instance
    """
    import logging
    logger = logging.getLogger(__name__)

    global _last_block_timestamp

    # Increment block counter
    blocks_total.inc()

    # Block time histogram
    current_time = time.time()
    if _last_block_timestamp is not None:
        block_time_seconds.observe(current_time - _last_block_timestamp)
    _last_block_timestamp = current_time


def update_metrics(chain, mempool_instance=None):
    """
    Update all Prometheus metrics from blockchain state.
    This is called both when blocks are added AND when metrics are scraped.
    Only updates Gauges, not Counters/Histograms.

    Args:
        chain: Blockchain instance
        mempool_instance: Optional mempool instance
    """
    from computechain.protocol.config.economic_model import TREASURY_ADDRESS
    from computechain.protocol.config.params import CURRENT_NETWORK

    state = chain.state

    # Block metrics (Gauges only)
    block_height.set(chain.height)

    # Mempool
    if mempool_instance:
        mempool_size.set(mempool_instance.size())

    # Transaction lifecycle metrics (Phase 1.4)
    try:
        from computechain.blockchain.core.tx_receipt import tx_receipt_store
        pending_count = sum(1 for receipt in tx_receipt_store.receipts.values()
                          if receipt.status == 'pending')
        pending_transactions.set(pending_count)
    except Exception as e:
        # If receipt store not available, set to 0
        pending_transactions.set(0)

    # Validator metrics
    validators = state.get_all_validators()
    validator_count_total.set(len(validators))

    active_count = sum(1 for v in validators if v.is_active)
    validator_count_active.set(active_count)

    jailed_count = sum(1 for v in validators if v.jailed_until_height > chain.height)
    validator_count_jailed.set(jailed_count)

    # Per-validator metrics
    for val in validators:
        validator_uptime_score.labels(validator_address=val.address).set(val.uptime_score)
        validator_performance_score.labels(validator_address=val.address).set(val.performance_score)
        validator_power.labels(validator_address=val.address).set(val.power)

    # Economic metrics
    total_supply.set(state.get_total_supply(CURRENT_NETWORK.genesis_premine))

    # Note: total_minted and total_burned are Counters, updated when minting/burning happens
    # Here we just sync if needed
    if hasattr(state, 'total_minted'):
        total_minted._value.set(state.total_minted)
    if hasattr(state, 'total_burned'):
        total_burned._value.set(state.total_burned)

    # Staking metrics
    total_staked_amount = sum(v.self_stake for v in validators)
    total_staked.set(total_staked_amount)

    total_delegated_amount = sum(v.total_delegated for v in validators)
    total_delegated.set(total_delegated_amount)

    # Treasury
    treasury_acc = state.get_account(TREASURY_ADDRESS)
    treasury_balance.set(treasury_acc.balance)

    # Network info
    epoch_index.set(state.epoch_index)

    # Network ID (for labels)
    network_map = {"devnet": 1, "testnet": 2, "mainnet": 3}
    network_id.labels(network=CURRENT_NETWORK.network_id).set(
        network_map.get(CURRENT_NETWORK.network_id, 0)
    )

    # Account count
    try:
        # Count accounts with non-zero balance from cache (rough estimate)
        account_count = len([acc for acc in state._accounts.values() if acc.balance > 0])
        accounts_total.set(account_count)
    except Exception as e:
        # If fails, set to 0
        accounts_total.set(0)


def update_transaction_metrics(tx):
    """
    Update transaction metrics.

    Args:
        tx: Transaction object
    """
    transactions_total.labels(tx_type=tx.tx_type.name).inc()


def update_block_transaction_count(tx_count):
    """
    Update transactions per block histogram.

    Args:
        tx_count: Number of transactions in block
    """
    transactions_per_block.observe(tx_count)
