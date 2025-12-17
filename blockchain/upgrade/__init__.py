# MIT License
# Copyright (c) 2025 Hashborn

"""
Upgrade Protocol (Phase 1.3)

Enables seamless chain upgrades without halting the network.
"""

from .types import Version, UpgradePlan
from .manager import UpgradeManager
from .migrations import MigrationRegistry, migration

__all__ = [
    "Version",
    "UpgradePlan",
    "UpgradeManager",
    "MigrationRegistry",
    "migration",
]
