import os
import json
import time
import re
import stat
from typing import List, Dict, Optional
from ..protocol.crypto.keys import generate_private_key, public_key_from_private
from ..protocol.crypto.addresses import address_from_pubkey

KEYSTORE_DIR = os.path.expanduser("~/.computechain/keys")

class KeyStore:
    def __init__(self, root_dir: str = KEYSTORE_DIR):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, mode=0o700, exist_ok=True)

    def _key_path(self, name: str) -> str:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise ValueError("Key name must be 1-64 safe filename characters")
        return os.path.join(self.root_dir, f"{name}.json")

    def create_key(self, name: str) -> Dict[str, str]:
        """Generates and saves a new key."""
        if self.get_key(name):
            raise ValueError(f"Key '{name}' already exists")

        priv = generate_private_key()
        pub = public_key_from_private(priv)
        addr = address_from_pubkey(pub)

        key_data = {
            "name": name,
            "address": addr,
            "public_key": pub.hex(),
            "private_key": priv.hex(), # TODO: Encrypt this!
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        self._save_key_file(name, key_data)
        return key_data

    def import_key(self, name: str, private_key_hex: str) -> Dict[str, str]:
        """Imports an existing private key."""
        if self.get_key(name):
            raise ValueError(f"Key '{name}' already exists")
            
        try:
            priv = bytes.fromhex(private_key_hex)
            if len(priv) != 32:
                raise ValueError("Invalid private key length")
        except ValueError:
            raise ValueError("Invalid hex string")

        pub = public_key_from_private(priv)
        addr = address_from_pubkey(pub)

        key_data = {
            "name": name,
            "address": addr,
            "public_key": pub.hex(),
            "private_key": priv.hex(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        
        self._save_key_file(name, key_data)
        return key_data

    def get_key(self, name: str) -> Optional[Dict[str, str]]:
        """Loads key by name."""
        path = self._key_path(name)
        if not os.path.exists(path):
            return None
        
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r") as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    return None
                raw = f.read(16385)
                if len(raw) > 16384:
                    return None
                return json.loads(raw)
        except Exception:
            return None

    def list_keys(self) -> List[Dict[str, str]]:
        """Lists all available keys (without private info)."""
        keys = []
        if not os.path.exists(self.root_dir):
            return []
            
        for filename in os.listdir(self.root_dir):
            if filename.endswith(".json"):
                data = self.get_key(filename[:-5])
                if data:
                    # Return safe view
                    keys.append({
                        "name": data["name"],
                        "address": data["address"],
                        "public_key": data["public_key"]
                    })
        return keys
    
    def delete_key(self, name: str) -> bool:
        path = self._key_path(name)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def _save_key_file(self, name: str, data: Dict[str, str]):
        path = self._key_path(name)
        raw = json.dumps(data, indent=2)
        # Permissions apply at creation, not after secrets were exposed by umask.
        # O_EXCL also rejects existing/corrupt files and symlinks without overwriting.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
