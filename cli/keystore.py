import os
import json
import time
from typing import List, Dict, Optional
from ..protocol.crypto.keys import generate_private_key, public_key_from_private
from ..protocol.crypto.addresses import address_from_pubkey

KEYSTORE_DIR = os.path.expanduser("~/.computechain/keys")

class KeyStore:
    def __init__(self, root_dir: str = KEYSTORE_DIR):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

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
        path = os.path.join(self.root_dir, f"{name}.json")
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, "r") as f:
                return json.load(f)
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
        path = os.path.join(self.root_dir, f"{name}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def _save_key_file(self, name: str, data: Dict[str, str]):
        path = os.path.join(self.root_dir, f"{name}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        # Secure permissions
        os.chmod(path, 0o600)

