import hashlib
from typing import List

def sha256(data: bytes) -> bytes:
    """Returns SHA256 hash of bytes."""
    return hashlib.sha256(data).digest()

def sha256_hex(data: bytes) -> str:
    """Returns SHA256 hash of bytes as hex string."""
    return sha256(data).hex()

def double_sha256(data: bytes) -> bytes:
    """Returns SHA256(SHA256(data)). Used in Bitcoin-like structures."""
    return sha256(sha256(data))

def ripemd160(data: bytes) -> bytes:
    """Returns RIPEMD160 hash of bytes."""
    h = hashlib.new('ripemd160')
    h.update(data)
    return h.digest()

def merkle_root(hashes: List[bytes]) -> bytes:
    """Calculates Merkle Root for a list of hashes."""
    if not hashes:
        return b'\x00' * 32
    
    if len(hashes) == 1:
        return hashes[0]
    
    new_level = []
    for i in range(0, len(hashes), 2):
        left = hashes[i]
        right = hashes[i+1] if i+1 < len(hashes) else left
        new_level.append(sha256(left + right))
        
    return merkle_root(new_level)
