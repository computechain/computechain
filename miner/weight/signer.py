# MIT License
# Copyright (c) 2025 Hashborn

"""
Cryptographic Signer for Miner Weight

Signs miner weight + ZK proof with miner's private key.
Blockchain verifies signature to ensure data wasn't tampered with.

Flow:
1. Miner calculates weight
2. Miner generates ZK proof
3. Miner signs (weight + proof) with private key
4. Blockchain verifies signature with miner's public key
"""

import hashlib
from typing import Tuple
from .prover import ZKProof


class WeightSigner:
    """
    Signs miner weight data with cryptographic signature.

    Uses Ed25519 signature scheme (same as validator signatures).
    """

    def __init__(self, private_key: bytes):
        """
        Initialize signer with miner's private key.

        Args:
            private_key: Miner's Ed25519 private key (32 bytes)
        """
        self.private_key = private_key

    def sign_weight(self, weight: float, proof: ZKProof) -> bytes:
        """
        Sign weight and ZK proof.

        Creates signature over (weight + proof) to prevent tampering.

        Args:
            weight: Calculated miner weight
            proof: ZK proof of honest calculation

        Returns:
            Signature bytes (64 bytes for Ed25519)
        """
        # Serialize data to sign
        message = self._prepare_message(weight, proof)

        # Sign with private key
        # TODO: Use actual Ed25519 signing (e.g., from cryptography library)
        # For now, simple hash-based signature (STUB)
        signature = self._sign_stub(message)

        return signature

    def _prepare_message(self, weight: float, proof: ZKProof) -> bytes:
        """
        Prepare message to sign.

        Format: weight || proof_data || version
        """
        weight_bytes = str(weight).encode()
        proof_bytes = proof.serialize()
        version_bytes = proof.version.encode()

        message = weight_bytes + b"||" + proof_bytes + b"||" + version_bytes
        return message

    def _sign_stub(self, message: bytes) -> bytes:
        """
        STUB: Simple hash-based signature.

        In production: Replace with real Ed25519 signature.

        Example with real crypto:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            signature = self.private_key.sign(message)
        """
        # Hash message with private key (STUB - not secure!)
        data = self.private_key + message
        sig_hash = hashlib.sha512(data).digest()
        return sig_hash[:64]  # Ed25519 signatures are 64 bytes

    @staticmethod
    def verify_signature(
        weight: float,
        proof: ZKProof,
        signature: bytes,
        public_key: bytes
    ) -> bool:
        """
        Verify signature (blockchain-side verification).

        Args:
            weight: Claimed weight
            proof: ZK proof
            signature: Signature to verify
            public_key: Miner's public key

        Returns:
            True if signature is valid
        """
        # Prepare message (same as signing)
        weight_bytes = str(weight).encode()
        proof_bytes = proof.serialize()
        version_bytes = proof.version.encode()
        message = weight_bytes + b"||" + proof_bytes + b"||" + version_bytes

        # Verify signature
        # TODO: Use actual Ed25519 verification
        # For now, STUB verification
        return WeightSigner._verify_stub(message, signature, public_key)

    @staticmethod
    def _verify_stub(message: bytes, signature: bytes, public_key: bytes) -> bool:
        """
        STUB: Simple hash-based verification.

        In production: Replace with real Ed25519 verification.

        Example with real crypto:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            public_key_obj.verify(signature, message)
        """
        # Hash message with public key (STUB)
        expected_sig = hashlib.sha512(public_key + message).digest()[:64]
        return signature == expected_sig
