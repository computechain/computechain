import sqlite3
import threading
from typing import Optional, Tuple, Dict

class StorageDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            # Blocks table: stores full JSON body
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocks (
                    height INTEGER PRIMARY KEY,
                    hash TEXT UNIQUE,
                    data TEXT
                )
            ''')
            # Index by hash for fast lookup
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS block_index (
                    hash TEXT PRIMARY KEY,
                    height INTEGER
                )
            ''')
            # State table: Key-Value store for account state
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            self.conn.commit()

    def save_block(self, height: int, block_hash: str, data: str):
        with self._lock:
            self.cursor.execute('INSERT OR REPLACE INTO blocks (height, hash, data) VALUES (?, ?, ?)', (height, block_hash, data))
            self.cursor.execute('INSERT OR REPLACE INTO block_index (hash, height) VALUES (?, ?)', (block_hash, height))
            self.conn.commit()

    def get_block_by_height(self, height: int) -> Optional[str]:
        with self._lock:
            self.cursor.execute('SELECT data FROM blocks WHERE height = ?', (height,))
            row = self.cursor.fetchone()
            return row[0] if row else None

    def get_block_by_hash(self, block_hash: str) -> Optional[str]:
        with self._lock:
            self.cursor.execute('SELECT data FROM blocks WHERE hash = ?', (block_hash,))
            row = self.cursor.fetchone()
            return row[0] if row else None

    def get_last_block(self) -> Optional[Tuple[int, str, str]]:
        """Returns (height, hash, data) of the last block."""
        with self._lock:
            self.cursor.execute('SELECT height, hash, data FROM blocks ORDER BY height DESC LIMIT 1')
            row = self.cursor.fetchone()
            return row if row else None

    def delete_block(self, height: int):
        with self._lock:
            # 1. Get hash to delete from index
            self.cursor.execute("SELECT hash FROM blocks WHERE height=?", (height,))
            row = self.cursor.fetchone()
            if row:
                block_hash = row[0]
                # 2. Delete from blocks table
                self.cursor.execute("DELETE FROM blocks WHERE height=?", (height,))
                # 3. Delete from index
                self.cursor.execute("DELETE FROM block_index WHERE hash=?", (block_hash,))
                self.conn.commit()

    # --- State Methods ---
    def get_state(self, key: str) -> Optional[str]:
        with self._lock:
            self.cursor.execute('SELECT value FROM state WHERE key = ?', (key,))
            row = self.cursor.fetchone()
            return row[0] if row else None

    def set_state(self, key: str, value: str):
        with self._lock:
            self.cursor.execute('INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)', (key, value))
            self.conn.commit()
            
    def get_state_by_prefix(self, prefix: str) -> Dict[str, str]:
        with self._lock:
            self.cursor.execute('SELECT key, value FROM state WHERE key LIKE ?', (f"{prefix}%",))
            return {row[0]: row[1] for row in self.cursor.fetchall()}

    def clear_state(self):
        with self._lock:
            self.cursor.execute('DELETE FROM state')
            self.conn.commit()
