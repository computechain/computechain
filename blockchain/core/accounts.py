from pydantic import BaseModel, Field
from typing import Dict

class Account(BaseModel):
    address: str
    balance: int = 0
    nonce: int = 0

    # Reward tracking for delegators (Phase 1: Step 2)
    # Maps epoch number to total rewards earned in that epoch
    reward_history: Dict[int, int] = Field(default_factory=dict)

    # Future fields for staking/locking can be added here
    # staked_balance: int = 0 

