from ecdsa import SigningKey, VerifyingKey, SECP256k1 # type: ignore
import os
from typing import Tuple
from .hash import sha256

def generate_private_key() -> bytes:
    """Generates a random 32-byte private key."""
    return os.urandom(32)

def public_key_from_private(priv_bytes: bytes) -> bytes:
    """Returns compressed 33-byte public key from private key."""
    sk = SigningKey.from_string(priv_bytes, curve=SECP256k1)
    vk = sk.get_verifying_key()
    return vk.to_string("compressed")

def sign(message_hash: bytes, priv_bytes: bytes) -> bytes:
    """Signs a message hash with private key. Returns 64-byte (r,s) signature."""
    sk = SigningKey.from_string(priv_bytes, curve=SECP256k1)
    # sigencode_string returns 64 bytes (32 bytes r + 32 bytes s)
    signature = sk.sign_digest(message_hash, sigencode=lambda r, s, order: r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return signature

def verify(message_hash: bytes, signature: bytes, pub_bytes: bytes) -> bool:
    """Verifies ECDSA signature."""
    try:
        vk = VerifyingKey.from_string(pub_bytes, curve=SECP256k1)
        # sigdecode_string expects 64 bytes
        return vk.verify_digest(signature, message_hash, sigdecode=lambda sig, order: (int.from_bytes(sig[:32], 'big'), int.from_bytes(sig[32:], 'big')))
    except Exception:
        return False

