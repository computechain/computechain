"""Immutable integer policy for CPC v3 LOCAL DEVNET, not production tokenomics."""
UNIT = 10**18
BPS = 10_000
VERSION = 3
MIN_GAS_PRICE = 1000
GAS = {"TRANSFER": 21_000, "STAKE": 40_000, "UNSTAKE": 40_000,
       "DELEGATE": 35_000, "UNDELEGATE": 35_000, "UPDATE_VALIDATOR": 30_000}
BLOCK_GAS_LIMIT = 10_500_000
MIN_SELF_STAKE = 1000 * UNIT
MIN_DELEGATION = 10 * UNIT
MAX_VALIDATORS = 64
MAX_DELEGATIONS = 10
MAX_BONDS = 64
MAX_UNBONDINGS = 64
MAX_TOTAL_POWER = (2**63 - 1) // 8  # pinned CometBFT types.MaxTotalVotingPower
POWER_UNIT = UNIT
MAX_POWER_SHARE_BPS = 2000
MAX_COMMISSION_BPS = 2000
MAX_COMMISSION_INCREASE_BPS = 500
COMMISSION_COOLDOWN_BLOCKS = 100
COMMISSION_ANNOUNCE_BLOCKS = 20
UPDATE_DELAY = 2
UNBOND_BLOCKS = 100
UNBOND_SECONDS = 60
EVIDENCE_BLOCKS = 20
EVIDENCE_SECONDS = 30
SLASH_BPS = 500


def policy():
    return {"version": VERSION, "unit": UNIT, "gas": GAS.copy(), "min_gas_price": MIN_GAS_PRICE,
        "block_gas_limit": BLOCK_GAS_LIMIT, "power_unit": POWER_UNIT, "min_self_stake": MIN_SELF_STAKE,
        "min_delegation": MIN_DELEGATION, "max_validators": MAX_VALIDATORS, "max_delegations": MAX_DELEGATIONS,
        "max_bonds": MAX_BONDS, "max_unbondings": MAX_UNBONDINGS, "max_total_power": MAX_TOTAL_POWER,
        "max_power_share_bps": MAX_POWER_SHARE_BPS, "max_commission_bps": MAX_COMMISSION_BPS,
        "max_commission_increase_bps": MAX_COMMISSION_INCREASE_BPS,
        "commission_cooldown_blocks": COMMISSION_COOLDOWN_BLOCKS,
        "commission_announce_blocks": COMMISSION_ANNOUNCE_BLOCKS, "update_delay": UPDATE_DELAY,
        "unbond_blocks": UNBOND_BLOCKS, "unbond_seconds": UNBOND_SECONDS,
        "evidence_blocks": EVIDENCE_BLOCKS, "evidence_seconds": EVIDENCE_SECONDS,
        "slash_bps": SLASH_BPS, "block_reward": 0, "fee_burn_bps": BPS}
