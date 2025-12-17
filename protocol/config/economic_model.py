# MIT License
# Copyright (c) 2025 Hashborn

"""
ComputeChain Economic Model v2.0
Single source of truth for all economic parameters.

Burn policy: Only when truly needed
- Undistributed remainder (dust from integer division)
- Penalties (slashing, unjail fee, unstake penalty when jailed)
"""

from dataclasses import dataclass
from typing import Dict

DECIMALS = 10**18

# Treasury Address (hardcoded, governance-controlled in future)
TREASURY_ADDRESS = "cpc1treasury000000000000000000000000000000000000000000"  # Special address for community pool

@dataclass
class EconomicConfig:
    """Economic parameters for a network."""

    # ═══════════════════════════════════════════════════════
    # EMISSION & HALVING
    # ═══════════════════════════════════════════════════════
    initial_block_reward: int           # Initial block reward in minimal units
    halving_period_blocks: int          # Halving every N blocks

    # ═══════════════════════════════════════════════════════
    # BLOCK REWARD DISTRIBUTION
    # ═══════════════════════════════════════════════════════
    validator_reward_share: float       # % of block reward for validators (e.g., 0.70 = 70%)
    miner_reward_share: float           # % of block reward for miners (e.g., 0.30 = 30%)

    # ═══════════════════════════════════════════════════════
    # REWARD CAPS (per block)
    # ═══════════════════════════════════════════════════════
    max_validator_reward_per_block: int  # Max reward single validator can get per block
    max_miner_reward_per_block: int      # Max reward single miner can get per block
    # If reward exceeds cap → excess BURNED

    # ═══════════════════════════════════════════════════════
    # TRANSACTION FEES DISTRIBUTION
    # ═══════════════════════════════════════════════════════
    validator_fee_share: float          # % of fees to block producer (e.g., 0.90 = 90%)
    treasury_fee_share: float           # % of fees to treasury (e.g., 0.10 = 10%)
    # Remainder (if any) → BURNED

    # ═══════════════════════════════════════════════════════
    # SLASHING RATES
    # ═══════════════════════════════════════════════════════
    validator_slashing_rate: float      # % slashed from validator total stake (self + delegations)
    miner_slashing_rate: float          # % slashed from miner stake
    # All slashed tokens → BURNED

    # ═══════════════════════════════════════════════════════
    # PENALTIES (all burned)
    # ═══════════════════════════════════════════════════════
    unjail_fee: int                     # Fee to unjail early (burned)
    unstake_penalty_rate: float         # % penalty for unstaking when jailed (burned)

    # ═══════════════════════════════════════════════════════
    # VALIDATOR LIMITS
    # ═══════════════════════════════════════════════════════
    max_validator_power_share: float    # Max % of total voting power (e.g., 0.20 = 20%)
    max_commission_rate: float          # Max commission rate (e.g., 0.20 = 20%)

    # Commission change rules
    commission_change_cooldown_blocks: int   # Cooldown between commission changes
    commission_announce_period_blocks: int   # Announce period before change takes effect
    max_commission_increase: float           # Max increase per change (e.g., 0.05 = +5pp)

    # ═══════════════════════════════════════════════════════
    # DELEGATION LIMITS
    # ═══════════════════════════════════════════════════════
    max_validators_per_delegator: int   # Max validators one delegator can delegate to
    max_unbonding_per_epoch_rate: float # Max % of validator stake that can unbond per epoch

    # ═══════════════════════════════════════════════════════
    # MINER WEIGHT VERIFICATION (ZK-based)
    # ═══════════════════════════════════════════════════════
    # NOTE: Weight CALCULATION happens in miner/ (off-chain)
    # Blockchain only VERIFIES weight via ZK proof + signature

    weight_calculation_version: str     # Version of weight formula (e.g., "v1.0")
    zk_circuit_hash: str                # Hash of ZK circuit for verification
    min_miner_weight: float             # Minimum valid weight (anti-spam)
    max_miner_weight: float             # Maximum valid weight (sanity check)

    # Weight formula reference (for documentation, NOT executed on-chain)
    # weight = results_count * gpu_tier_multiplier * uptime_score * task_difficulty * reputation
    # Actual calculation in: miner/weight/calculator.py
    # ZK proof generation in: miner/weight/prover.py

    # ═══════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════

    def calculate_block_reward(self, height: int) -> int:
        """Calculate block reward with halving."""
        halvings = height // self.halving_period_blocks
        return self.initial_block_reward >> halvings

    def distribute_block_reward(self, total_reward: int) -> Dict[str, int]:
        """
        Split block reward into validator and miner pools.
        Returns: {'validator_pool': int, 'miner_pool': int}
        """
        validator_pool = int(total_reward * self.validator_reward_share)
        miner_pool = int(total_reward * self.miner_reward_share)

        return {
            'validator_pool': validator_pool,
            'miner_pool': miner_pool,
        }

    def distribute_fees(self, total_fees: int) -> Dict[str, int]:
        """
        Split fees into validator share and treasury.
        Returns: {'validator_share': int, 'treasury': int, 'dust': int}
        Dust (if any) should be burned.
        """
        validator_share = int(total_fees * self.validator_fee_share)
        treasury = int(total_fees * self.treasury_fee_share)
        dust = total_fees - validator_share - treasury

        return {
            'validator_share': validator_share,
            'treasury': treasury,
            'dust': dust,  # Burn this
        }


