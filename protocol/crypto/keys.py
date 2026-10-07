from ecdsa import SigningKey, VerifyingKey, SECP256k1 # type: ignore
import os
from typing import Tuple
from .hash import sha256
from ecdsa.util import sigencode_string_canonize, sigdecode_string

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
    signature = sk.sign_digest_deterministic(message_hash, sigencode=sigencode_string_canonize)
    return signature

def verify(message_hash: bytes, signature: bytes, pub_bytes: bytes) -> bool:
    """Verifies ECDSA signature."""
    try:
        if len(message_hash) != 32 or len(signature) != 64 or len(pub_bytes) != 33 or pub_bytes[0] not in (2, 3):
            return False
        r, s = sigdecode_string(signature, SECP256k1.order)
        if not 0 < r < SECP256k1.order or not 0 < s <= SECP256k1.order // 2:
            return False
        vk = VerifyingKey.from_string(pub_bytes, curve=SECP256k1)
        # sigdecode_string expects 64 bytes
        return vk.verify_digest(signature, message_hash, sigdecode=sigdecode_string)
    except Exception:
        return False
