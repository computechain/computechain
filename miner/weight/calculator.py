# MIT License
# Copyright (c) 2025 Hashborn

"""
Miner Weight Calculator

Implements the weight formula for miner reward distribution.
This calculation happens OFF-CHAIN (not in blockchain consensus).

Formula v1.0:
    weight = results_count * gpu_tier_multiplier * uptime_score * task_difficulty_avg * reputation_score

The blockchain does NOT execute this formula. Instead:
1. Miner calculates weight using this module
2. Miner generates ZK proof of honest calculation
3. Blockchain verifies ZK proof
"""

from dataclasses import dataclass
from typing import Dict

# GPU Tier Multipliers
# Higher tier = more powerful GPU = higher reward weight
GPU_TIERS: Dict[str, float] = {
    # Consumer GPUs
    "RTX_4070":     1.0,    # Baseline
    "RTX_4080":     1.3,    # +30%
    "RTX_4090":     1.6,    # +60%

    # Professional GPUs
    "RTX_A6000":    2.0,    # +100%
    "A100_40GB":    2.5,    # +150%
    "A100_80GB":    3.0,    # +200%

    # Latest generation
    "H100":         4.0,    # +300%
    "H200":         4.5,    # +350%

    # Unknown/default
    "UNKNOWN":      0.5,    # Penalty for unverified GPU
}

# Task Difficulty Weights
# More difficult tasks = higher reward weight
TASK_DIFFICULTY: Dict[str, float] = {
    "matrix_mult_small":    1.0,    # Baseline (RTX 4080 capable)
    "matrix_mult_large":    2.0,    # RTX 4090+
    "llm_inference_7b":     2.5,    # A100+
    "llm_inference_70b":    4.0,    # H100+
    "training_small":       5.0,    # H200 only
    "training_large":       6.0,    # Multiple H200s
}


@dataclass
class MinerMetrics:
    """
    Metrics used for weight calculation.

    These metrics are tracked off-chain by the miner.
    They are NOT stored on blockchain (privacy-preserving).
    """
    results_count: int          # Number of valid results submitted in this block/period
    gpu_model: str              # GPU model name (e.g., "H100")
    uptime_score: float         # Uptime reliability (0.0 - 1.0)
    task_difficulty_avg: float  # Average difficulty of tasks completed (1.0+)
    reputation_score: float     # Historical performance score (0.0 - 1.0)


class WeightCalculator:
    """
    Calculates miner weight for reward distribution.

    This is the OFF-CHAIN reference implementation.
    Blockchain does NOT execute this code - it verifies ZK proof instead.
    """

    def __init__(self, version: str = "v1.0"):
        """
        Initialize weight calculator.

        Args:
            version: Weight formula version (must match blockchain config)
        """
        self.version = version

    def calculate_weight(self, metrics: MinerMetrics) -> float:
        """
        Calculate miner weight using formula v1.0.

        Formula:
            weight = results_count * gpu_tier * uptime * difficulty * reputation

        Args:
            metrics: Miner performance metrics

        Returns:
            weight: Calculated weight for reward distribution

        Example:
            metrics = MinerMetrics(
                results_count=10,
                gpu_model="H100",
                uptime_score=0.95,
                task_difficulty_avg=1.5,
                reputation_score=1.0
            )
            weight = calculator.calculate_weight(metrics)
            # weight = 10 * 4.0 * 0.95 * 1.5 * 1.0 = 57.0
        """
        # Get GPU tier multiplier
        gpu_tier = GPU_TIERS.get(metrics.gpu_model, GPU_TIERS["UNKNOWN"])

        # Calculate weight
        weight = (
            metrics.results_count *
            gpu_tier *
            metrics.uptime_score *
            metrics.task_difficulty_avg *
            metrics.reputation_score
        )

        return weight

    def get_gpu_tier(self, gpu_model: str) -> float:
        """Get GPU tier multiplier for a given GPU model."""
        return GPU_TIERS.get(gpu_model, GPU_TIERS["UNKNOWN"])

    def get_task_difficulty(self, task_type: str) -> float:
        """Get difficulty multiplier for a given task type."""
        return TASK_DIFFICULTY.get(task_type, 1.0)

    def validate_metrics(self, metrics: MinerMetrics) -> tuple[bool, str]:
        """
        Validate miner metrics before weight calculation.

        Returns:
            (is_valid, error_message)
        """
        if metrics.results_count < 0:
            return False, "results_count cannot be negative"

        if not (0.0 <= metrics.uptime_score <= 1.0):
            return False, "uptime_score must be between 0.0 and 1.0"

        if metrics.task_difficulty_avg < 0:
            return False, "task_difficulty_avg cannot be negative"

        if not (0.0 <= metrics.reputation_score <= 1.0):
            return False, "reputation_score must be between 0.0 and 1.0"

        return True, ""


# Singleton instance
weight_calculator = WeightCalculator()
