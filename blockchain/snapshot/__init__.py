# MIT License
# Copyright (c) 2025 Hashborn

"""
State Snapshot System (Phase 1.3)

Enables fast node synchronization by creating/loading compressed state snapshots.
"""

from .snapshot_manager import SnapshotManager
from .types import Snapshot, SnapshotMetadata

__all__ = ["SnapshotManager", "Snapshot", "SnapshotMetadata"]
