from __future__ import annotations

import hashlib
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
            # Main disc label to identification result cache
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disc_cache (
                    disc_label TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            # Disc hash tracking for deduplication and re-insertion detection
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disc_history (
                    disc_hash TEXT PRIMARY KEY,
                    disc_label TEXT,
                    title TEXT,
                    year TEXT,
                    media_type TEXT,
                    ripped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
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
    
    @staticmethod
    def compute_disc_hash(disc_label: str, track_count: int, duration_seconds: int) -> str:
        """
        Compute a hash of disc metadata for deduplication.
        Uses disc_label + track_count + total_duration as fingerprint.
        """
        fingerprint = f"{disc_label}:{track_count}:{duration_seconds}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()
    
    def record_disc_rip(
        self, 
        disc_hash: str, 
        disc_label: str, 
        title: str, 
        year: str, 
        media_type: str,
        notes: str = ""
    ) -> None:
        """Record that a disc has been ripped to prevent re-ripping on re-insertion."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO disc_history (disc_hash, disc_label, title, year, media_type, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (disc_hash, disc_label, title, year, media_type, notes),
            )
    
    def has_been_ripped(self, disc_hash: str) -> dict[str, str] | None:
        """Check if disc hash was previously ripped. Returns rip history or None."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT disc_label, title, year, media_type, ripped_at 
                FROM disc_history WHERE disc_hash = ?
                """,
                (disc_hash,),
            ).fetchone()
        if not row:
            return None
        return {
            "disc_label": row["disc_label"],
            "title": row["title"],
            "year": row["year"],
            "media_type": row["media_type"],
            "ripped_at": row["ripped_at"],
        }
