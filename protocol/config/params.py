# MIT License
# Copyright (c) 2025 Hashborn

from typing import Dict, Any
from ..types.common import TxType

# Global Constants
DENOM = "cpc"
DECIMALS = 18

# Base Gas Costs
GAS_PER_TYPE = {
    TxType.TRANSFER:      21_000,
    TxType.STAKE:         40_000,
    TxType.SUBMIT_RESULT: 80_000,
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
        self.faucet_priv_key = faucet_priv_key

NETWORKS: Dict[str, NetworkConfig] = {
    "devnet": NetworkConfig(
        network_id="devnet",
        chain_id="cpc-devnet-1",
        block_time_sec=10,
        min_gas_price=1000,
        block_gas_limit=10_000_000,
        max_tx_per_block=100,
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