# ═══════════════════════════════════════════════════════════════════════════
# DEVNET CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
DEVNET = EconomicConfig(
    # Emission
    initial_block_reward=10 * DECIMALS,         # 10 CPC per block
    halving_period_blocks=1_000_000,            # Halving every 1M blocks

    # Block reward split
    validator_reward_share=0.70,                # 70% (7 CPC)
    miner_reward_share=0.30,                    # 30% (3 CPC)

    # Reward caps per block
    max_validator_reward_per_block=7 * DECIMALS,   # Max 7 CPC per validator per block
    max_miner_reward_per_block=3 * DECIMALS,       # Max 3 CPC per miner per block

    # Fee distribution
    validator_fee_share=0.90,                   # 90% to block producer
    treasury_fee_share=0.10,                    # 10% to treasury

    # Slashing
    validator_slashing_rate=0.05,               # 5% (includes delegations)
    miner_slashing_rate=0.10,                   # 10%

    # Penalties
    unjail_fee=1_000 * DECIMALS,                # 1000 CPC
    unstake_penalty_rate=0.10,                  # 10%

    # Validator limits
    max_validator_power_share=0.20,             # 20% max voting power
    max_commission_rate=0.20,                   # 20% max commission

    # Commission change rules
    commission_change_cooldown_blocks=10_080,   # ~7 days @ 10s
    commission_announce_period_blocks=1_440,    # ~4 hours @ 10s
    max_commission_increase=0.05,               # +5pp max per change

    # Delegation limits
    max_validators_per_delegator=10,            # Max 10 validators
    max_unbonding_per_epoch_rate=0.30,          # 30% max unbonding per epoch

    # Miner weight verification (ZK-based)
    weight_calculation_version="v1.0",          # Formula version
    zk_circuit_hash="0x0000000000000000000000000000000000000000000000000000000000000000",  # TODO: Update with actual circuit hash
    min_miner_weight=0.1,                       # Minimum valid weight (anti-spam)
    max_miner_weight=1000.0,                    # Maximum valid weight (sanity check)
)


