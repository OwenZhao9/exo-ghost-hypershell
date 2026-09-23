"""Local product data. Each worktree has its own database by default."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, started REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
                    payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def sessions(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM sessions ORDER BY started DESC, id")]

    def add_session(self, value: dict) -> bool:
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO sessions VALUES (?, ?, ?)",
                              (value['id'], value['started_at'],
                               json.dumps(value, ensure_ascii=False, allow_nan=False))).rowcount == 1

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                       (key, payload))
