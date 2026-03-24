from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import IdentificationResult


class DiscCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
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
                CREATE TABLE IF NOT EXISTS disc_cache (
                    disc_label TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, disc_label: str) -> IdentificationResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM disc_cache WHERE disc_label = ?", (disc_label,)
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload"])
        return IdentificationResult(**payload)

    def set(self, disc_label: str, result: IdentificationResult) -> None:
        payload = json.dumps(
            {
                "media_type": result.media_type,
                "title": result.title,
                "year": result.year,
                "confidence": result.confidence,
                "season": result.season,
                "episodes": result.episodes,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO disc_cache (disc_label, payload)
                VALUES (?, ?)
                ON CONFLICT(disc_label) DO UPDATE SET payload = excluded.payload
                """,
                (disc_label, payload),
            )
