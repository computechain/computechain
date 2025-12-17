# MIT License
# Copyright (c) 2025 Hashborn

"""
Upgrade Manager (Phase 1.3)

Coordinates chain upgrades during block processing.
"""

import logging
from typing import Optional
from .types import Version, UpgradePlan, ChainVersion
from .migrations import get_global_registry
from ..core.state import AccountState

logger = logging.getLogger(__name__)


class UpgradeManager:
    """
    Manages chain upgrades and state migrations.

    Responsibilities:
    - Track current chain version
    - Schedule upgrades
    - Execute migrations at upgrade height
    - Validate block versions
    """

    def __init__(self, current_version: str = "1.0.0"):
        """
        Initialize upgrade manager.

        Args:
            current_version: Current chain version (default: "1.0.0")
        """
        self.chain_version = ChainVersion(version=current_version)
        self.migration_registry = get_global_registry()

    def get_current_version(self) -> Version:
        """Get current chain version."""
        return self.chain_version.get_version()

    def schedule_upgrade(self, plan: UpgradePlan):
        """
        Schedule a network upgrade.

        Args:
            plan: Upgrade plan

        Raises:
            ValueError: If upgrade is invalid
        """
        current = self.get_current_version()
        target = plan.get_version()

        # Validate version progression
        if target <= current:
            raise ValueError(
                f"Target version {target} must be greater than current {current}"
            )

        # Check if migration exists for breaking changes
        if plan.breaking_changes:
            if not self.migration_registry.has_migration(
                self.chain_version.version,
                plan.version
            ):
                raise ValueError(
                    f"Breaking upgrade requires migration from {self.chain_version.version} "
                    f"to {plan.version}, but no migration registered"
                )

        self.chain_version.next_upgrade = plan
        logger.info(
            f"Scheduled upgrade: {plan.name} ({plan.version}) at height {plan.upgrade_height}"
        )

    def should_upgrade(self, current_height: int) -> bool:
        """
        Check if an upgrade should happen at this height.

        Args:
            current_height: Current block height

        Returns:
            True if upgrade should be performed
        """
        if not self.chain_version.next_upgrade:
            return False

        return current_height == self.chain_version.next_upgrade.upgrade_height

    def execute_upgrade(self, state: AccountState, height: int):
        """
        Execute a scheduled upgrade at the given height.

        Args:
            state: Current blockchain state
            height: Current block height

        Raises:
            RuntimeError: If upgrade fails
        """
        if not self.chain_version.next_upgrade:
            raise RuntimeError("No upgrade scheduled")

        plan = self.chain_version.next_upgrade

        logger.info(f"Executing upgrade: {plan.name} ({plan.version}) at height {height}")

        # Get migration (if any)
        migration_func = None
        try:
            migration_func = self.migration_registry.get_migration(
                self.chain_version.version,
                plan.version
            )
        except KeyError as e:
            logger.error(f"Migration error: {e}")
            raise RuntimeError(f"Upgrade failed: {e}")

        # Execute migration
        if migration_func:
            logger.info(f"Running migration: {self.chain_version.version} -> {plan.version}")
            try:
                migration_func(state)
                logger.info("Migration completed successfully")
            except Exception as e:
                logger.error(f"Migration failed: {e}")
                raise RuntimeError(f"Migration failed: {e}")
        else:
            logger.info("No migration needed for this upgrade")

        # Update chain version
        old_version = self.chain_version.version
        self.chain_version.version = plan.version
        self.chain_version.last_upgrade_height = height
        self.chain_version.next_upgrade = None

        # Persist version to state (for recovery after restart)
        state.db.set_state("chain_version", self.chain_version.model_dump_json())

        logger.info(f"Upgrade complete: {old_version} -> {plan.version}")

    def load_version_from_state(self, state: AccountState):
        """
        Load chain version from persisted state.

        Args:
            state: Blockchain state
        """
        version_json = state.db.get_state("chain_version")
        if version_json:
            self.chain_version = ChainVersion.model_validate_json(version_json)
            logger.info(f"Loaded chain version: {self.chain_version.version}")
        else:
            # First time - persist default version
            state.db.set_state("chain_version", self.chain_version.model_dump_json())
            logger.info(f"Initialized chain version: {self.chain_version.version}")

    def validate_block_version(self, block_height: int, block_version: Optional[str] = None) -> bool:
        """
        Validate that a block's version is compatible with chain state.

        Args:
            block_height: Height of the block
            block_version: Version tag of the block (optional, for future use)

        Returns:
            True if valid, False otherwise
        """
        # For now, blocks don't carry version tags
        # In the future, blocks could include version field for validation
        # This would enforce that all nodes agree on upgrade timing

        if self.chain_version.next_upgrade:
            upgrade_height = self.chain_version.next_upgrade.upgrade_height

            # After upgrade height, old software should reject new blocks
            if block_height > upgrade_height:
                # Block is post-upgrade, node must be upgraded
                required_version = self.chain_version.next_upgrade.get_version()
                current_version = self.get_current_version()

                if current_version < required_version:
                    logger.error(
                        f"Block {block_height} requires version {required_version}, "
                        f"but node is on {current_version}. Upgrade required!"
                    )
                    return False

        return True
