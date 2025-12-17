# MIT License
# Copyright (c) 2025 Hashborn

"""
Snapshot Data Structures (Phase 1.3)
"""

from pydantic import BaseModel, Field
from typing import Dict, Optional
from datetime import datetime


class SnapshotMetadata(BaseModel):
    """
    Snapshot metadata (stored separately for quick querying).
    """
    version: str = Field(default="1.0.0", description="Snapshot format version")
    network_id: str = Field(..., description="Network ID (devnet/testnet/mainnet)")
    height: int = Field(..., description="Block height at snapshot")
    epoch_index: int = Field(..., description="Epoch index at snapshot")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    accounts_count: int = Field(..., description="Number of accounts")
    validators_count: int = Field(..., description="Number of validators")
    total_supply: int = Field(..., description="Total token supply")
    total_burned: int = Field(..., description="Total tokens burned")
    total_minted: int = Field(..., description="Total tokens minted")
    hash: str = Field(..., description="SHA256 hash of snapshot data")
    compressed_size: int = Field(..., description="Compressed file size (bytes)")
    uncompressed_size: int = Field(..., description="Uncompressed data size (bytes)")


class Snapshot(BaseModel):
    """
    Complete state snapshot (saved to disk, compressed).
    """
    # Metadata
    version: str = Field(default="1.0.0", description="Snapshot format version")
    network_id: str = Field(..., description="Network ID")
    height: int = Field(..., description="Block height")
    epoch_index: int = Field(..., description="Epoch index")
    timestamp: str = Field(..., description="ISO 8601 timestamp")

    # Economic tracking
    total_burned: int = Field(default=0, description="Total tokens burned")
    total_minted: int = Field(default=0, description="Total tokens minted")

    # State data (serialized accounts/validators as JSON strings for efficiency)
    accounts: Dict[str, str] = Field(default_factory=dict, description="address -> Account JSON")
    validators: Dict[str, str] = Field(default_factory=dict, description="address -> Validator JSON")

    # Verification
    hash: Optional[str] = Field(default=None, description="SHA256 hash of snapshot (excluding this field)")

    def calculate_hash(self) -> str:
        """
        Calculate SHA256 hash of snapshot data (excluding hash field).
        """
        from ...protocol.crypto.hash import sha256_hex
        import json

        # Create dict without hash field
        data = self.model_dump(exclude={"hash"})

        # Sort keys for deterministic hashing
        canonical_json = json.dumps(data, sort_keys=True, separators=(',', ':'))

        return sha256_hex(canonical_json.encode())

    def verify_hash(self) -> bool:
        """
        Verify snapshot hash matches computed hash.
        """
        if not self.hash:
            return False

        return self.calculate_hash() == self.hash
