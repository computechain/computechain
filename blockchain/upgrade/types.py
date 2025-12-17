# MIT License
# Copyright (c) 2025 Hashborn

"""
Upgrade Protocol Types (Phase 1.3)
"""

from pydantic import BaseModel, Field
from typing import Optional
from dataclasses import dataclass


@dataclass
class Version:
    """
    Semantic version (MAJOR.MINOR.PATCH).

    Breaking changes: increment MAJOR
    New features (backwards compatible): increment MINOR
    Bug fixes: increment PATCH
    """
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_string(cls, version_str: str) -> 'Version':
        """Parse version from string (e.g., '1.2.3')."""
        parts = version_str.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str}")

        return cls(
            major=int(parts[0]),
            minor=int(parts[1]),
            patch=int(parts[2])
        )

    def is_compatible_with(self, other: 'Version') -> bool:
        """
        Check if this version is compatible with another.

        Compatible if:
        - Same MAJOR version (breaking changes compatibility)
        - This version >= other version
        """
        if self.major != other.major:
            return False

        if self.minor < other.minor:
            return False

        if self.minor == other.minor and self.patch < other.patch:
            return False

        return True

    def __lt__(self, other: 'Version') -> bool:
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.patch < other.patch

    def __eq__(self, other) -> bool:
        if not isinstance(other, Version):
            return False
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __le__(self, other: 'Version') -> bool:
        return self < other or self == other

    def __gt__(self, other: 'Version') -> bool:
        return not self <= other

    def __ge__(self, other: 'Version') -> bool:
        return not self < other


class UpgradePlan(BaseModel):
    """
    Planned network upgrade.

    Defines when and how to upgrade the chain to a new version.
    """
    name: str = Field(..., description="Upgrade name (e.g., 'Phase2A')")
    version: str = Field(..., description="Target version (e.g., '1.1.0')")
    upgrade_height: int = Field(..., description="Block height to activate upgrade")
    description: str = Field(default="", description="Upgrade description")
    breaking_changes: bool = Field(default=False, description="Whether this is a breaking change")

    def get_version(self) -> Version:
        """Parse version string to Version object."""
        return Version.from_string(self.version)


class ChainVersion(BaseModel):
    """
    Current chain version (stored in state).
    """
    version: str = Field(default="1.0.0", description="Current chain version")
    last_upgrade_height: int = Field(default=0, description="Height of last upgrade")
    next_upgrade: Optional[UpgradePlan] = Field(default=None, description="Scheduled upgrade")

    def get_version(self) -> Version:
        """Parse version string to Version object."""
        return Version.from_string(self.version)