# ═══════════════════════════════════════════════════════════════════════════
# TESTNET CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
TESTNET = EconomicConfig(
    # Emission
    initial_block_reward=10 * DECIMALS,         # 10 CPC per block
    halving_period_blocks=1_000_000,            # Halving every 1M blocks

    # Block reward split
    validator_reward_share=0.70,                # 70% (7 CPC)
    miner_reward_share=0.30,                    # 30% (3 CPC)

    # Reward caps per block
    max_validator_reward_per_block=7 * DECIMALS,   # Max 7 CPC per validator per block
    max_miner_reward_per_block=3 * DECIMALS,       # Max 3 CPC per miner per block

    # Fee distribution
    validator_fee_share=0.90,                   # 90% to block producer
    treasury_fee_share=0.10,                    # 10% to treasury

    # Slashing
    validator_slashing_rate=0.05,               # 5% (includes delegations)
    miner_slashing_rate=0.10,                   # 10%

    # Penalties
    unjail_fee=1_000 * DECIMALS,                # 1000 CPC
    unstake_penalty_rate=0.10,                  # 10%

    # Validator limits
    max_validator_power_share=0.20,             # 20% max voting power
    max_commission_rate=0.20,                   # 20% max commission

    # Commission change rules
    commission_change_cooldown_blocks=30_240,   # ~7 days @ 30s
    commission_announce_period_blocks=4_320,    # ~4 hours @ 30s (testnet block time)
    max_commission_increase=0.05,               # +5pp max per change

    # Delegation limits
    max_validators_per_delegator=10,            # Max 10 validators
    max_unbonding_per_epoch_rate=0.30,          # 30% max unbonding per epoch

    # Miner weight verification (ZK-based)
    weight_calculation_version="v1.0",          # Formula version
    zk_circuit_hash="0x0000000000000000000000000000000000000000000000000000000000000000",  # TODO: Update with actual circuit hash
    min_miner_weight=0.1,                       # Minimum valid weight (anti-spam)
    max_miner_weight=1000.0,                    # Maximum valid weight (sanity check)
)


# ═══════════════════════════════════════════════════════════════════════════
# MAINNET CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
MAINNET = EconomicConfig(
    # Emission
    initial_block_reward=10 * DECIMALS,         # 10 CPC per block
    halving_period_blocks=1_000_000,            # Halving every 1M blocks

    # Block reward split
    validator_reward_share=0.70,                # 70% (7 CPC)
    miner_reward_share=0.30,                    # 30% (3 CPC)

    # Reward caps per block
    max_validator_reward_per_block=7 * DECIMALS,   # Max 7 CPC per validator per block
    max_miner_reward_per_block=3 * DECIMALS,       # Max 3 CPC per miner per block

    # Fee distribution
    validator_fee_share=0.90,                   # 90% to block producer
    treasury_fee_share=0.10,                    # 10% to treasury

    # Slashing
    validator_slashing_rate=0.05,               # 5% (includes delegations)
    miner_slashing_rate=0.10,                   # 10%

    # Penalties
    unjail_fee=1_000 * DECIMALS,                # 1000 CPC
    unstake_penalty_rate=0.10,                  # 10%

    # Validator limits
    max_validator_power_share=0.20,             # 20% max voting power
    max_commission_rate=0.20,                   # 20% max commission

    # Commission change rules
    commission_change_cooldown_blocks=181_440,  # ~21 days @ 10s
    commission_announce_period_blocks=14_400,   # ~40 hours @ 10s
    max_commission_increase=0.05,               # +5pp max per change

    # Delegation limits
    max_validators_per_delegator=10,            # Max 10 validators
    max_unbonding_per_epoch_rate=0.30,          # 30% max unbonding per epoch

    # Miner weight verification (ZK-based)
    weight_calculation_version="v1.0",          # Formula version
    zk_circuit_hash="0x0000000000000000000000000000000000000000000000000000000000000000",  # TODO: Update with actual circuit hash
    min_miner_weight=0.1,                       # Minimum valid weight (anti-spam)
    max_miner_weight=1000.0,                    # Maximum valid weight (sanity check)
)


# ═══════════════════════════════════════════════════════════════════════════
# CURRENT NETWORK (selected at runtime)
# ═══════════════════════════════════════════════════════════════════════════
ECONOMIC_CONFIG = DEVNET  # Default to devnet, can be changed via CLI/config
