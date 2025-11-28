import bech32 # type: ignore
from .hash import sha256, ripemd160
from typing import Tuple, Optional

def address_from_pubkey(pub_bytes: bytes, prefix: str = "cpc") -> str:
    """Creates Bech32 address from public key."""
    sha = sha256(pub_bytes)
    h20 = ripemd160(sha) # 20 bytes
    
    # Convert to 5-bit words
    five_bit_r = bech32.convertbits(h20, 8, 5)
    if five_bit_r is None:
        raise ValueError("Error converting to bech32 words")
        
    return bech32.bech32_encode(prefix, five_bit_r)

def decode_address(addr: str) -> Tuple[str, bytes]:
    """Decodes Bech32 address to (prefix, h20_bytes)."""
    hrp, data = bech32.bech32_decode(addr)
    if hrp is None or data is None:
        raise ValueError("Invalid bech32 address")
    
    decoded = bech32.convertbits(data, 5, 8, False)
    if decoded is None:
        raise ValueError("Error converting from bech32 words")
        
    return hrp, bytes(decoded)

def is_valid_address(addr: str, expected_prefix: Optional[str] = None) -> bool:
    try:
        hrp, _ = decode_address(addr)
        if expected_prefix and hrp != expected_prefix:
            return False
        return True
    except ValueError:
        return False

