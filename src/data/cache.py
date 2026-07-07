"""SQLite caching layer to avoid redundant API calls."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "cache.db"


class Cache:
    """Simple SQLite cache for stock data."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)
            """)

    def get(self, key: str) -> str | None:
        """Get cached value. Returns None if missing or expired."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row:
                value, expires = row
                if datetime.fromisoformat(expires) > datetime.now():
                    return value
                # Expired — delete it
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
        return None

    def set(self, key: str, value: str, ttl_minutes: int = 60):
        """Cache a value with TTL in minutes."""
        expires_at = datetime.now() + timedelta(minutes=ttl_minutes)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, expires_at.isoformat()),
            )
            conn.commit()

    def cache_dataframe(self, key: str, df: pd.DataFrame, ttl_minutes: int = 60):
        """Cache a DataFrame as JSON."""
        self.set(key, df.to_json(date_format="iso"), ttl_minutes)

    def get_dataframe(self, key: str) -> pd.DataFrame | None:
        """Retrieve cached DataFrame."""
        raw = self.get(key)
        if raw:
            return pd.read_json(raw)
        return None

    def clear_expired(self):
        """Remove all expired entries."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM cache WHERE expires_at < ?", (datetime.now().isoformat(),))
            conn.commit()


cache = Cache()
