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

    @classmethod
    def from_overrides(cls, overrides: dict[str, str] | None) -> "Settings":
        settings = cls()
        if not overrides:
            return settings

        def _set_path(field_name: str, key: str) -> None:
            value = overrides.get(key)
            if value:
                setattr(settings, field_name, Path(value))

        def _set_int(field_name: str, key: str) -> None:
            value = overrides.get(key)
            if value:
                try:
                    setattr(settings, field_name, int(value))
                except ValueError:
                    pass

        _set_path("movies_path", "MOVIES_PATH")
        _set_path("tv_path", "TV_PATH")
        _set_path("temp_rip_path", "TEMP_RIP_PATH")
        _set_path("disc_cache_db", "DISC_CACHE_DB")
        _set_int("runtime_tolerance_minutes", "RUNTIME_TOLERANCE_MINUTES")
        _set_int("max_identify_workers", "MAX_IDENTIFY_WORKERS")

        drives = overrides.get("DRIVES")
        if drives is not None:
            settings.drives = [d.strip() for d in drives.split(",") if d.strip()]

        if overrides.get("TMDB_API_KEY") is not None:
            settings.tmdb_api_key = overrides.get("TMDB_API_KEY", "")
        if overrides.get("OLLAMA_URL"):
            settings.ollama_url = overrides["OLLAMA_URL"]
        if overrides.get("OLLAMA_MODEL"):
            settings.ollama_model = overrides["OLLAMA_MODEL"]

        return settings

    def to_runtime_dict(self) -> dict[str, str]:
        return {
            "MOVIES_PATH": str(self.movies_path),
            "TV_PATH": str(self.tv_path),
            "TEMP_RIP_PATH": str(self.temp_rip_path),
            "DRIVES": ",".join(self.drives),
            "TMDB_API_KEY": self.tmdb_api_key,
            "OLLAMA_URL": self.ollama_url,
            "OLLAMA_MODEL": self.ollama_model,
            "RUNTIME_TOLERANCE_MINUTES": str(self.runtime_tolerance_minutes),
            "MAX_IDENTIFY_WORKERS": str(self.max_identify_workers),
            "DISC_CACHE_DB": str(self.disc_cache_db),
        }

    def ensure_dirs(self) -> None:
        self.movies_path.mkdir(parents=True, exist_ok=True)
        self.tv_path.mkdir(parents=True, exist_ok=True)
        self.temp_rip_path.mkdir(parents=True, exist_ok=True)
        self.disc_cache_db.parent.mkdir(parents=True, exist_ok=True)
