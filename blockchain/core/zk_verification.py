# MIT License
# Copyright (c) 2025 Hashborn

"""
ZK Proof Verification (On-Chain)

Verifies zero-knowledge proofs of miner weight calculations.

This module runs INSIDE the blockchain consensus.
It verifies proofs WITHOUT knowing the private inputs (GPU specs, uptime, etc).

Flow:
1. Miner submits: (weight, zk_proof, signature)
2. Blockchain verifies signature (data not tampered)
3. Blockchain verifies ZK proof (weight honestly calculated)
4. If valid → use weight for reward distribution
5. If invalid → reject, potentially slash miner
"""

import hashlib
import json
import logging
from typing import Tuple
from protocol.config.economic_model import ECONOMIC_CONFIG

logger = logging.getLogger(__name__)


class ZKVerificationError(Exception):
    """Raised when ZK proof verification fails."""
    pass


class ZKVerifier:
    """
    Verifies ZK proofs of miner weight calculations.

    This is the ON-CHAIN verification component.
    It must be deterministic and efficient (runs in consensus).
    """

    def __init__(self, economic_config=None):
        """
        Initialize ZK verifier.

        Args:
            economic_config: Economic configuration (defaults to ECONOMIC_CONFIG)
        """
        self.config = economic_config or ECONOMIC_CONFIG

    def verify_miner_weight_submission(
        self,
        miner_address: str,
        weight: float,
        proof_data: bytes,
        signature: bytes,
        public_key: bytes
    ) -> Tuple[bool, str]:
        """
        Verify complete miner weight submission.

        Performs three checks:
        1. Signature verification (authenticity)
        2. ZK proof verification (honest calculation)
        3. Sanity bounds check (weight within valid range)

        Args:
            miner_address: Miner's blockchain address
            weight: Claimed weight value
            proof_data: Serialized ZK proof
            signature: Cryptographic signature
            public_key: Miner's public key

        Returns:
            (is_valid, error_message)
        """
        try:
            # Step 1: Verify signature
            if not self._verify_signature(weight, proof_data, signature, public_key):
                return False, "Invalid signature"

            # Step 2: Verify ZK proof
            if not self._verify_zk_proof(weight, proof_data):
                return False, "Invalid ZK proof"

            # Step 3: Sanity check bounds
            if not self._check_weight_bounds(weight):
                return False, f"Weight {weight} outside valid range [{self.config.min_miner_weight}, {self.config.max_miner_weight}]"

            logger.info(f"Miner {miner_address} weight {weight} verified successfully")
            return True, ""

        except Exception as e:
            logger.error(f"Verification error for miner {miner_address}: {e}")
            return False, str(e)

    def _verify_signature(
        self,
        weight: float,
        proof_data: bytes,
        signature: bytes,
        public_key: bytes
    ) -> bool:
        """
        Verify cryptographic signature.

        STUB: Simple hash-based verification.
        TODO: Replace with real Ed25519 verification.

        Args:
            weight: Weight value
            proof_data: Proof bytes
            signature: Signature to verify
            public_key: Signer's public key

        Returns:
            True if signature is valid
        """
        # Reconstruct message (same format as signer)
        weight_bytes = str(weight).encode()
        message = weight_bytes + b"||" + proof_data

        # STUB verification (replace with real Ed25519)
        expected_sig = hashlib.sha512(public_key + message).digest()[:64]
        return signature == expected_sig

    def _verify_zk_proof(self, weight: float, proof_data: bytes) -> bool:
        """
        Verify zero-knowledge proof.

        STUB: Simple verification for development.
        TODO: Replace with real zk-SNARK/STARK verifier.

        In production:
        - Load verification key from circuit_hash
        - Verify proof cryptographically
        - Check public inputs match weight

        Args:
            weight: Public output (claimed weight)
            proof_data: Serialized ZK proof

        Returns:
            True if proof is valid
        """
        try:
            # Deserialize proof
            proof_obj = json.loads(proof_data.decode())

            # Check version matches
            if proof_obj.get("version") != self.config.weight_calculation_version:
                logger.warning(f"Version mismatch: {proof_obj.get('version')} != {self.config.weight_calculation_version}")
                return False

            # Check public output matches claimed weight
            public_output = proof_obj.get("public_output")
            if abs(public_output - weight) > 1e-6:
                logger.warning(f"Weight mismatch: {public_output} != {weight}")
                return False

            # STUB: In production, verify actual zk-SNARK proof here
            # Example with real ZK library:
            # verification_key = load_vk(self.config.zk_circuit_hash)
            # return verify_proof(verification_key, proof_obj["proof"], [weight])

            # For now, accept if format is correct
            return True

        except Exception as e:
            logger.error(f"ZK proof verification error: {e}")
            return False

    def _check_weight_bounds(self, weight: float) -> bool:
        """
        Check if weight is within valid bounds.

        Sanity check to prevent extreme values.

        Args:
            weight: Weight to check

        Returns:
            True if weight is within bounds
        """
        min_weight = self.config.min_miner_weight
        max_weight = self.config.max_miner_weight

        if weight < min_weight or weight > max_weight:
            logger.warning(f"Weight {weight} outside bounds [{min_weight}, {max_weight}]")
            return False

        return True


# Global verifier instance
zk_verifier = ZKVerifier()
