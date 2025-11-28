from typing import Optional, List
from ...protocol.types.validator import Validator, ValidatorSet

class ConsensusEngine:
    def __init__(self):
        self.validator_set = ValidatorSet(validators=[])

    def update_validator_set(self, validators: List[Validator]):
        """Updates the validator set (e.g. from genesis or block updates)."""
        self.validator_set = ValidatorSet(validators=validators)

    def get_proposer(self, height: int, round: int = 0) -> Optional[Validator]:
        """Returns the expected proposer for the given height and round."""
        return self.validator_set.get_proposer(height, round)
