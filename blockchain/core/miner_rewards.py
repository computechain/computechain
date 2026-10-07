# MIT License
# Copyright (c) 2025 Hashborn

"""
Miner Reward Distribution

Distributes miner reward pool proportionally based on verified weights.

Economic Model:
- Block reward: 10 CPC
- Miner pool: 30% (3 CPC)
- Distribution: Proportional to verified miner weights

Flow:
1. Collect all valid miner weight submissions in block
2. Verify each submission (ZK proof + signature)
3. Calculate total weight
4. Distribute miner_pool proportionally
5. Handle dust (remainder from integer division) → BURN
"""

import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass
from ...protocol.config.economic_model import ECONOMIC_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class MinerSubmission:
    """
    Miner's weight submission for a block.

    This data comes from SUBMIT_RESULT transactions.
    """
    miner_address: str      # Miner's blockchain address
    weight: float           # Verified weight
    # In full implementation, would also include:
    # - computation_results
    # - zk_proof
    # - signature


class MinerRewardDistributor:
    """
    Distributes miner rewards based on verified weights.

    This runs during block processing (on-chain).
    """

    def __init__(self, economic_config=None):
        """
        Initialize miner reward distributor.

        Args:
            economic_config: Economic configuration (defaults to ECONOMIC_CONFIG)
        """
        self.config = economic_config or ECONOMIC_CONFIG

    def distribute_miner_rewards(
        self,
        miner_pool: int,
        miner_submissions: List[MinerSubmission],
        state
    ) -> Tuple[int, int]:
        """
        Distribute miner reward pool to miners.

        Args:
            miner_pool: Total miner rewards for this block (in minimal units)
            miner_submissions: List of valid miner submissions
            state: Current blockchain state

        Returns:
            (total_distributed, dust_burned)
        """
        if not miner_submissions:
            # No miners in this block → burn entire miner pool
            logger.info(f"No miner submissions, burning miner pool: {miner_pool}")
            return 0, miner_pool

        # MinerSubmission contains no proof/signature. A caller cannot assert that
        # an arbitrary weight was verified. Enable payouts only with a real protocol.
        raise ValueError("Miner payouts disabled until cryptographic weight verification is implemented")

    def validate_miner_submission(
        self,
        submission: MinerSubmission
    ) -> Tuple[bool, str]:
        """
        Validate miner submission.

        Checks:
        - Weight within bounds
        - No negative values

        Note: ZK proof verification done separately in zk_verification.py

        Args:
            submission: Miner submission to validate

        Returns:
            (is_valid, error_message)
        """
        # Check weight bounds
        if submission.weight < self.config.min_miner_weight:
            return False, f"Weight {submission.weight} below minimum {self.config.min_miner_weight}"

        if submission.weight > self.config.max_miner_weight:
            return False, f"Weight {submission.weight} above maximum {self.config.max_miner_weight}"

        # Check non-negative
        if submission.weight < 0:
            return False, "Weight cannot be negative"

        return True, ""


# Global distributor instance
miner_reward_distributor = MinerRewardDistributor()
