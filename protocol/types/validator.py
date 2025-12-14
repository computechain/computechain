from pydantic import BaseModel, Field
from typing import List, Optional

class Delegation(BaseModel):
    """Represents a delegation from a user to a validator."""
    delegator: str          # Delegator's address (cpc...)
    validator: str          # Validator's address (cpcvalcons...)
    amount: int             # Delegated amount
    created_height: int     # Block height when delegation was created

class UnstakingEntry(BaseModel):
    """Represents a pending unstake request."""
    amount: int                    # Amount being unstaked
    completion_height: int         # Block height when tokens become available
    beneficiary: str              # Address to receive tokens (usually validator owner)

class Validator(BaseModel):
    address: str      # Bech32 address (cpcvalcons...)
    pq_pub_key: str   # Hex encoded PQ public key
    power: int        # Voting power
    is_active: bool = True
    reward_address: Optional[str] = None # Address to receive rewards

    # Metadata (human-readable info)
    name: Optional[str] = None           # Validator name (e.g., "MyPool")
    website: Optional[str] = None        # Website URL
    description: Optional[str] = None    # Short description (max 256 chars)

    # Performance tracking (Phase 0: Validator Performance System)
    blocks_proposed: int = 0          # How many blocks created
    blocks_expected: int = 0          # How many blocks should have created
    missed_blocks: int = 0            # Consecutive missed blocks
    last_block_height: int = 0        # Last block height proposed
    uptime_score: float = 1.0         # Score from 0.0 to 1.0
    performance_score: float = 1.0    # Overall performance score

    # Penalties & Slashing
    total_penalties: int = 0          # Total penalties applied
    jailed_until_height: int = 0      # Jailed until this block height (0 = not jailed)
    jail_count: int = 0               # Number of times jailed

    # Metadata
    joined_height: int = 0            # Block height when validator joined
    last_seen_height: int = 0         # Last block height when active

    # Unstaking queue (timelock)
    unstaking_queue: List[UnstakingEntry] = Field(default_factory=list)

    # Delegation & Commission (Phase 2: Decentralization)
    commission_rate: float = 0.10        # Commission rate (0.0 to 1.0, default 10%)
    self_stake: int = 0                  # Validator's own stake
    total_delegated: int = 0             # Total delegated by others
    delegations: List[Delegation] = Field(default_factory=list)  # Individual delegations

class ValidatorSet(BaseModel):
    validators: List[Validator]
    total_power: int = 0

    def __init__(self, **data):
        super().__init__(**data)
        self.total_power = sum(v.power for v in self.validators if v.is_active)

    def get_proposer(self, height: int, round: int = 0) -> Optional[Validator]:
        """
        Selects proposer for a given height using Round-Robin with Round support.
        Validators are sorted by address to ensure determinism.
        
        Args:
            height: Block height
            round: Round number (0 = standard time slot, 1+ = delayed slots)
        """
        active = sorted([v for v in self.validators if v.is_active], key=lambda v: v.address)
        if not active:
            return None
        
        # Round-Robin with offset based on round
        # If round 0 (normal): index = height % N
        # If round 1 (1 timeout): index = (height + 1) % N
        index = (height + round) % len(active)
        return active[index]

    def get_by_address(self, address: str) -> Optional[Validator]:
        for v in self.validators:
            if v.address == address:
                return v
        return None
