# MIT License
# Copyright (c) 2025 Hashborn

"""
State Migration Registry (Phase 1.3)

Allows registering migration functions that run during upgrades.
"""

import logging
from typing import Dict, Callable
from .types import Version

logger = logging.getLogger(__name__)


class MigrationRegistry:
    """
    Registry for state migration functions.

    Migrations are triggered when crossing an upgrade height.
    Each migration transforms state from version N to version N+1.
    """

    def __init__(self):
        self._migrations: Dict[str, Callable] = {}

    def register(self, from_version: str, to_version: str, migration_func: Callable):
        """
        Register a migration function.

        Args:
            from_version: Version to migrate from (e.g., "1.0.0")
            to_version: Version to migrate to (e.g., "1.1.0")
            migration_func: Function that takes (state: AccountState) -> None
        """
        key = f"{from_version}->{to_version}"
        if key in self._migrations:
            logger.warning(f"Overwriting migration {key}")

        self._migrations[key] = migration_func
        logger.info(f"Registered migration: {key}")

    def get_migration(self, from_version: str, to_version: str) -> Callable:
        """
        Get migration function for version transition.

        Args:
            from_version: Current version
            to_version: Target version

        Returns:
            Migration function, or None if no migration needed

        Raises:
            KeyError: If migration not found and is required
        """
        key = f"{from_version}->{to_version}"

        if key in self._migrations:
            return self._migrations[key]

        # Check if migration is needed
        from_v = Version.from_string(from_version)
        to_v = Version.from_string(to_version)

        # Same version → no migration
        if from_v == to_v:
            return None

        # Minor/patch upgrade → optional migration
        if from_v.major == to_v.major:
            if (to_v.minor == from_v.minor and to_v.patch > from_v.patch) or \
               (to_v.minor > from_v.minor):
                # Minor or patch upgrade - migration may not be required
                logger.info(f"No migration registered for {key} (optional)")
                return None

        # Major version change → migration required
        if to_v.major != from_v.major:
            raise KeyError(
                f"Migration required for {key} but not found. "
                f"Cannot perform breaking upgrade without migration."
            )

        raise KeyError(f"Migration {key} not found")

    def get_migration_path(self, from_version: str, to_version: str) -> list:
        """
        Get sequence of migrations needed to go from from_version to to_version.

        For example: 1.0.0 -> 1.2.0 might require:
          1.0.0 -> 1.1.0
          1.1.0 -> 1.2.0

        Args:
            from_version: Starting version
            to_version: Target version

        Returns:
            List of (from, to, migration_func) tuples
        """
        from_v = Version.from_string(from_version)
        to_v = Version.from_string(to_version)

        if from_v >= to_v:
            return []

        # For now, only support direct migrations
        # In the future, could implement graph search for multi-step migrations
        migration = self.get_migration(from_version, to_version)
        if migration:
            return [(from_version, to_version, migration)]
        return []

    def has_migration(self, from_version: str, to_version: str) -> bool:
        """Check if migration exists."""
        key = f"{from_version}->{to_version}"
        return key in self._migrations

    def list_migrations(self) -> list:
        """List all registered migrations."""
        return list(self._migrations.keys())


# Global migration registry
_global_registry = MigrationRegistry()


def migration(from_version: str, to_version: str):
    """
    Decorator to register a migration function.

    Usage:
        @migration("1.0.0", "1.1.0")
        def migrate_1_0_to_1_1(state: AccountState):
            # Perform migration
            state.new_field = default_value
    """
    def decorator(func):
        _global_registry.register(from_version, to_version, func)
        return func
    return decorator


def get_global_registry() -> MigrationRegistry:
    """Get the global migration registry."""
    return _global_registry
