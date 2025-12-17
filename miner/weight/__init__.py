# MIT License
# Copyright (c) 2025 Hashborn

"""
Miner Weight Calculation Module

This module handles off-chain weight calculation for miners.
Weight is used to determine proportional reward distribution.

Architecture:
- calculator.py: Weight formula implementation
- prover.py: ZK proof generation (cryptographic proof of honest calculation)
- signer.py: Cryptographic signature of weight + proof
- verifier.py: Local verification (for testing)

The blockchain DOES NOT execute the weight formula on-chain.
Instead, it verifies the ZK proof to ensure honest calculation.
"""

from .calculator import WeightCalculator, MinerMetrics
from .prover import ZKProver
from .signer import WeightSigner

__all__ = [
    'WeightCalculator',
    'MinerMetrics',
    'ZKProver',
    'WeightSigner',
]
