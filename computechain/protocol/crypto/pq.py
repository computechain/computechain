from .keys import sign as secp_sign, verify as secp_verify

# PQ Constants
SCHEME_ID = 1  # 1 = Dilithium3 (Mock), 2 = Falcon512, etc.

def sign(msg_bytes: bytes, priv_key_bytes: bytes) -> bytes:
    """
    Signs the message using the Post-Quantum scheme.
    For Devnet/MVP, we wrap secp256k1.
    """
    # In real PQ, this would use Dilithium/Falcon
    return secp_sign(msg_bytes, priv_key_bytes)

def verify(msg_bytes: bytes, sig_bytes: bytes, pub_key_bytes: bytes) -> bool:
    """
    Verifies the PQ signature.
    """
    # In real PQ, this would use Dilithium/Falcon verify
    return secp_verify(msg_bytes, sig_bytes, pub_key_bytes)

