# MIT License
# Copyright (c) 2025 Hashborn

from typing import Dict, Any
from ..types.common import TxType

# Global Constants
DENOM = "cpc"
DECIMALS = 18

# Base Gas Costs
GAS_PER_TYPE = {
    TxType.TRANSFER:         21_000,
    TxType.STAKE:            40_000,
    TxType.UNSTAKE:          40_000,
    TxType.SUBMIT_RESULT:    80_000,
    TxType.UPDATE_VALIDATOR: 30_000,   # Phase 1: Metadata update
    TxType.DELEGATE:         35_000,   # Phase 2: Delegation
    TxType.UNDELEGATE:       35_000,   # Phase 2: Undelegation
    TxType.UNJAIL:           50_000,   # Phase 3: Unjail (expensive on purpose)
}

class NetworkConfig:
    def __init__(self,
                 network_id: str,
                 chain_id: str,
                 block_time_sec: int,
                 min_gas_price: int,
                 block_gas_limit: int,
                 max_tx_per_block: int,
                 genesis_premine: int,
                 bech32_prefix_acc: str = "cpc",
                 bech32_prefix_val: str = "cpcvaloper",
                 bech32_prefix_cons: str = "cpcvalcons",
                 version: int = 1,
                 # Epoch params
                 epoch_length_blocks: int = 10,
                 min_validator_stake: int = 1000,
                 max_validators: int = 5,
                 # Validator performance params (Phase 0)
                 min_uptime_score: float = 0.75,
                 max_missed_blocks_sequential: int = 10,
                 jail_duration_blocks: int = 100,
                 slashing_penalty_rate: float = 0.05,
                 ejection_threshold_jails: int = 3,
                 performance_lookback_epochs: int = 3,
                 # Unstaking params
                 unstaking_period_blocks: int = 100,
                 # Undelegation params (Phase 1.2)
                 undelegation_period_blocks: int = 100,  # 21 days on mainnet (181440 blocks @ 10s)
                 # Unjail params (Phase 3)
                 unjail_fee: int = 1000 * 10**18,  # 1000 CPC to unjail early
                 # Delegation params (Phase 2)
                 min_delegation: int = 100 * 10**18,  # 100 CPC minimum delegation
                 max_commission_rate: float = 0.20,   # 20% max commission
                 # Devnet specific deterministic keys (hex strings)
                 faucet_priv_key: str = None):
        self.network_id = network_id
        self.chain_id = chain_id
        self.block_time_sec = block_time_sec
        self.min_gas_price = min_gas_price
        self.block_gas_limit = block_gas_limit
        self.max_tx_per_block = max_tx_per_block
        self.genesis_premine = genesis_premine
        self.bech32_prefix_acc = bech32_prefix_acc
        self.bech32_prefix_val = bech32_prefix_val
        self.bech32_prefix_cons = bech32_prefix_cons
        self.version = version
        self.epoch_length_blocks = epoch_length_blocks
        self.min_validator_stake = min_validator_stake
        self.max_validators = max_validators
        # Performance params
        self.min_uptime_score = min_uptime_score
        self.max_missed_blocks_sequential = max_missed_blocks_sequential
        self.jail_duration_blocks = jail_duration_blocks
        self.slashing_penalty_rate = slashing_penalty_rate
        self.ejection_threshold_jails = ejection_threshold_jails
        self.performance_lookback_epochs = performance_lookback_epochs
        self.unstaking_period_blocks = unstaking_period_blocks
        self.undelegation_period_blocks = undelegation_period_blocks
        # Unjail params
        self.unjail_fee = unjail_fee
        # Delegation params
        self.min_delegation = min_delegation
        self.max_commission_rate = max_commission_rate
        self.faucet_priv_key = faucet_priv_key

NETWORKS: Dict[str, NetworkConfig] = {
    "devnet": NetworkConfig(
        network_id="devnet",
        chain_id="cpc-devnet-1",
        block_time_sec=5,
        min_gas_price=1000,
        block_gas_limit=50_000_000,
        max_tx_per_block=500,
        genesis_premine=1_000_000_000 * 10**18,
        epoch_length_blocks=10,
        min_validator_stake=1000,
        max_validators=5,
        # Deterministic Faucet Key for Devnet
        faucet_priv_key="4f3edf982522b4e51b7e8b5f2f9c4d1d7a9e5f8c2b6d4e1a3c5b7d9e0f1a2b3c" 
    ),
    "testnet": NetworkConfig(
        network_id="testnet",
        chain_id="cpc-testnet-1",
        block_time_sec=30,
        min_gas_price=5000,
        block_gas_limit=15_000_000,
        max_tx_per_block=1000,
        genesis_premine=100_000_000 * 10**18,
        epoch_length_blocks=100,
        min_validator_stake=100_000 * 10**18,
        max_validators=21
    ),
    "mainnet": NetworkConfig(
        network_id="mainnet",
        chain_id="cpc-mainnet-1",
        block_time_sec=60,
        min_gas_price=1000000000, # 1 Gwei
        block_gas_limit=30_000_000,
        max_tx_per_block=5000,
        genesis_premine=0,
        epoch_length_blocks=72, # ~1 hour approx if block time 60s? No, 72*60 = 72 mins.
        min_validator_stake=100_000 * 10**18,
        max_validators=100
    )
}

# Default to devnet for now
CURRENT_NETWORK = NETWORKS["devnet"]
