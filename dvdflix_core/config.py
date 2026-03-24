from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    movies_path: Path = Path(os.getenv("MOVIES_PATH", "/media/dvdflix/movies"))
    tv_path: Path = Path(os.getenv("TV_PATH", "/media/dvdflix/tvshows"))
    temp_rip_path: Path = Path(os.getenv("TEMP_RIP_PATH", "/media/dvdflix/tmp"))
    drives: list[str] = field(
        default_factory=lambda: [d.strip() for d in os.getenv("DRIVES", "/dev/sr0,/dev/sr1,/dev/sr2").split(",") if d.strip()]
    )
    tmdb_api_key: str = os.getenv("TMDB_API_KEY", "")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    runtime_tolerance_minutes: int = int(os.getenv("RUNTIME_TOLERANCE_MINUTES", "8"))
    max_identify_workers: int = int(os.getenv("MAX_IDENTIFY_WORKERS", "1"))
    disc_cache_db: Path = Path(os.getenv("DISC_CACHE_DB", "data/disc_cache.db"))

    def ensure_dirs(self) -> None:
        self.movies_path.mkdir(parents=True, exist_ok=True)
        self.tv_path.mkdir(parents=True, exist_ok=True)
        self.temp_rip_path.mkdir(parents=True, exist_ok=True)
        self.disc_cache_db.parent.mkdir(parents=True, exist_ok=True)
