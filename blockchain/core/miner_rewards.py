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
from protocol.config.economic_model import ECONOMIC_CONFIG

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

        if miner_pool == 0:
            logger.warning("Miner pool is 0, nothing to distribute")
            return 0, 0

        # Calculate total weight
        total_weight = sum(sub.weight for sub in miner_submissions)

        if total_weight == 0:
            # All weights are 0 → burn pool
            logger.warning("Total miner weight is 0, burning miner pool")
            return 0, miner_pool

        # Distribute proportionally
        total_distributed = 0

        for submission in miner_submissions:
            # Calculate proportional reward
            # reward = (miner_pool * miner_weight) / total_weight
            miner_reward = (miner_pool * int(submission.weight * 1e6)) // int(total_weight * 1e6)

            if miner_reward > 0:
                # Get miner account
                miner_acc = state.get_account(submission.miner_address)
                miner_acc.balance += miner_reward
                state.set_account(miner_acc)

                total_distributed += miner_reward

                logger.info(
                    f"Distributed {miner_reward} to miner {submission.miner_address} "
                    f"(weight: {submission.weight:.2f}, share: {submission.weight/total_weight*100:.1f}%)"
                )

        # Calculate dust (remainder)
        dust = miner_pool - total_distributed

        if dust > 0:
            logger.info(f"Miner reward dust: {dust} (will be burned)")

        return total_distributed, dust

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
