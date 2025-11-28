from pydantic import BaseModel
from typing import List, Optional

class Validator(BaseModel):
    address: str      # Bech32 address (cpcvalcons...)
    pq_pub_key: str   # Hex encoded PQ public key
    power: int        # Voting power
    is_active: bool = True
    reward_address: Optional[str] = None # Address to receive rewards

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
