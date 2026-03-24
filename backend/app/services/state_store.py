from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path


class StateStore:
    def __init__(self, db_path: str = "/app/data/app_state.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_setting(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_settings(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        marks = ",".join("?" for _ in keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({marks})", keys
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def upsert_settings(self, values: dict[str, str]) -> None:
        if not values:
            return
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )

    def is_setup_complete(self) -> bool:
        with self._connect() as conn:
            user_count = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            setup = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'SETUP_COMPLETE'"
            ).fetchone()
        return bool(user_count > 0 and setup and setup["value"] == "true")

    def create_admin(self, username: str, password: str) -> None:
        if not username or not password:
            raise ValueError("username and password are required")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")

        salt = secrets.token_hex(16)
        pwd_hash = self._hash_password(password, salt)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, is_admin) VALUES (?, ?, ?, 1)",
                (username, pwd_hash, salt),
            )
        self.set_setting("SETUP_COMPLETE", "true")

    def login(self, username: str, password: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash, salt FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None

        expected = row["password_hash"]
        actual = self._hash_password(password, row["salt"])
        if not hmac.compare_digest(expected, actual):
            return None

        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO auth_tokens (token_hash, user_id) VALUES (?, ?)",
                (token_hash, int(row["id"])),
            )
        return token

    def validate_token(self, token: str) -> bool:
        if not token:
            return False
        token_hash = self._hash_token(token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash FROM auth_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return bool(row)

    def _hash_password(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
        ).hex()

    def _hash_token(self, token: str) -> str:
        secret = os.getenv("DVD_FLIX_TOKEN_SECRET", "dvdflix-dev-secret")
        return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
