# MIT License
# Copyright (c) 2025 Hashborn

"""
Snapshot Manager (Phase 1.3)

Handles creation, storage, loading, and verification of state snapshots.
"""

import os
import gzip
import json
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from .types import Snapshot, SnapshotMetadata
from ..core.state import AccountState
from ...protocol.config.params import CURRENT_NETWORK

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Manages state snapshots for fast node synchronization.

    Snapshots are saved as compressed JSON files:
    - snapshots/snapshot_<height>.json.gz (full snapshot)
    - snapshots/snapshot_<height>_meta.json (metadata for quick queries)
    """

    def __init__(self, snapshots_dir: str = "snapshots"):
        """
        Initialize snapshot manager.

        Args:
            snapshots_dir: Directory to store snapshots (default: "snapshots")
        """
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        state: AccountState,
        height: int,
        network_id: Optional[str] = None
    ) -> SnapshotMetadata:
        """
        Create a snapshot from current blockchain state.

        Args:
            state: Current AccountState
            height: Current block height
            network_id: Network ID (default: CURRENT_NETWORK.network_id)

        Returns:
            SnapshotMetadata for the created snapshot
        """
        logger.info(f"Creating snapshot at height {height}...")

        if network_id is None:
            network_id = CURRENT_NETWORK.network_id

        # Collect all accounts from state
        accounts_dict = {}
        for addr, acc in state._accounts.items():
            accounts_dict[addr] = acc.model_dump_json()

        # Load all accounts from DB (that aren't in cache)
        db_accounts = state.db.get_state_by_prefix("acc:")
        for key, value in db_accounts.items():
            addr = key.split(":")[1]
            if addr not in accounts_dict:
                accounts_dict[addr] = value

        # Collect all validators
        validators_dict = {}
        all_validators = state.get_all_validators()
        for val in all_validators:
            validators_dict[val.address] = val.model_dump_json()

        # Create snapshot object
        snapshot = Snapshot(
            version="1.0.0",
            network_id=network_id,
            height=height,
            epoch_index=state.epoch_index,
            timestamp=datetime.utcnow().isoformat() + "Z",
            total_burned=state.total_burned,
            total_minted=state.total_minted,
            accounts=accounts_dict,
            validators=validators_dict
        )

        # Calculate hash
        snapshot.hash = snapshot.calculate_hash()

        # Save to disk (compressed)
        snapshot_path = self._get_snapshot_path(height)
        uncompressed_data = snapshot.model_dump_json(indent=None).encode()
        uncompressed_size = len(uncompressed_data)

        with gzip.open(snapshot_path, 'wb', compresslevel=6) as f:
            f.write(uncompressed_data)

        compressed_size = snapshot_path.stat().st_size

        # Calculate total supply
        total_supply = state.get_total_supply(CURRENT_NETWORK.genesis_premine)

        # Create metadata
        metadata = SnapshotMetadata(
            version=snapshot.version,
            network_id=snapshot.network_id,
            height=snapshot.height,
            epoch_index=snapshot.epoch_index,
            timestamp=snapshot.timestamp,
            accounts_count=len(accounts_dict),
            validators_count=len(validators_dict),
            total_supply=total_supply,
            total_burned=snapshot.total_burned,
            total_minted=snapshot.total_minted,
            hash=snapshot.hash,
            compressed_size=compressed_size,
            uncompressed_size=uncompressed_size
        )

        # Save metadata separately (for quick queries)
        meta_path = self._get_metadata_path(height)
        with open(meta_path, 'w') as f:
            f.write(metadata.model_dump_json(indent=2))

        compression_ratio = (1 - compressed_size / uncompressed_size) * 100
        logger.info(
            f"Snapshot created at height {height}: "
            f"{len(accounts_dict)} accounts, {len(validators_dict)} validators, "
            f"{compressed_size / 1024:.2f} KB compressed ({compression_ratio:.1f}% reduction)"
        )

        return metadata

    def load_snapshot(self, height: int) -> Snapshot:
        """
        Load a snapshot from disk.

        Args:
            height: Block height of snapshot

        Returns:
            Snapshot object

        Raises:
            FileNotFoundError: If snapshot doesn't exist
            ValueError: If snapshot hash verification fails
        """
        snapshot_path = self._get_snapshot_path(height)

        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot at height {height} not found")

        logger.info(f"Loading snapshot from height {height}...")

        # Load compressed snapshot
        with gzip.open(snapshot_path, 'rb') as f:
            data = f.read()

        snapshot = Snapshot.model_validate_json(data)

        # Verify hash
        if not snapshot.verify_hash():
            raise ValueError(f"Snapshot at height {height} failed hash verification!")

        logger.info(
            f"Snapshot loaded: {len(snapshot.accounts)} accounts, "
            f"{len(snapshot.validators)} validators"
        )

        return snapshot

    def apply_snapshot(self, snapshot: Snapshot, state: AccountState):
        """
        Apply a snapshot to blockchain state.

        Args:
            snapshot: Snapshot to apply
            state: AccountState to populate
        """
        logger.info(f"Applying snapshot from height {snapshot.height}...")

        # Clear existing state (cache only, DB will be overwritten)
        state._accounts.clear()
        state._validators.clear()

        # Load accounts
        from ..core.accounts import Account
        for addr, acc_json in snapshot.accounts.items():
            acc = Account.model_validate_json(acc_json)
            state._accounts[addr] = acc
            state.db.set_state(f"acc:{addr}", acc_json)

        # Load validators
        from ...protocol.types.validator import Validator
        for addr, val_json in snapshot.validators.items():
            val = Validator.model_validate_json(val_json)
            state._validators[addr] = val
            state.db.set_state(f"val:{addr}", val_json)

        # Restore epoch info and economic tracking
        state.epoch_index = snapshot.epoch_index
        state.total_burned = snapshot.total_burned
        state.total_minted = snapshot.total_minted

        # Persist epoch info
        state.db.set_state("epoch_index", str(state.epoch_index))
        state.db.set_state("total_burned", str(state.total_burned))
        state.db.set_state("total_minted", str(state.total_minted))

        logger.info(
            f"Snapshot applied: epoch {snapshot.epoch_index}, "
            f"{len(snapshot.accounts)} accounts, {len(snapshot.validators)} validators"
        )

    def get_latest_snapshot_height(self) -> Optional[int]:
        """
        Get the height of the most recent snapshot.

        Returns:
            Height of latest snapshot, or None if no snapshots exist
        """
        snapshots = self.list_snapshots()
        if not snapshots:
            return None

        return max(snap.height for snap in snapshots)

    def list_snapshots(self) -> List[SnapshotMetadata]:
        """
        List all available snapshots.

        Returns:
            List of SnapshotMetadata, sorted by height (descending)
        """
        snapshots = []

        for meta_path in self.snapshots_dir.glob("snapshot_*_meta.json"):
            try:
                with open(meta_path, 'r') as f:
                    metadata = SnapshotMetadata.model_validate_json(f.read())
                    snapshots.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load metadata from {meta_path}: {e}")

        # Sort by height (descending)
        snapshots.sort(key=lambda s: s.height, reverse=True)

        return snapshots

    def delete_snapshot(self, height: int):
        """
        Delete a snapshot and its metadata.

        Args:
            height: Block height of snapshot to delete
        """
        snapshot_path = self._get_snapshot_path(height)
        meta_path = self._get_metadata_path(height)

        if snapshot_path.exists():
            snapshot_path.unlink()
            logger.info(f"Deleted snapshot at height {height}")

        if meta_path.exists():
            meta_path.unlink()

    def cleanup_old_snapshots(self, keep_count: int = 10):
        """
        Delete old snapshots, keeping only the N most recent.

        Args:
            keep_count: Number of snapshots to keep (default: 10)
        """
        snapshots = self.list_snapshots()

        if len(snapshots) <= keep_count:
            return

        # Delete oldest snapshots
        to_delete = snapshots[keep_count:]
        for snap in to_delete:
            self.delete_snapshot(snap.height)

        logger.info(f"Cleaned up {len(to_delete)} old snapshots")

    def _get_snapshot_path(self, height: int) -> Path:
        """Get path to snapshot file."""
        return self.snapshots_dir / f"snapshot_{height}.json.gz"

    def _get_metadata_path(self, height: int) -> Path:
        """Get path to metadata file."""
        return self.snapshots_dir / f"snapshot_{height}_meta.json"

    def save_snapshot_bytes(self, height: int, data: bytes) -> Path:
        """
        Save raw snapshot bytes (gzip-compressed JSON) to disk.
        """
        snapshot_path = self._get_snapshot_path(height)
        with open(snapshot_path, "wb") as f:
            f.write(data)
        return snapshot_path
