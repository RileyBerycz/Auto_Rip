from __future__ import annotations

import os
from glob import glob
from dataclasses import dataclass, field
from pathlib import Path


def _canonical_drive_key(path: str) -> str:
    p = Path(path)
    try:
        return str(p.resolve(strict=False))
    except OSError:
        return str(p)


def discover_optical_drives() -> list[str]:
    """Detect common Linux optical drive device nodes in stable order."""
    candidates = set(glob("/dev/sr*"))
    for alias in ("/dev/cdrom", "/dev/dvd"):
        if Path(alias).exists():
            candidates.add(alias)

    canonical_to_drive: dict[str, str] = {}
    for drive in sorted(candidates):
        if not Path(drive).exists():
            continue

        key = _canonical_drive_key(drive)
        current = canonical_to_drive.get(key)
        # Prefer canonical /dev/sr* names over aliases like /dev/cdrom.
        if current is None or (not current.startswith("/dev/sr") and drive.startswith("/dev/sr")):
            canonical_to_drive[key] = drive

    return sorted(canonical_to_drive.values())


def parse_drives(value: str | None) -> list[str]:
    def _normalize(drives: list[str]) -> list[str]:
        canonical_to_drive: dict[str, str] = {}
        for drive in drives:
            if not drive:
                continue
            key = _canonical_drive_key(drive)
            current = canonical_to_drive.get(key)
            # Prefer /dev/sr* over aliases for display and job identity.
            if current is None or (not current.startswith("/dev/sr") and drive.startswith("/dev/sr")):
                canonical_to_drive[key] = drive
        return sorted(canonical_to_drive.values())

    if value is None:
        return discover_optical_drives() or ["/dev/sr0", "/dev/sr1", "/dev/sr2"]

    parsed = [d.strip() for d in value.split(",") if d.strip()]
    if parsed:
        return _normalize(parsed)

    # Blank value in env or UI means "auto-detect".
    return discover_optical_drives()


@dataclass(slots=True)
class Settings:
    movies_path: Path = Path(os.getenv("MOVIES_PATH", "/media/dvdflix/movies"))
    tv_path: Path = Path(os.getenv("TV_PATH", "/media/dvdflix/tvshows"))
    temp_rip_path: Path = Path(os.getenv("TEMP_RIP_PATH", "/media/dvdflix/tmp"))
    drives: list[str] = field(
        default_factory=lambda: parse_drives(os.getenv("DRIVES"))
    )
    tmdb_api_key: str = os.getenv("TMDB_API_KEY", "")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    runtime_tolerance_minutes: int = int(os.getenv("RUNTIME_TOLERANCE_MINUTES", "8"))
    max_identify_workers: int = int(os.getenv("MAX_IDENTIFY_WORKERS", "1"))
    disc_cache_db: Path = Path(os.getenv("DISC_CACHE_DB", "data/disc_cache.db"))
    omdb_api_key: str = os.getenv("OMDB_API_KEY", "")
    tvdb_api_key: str = os.getenv("TVDB_API_KEY", "")
    tvdb_pin: str = os.getenv("TVDB_PIN", "")
    identify_min_confidence: int = int(os.getenv("IDENTIFY_MIN_CONFIDENCE", "80"))
    opensubtitles_api_key: str = os.getenv("OPENSUBTITLES_API_KEY", "")
    enable_web_search: bool = os.getenv("ENABLE_WEB_SEARCH", "false").lower() == "true"
    searxng_url: str = os.getenv("SEARXNG_URL", "")
    handbrake_preset: str = os.getenv("HANDBRAKE_PRESET", "default")
    makemkvcon_path: str = os.getenv("MAKEMKVCON_PATH", "makemkvcon")

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
        _set_int("identify_min_confidence", "IDENTIFY_MIN_CONFIDENCE")

        drives = overrides.get("DRIVES")
        if drives is not None:
            settings.drives = parse_drives(drives)

        if overrides.get("TMDB_API_KEY") is not None:
            settings.tmdb_api_key = overrides.get("TMDB_API_KEY", "")
        if overrides.get("OLLAMA_URL"):
            settings.ollama_url = overrides["OLLAMA_URL"]
        if overrides.get("OLLAMA_MODEL"):
            settings.ollama_model = overrides["OLLAMA_MODEL"]
        if overrides.get("OMDB_API_KEY") is not None:
            settings.omdb_api_key = overrides.get("OMDB_API_KEY", "")
        if overrides.get("TVDB_API_KEY") is not None:
            settings.tvdb_api_key = overrides.get("TVDB_API_KEY", "")
        if overrides.get("TVDB_PIN") is not None:
            settings.tvdb_pin = overrides.get("TVDB_PIN", "")
        if overrides.get("OPENSUBTITLES_API_KEY") is not None:
            settings.opensubtitles_api_key = overrides.get("OPENSUBTITLES_API_KEY", "")
        if overrides.get("ENABLE_WEB_SEARCH") is not None:
            settings.enable_web_search = overrides.get("ENABLE_WEB_SEARCH", "").lower() == "true"
        if overrides.get("SEARXNG_URL"):
            settings.searxng_url = overrides["SEARXNG_URL"]
        if overrides.get("HANDBRAKE_PRESET"):
            settings.handbrake_preset = overrides["HANDBRAKE_PRESET"]
        if overrides.get("MAKEMKVCON_PATH"):
            settings.makemkvcon_path = overrides["MAKEMKVCON_PATH"]

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
            "OMDB_API_KEY": self.omdb_api_key,
            "TVDB_API_KEY": self.tvdb_api_key,
            "TVDB_PIN": self.tvdb_pin,
            "IDENTIFY_MIN_CONFIDENCE": str(self.identify_min_confidence),
            "OPENSUBTITLES_API_KEY": self.opensubtitles_api_key,
            "ENABLE_WEB_SEARCH": "true" if self.enable_web_search else "false",
            "SEARXNG_URL": self.searxng_url,
            "HANDBRAKE_PRESET": self.handbrake_preset,
            "MAKEMKVCON_PATH": self.makemkvcon_path,
        }

    def ensure_dirs(self) -> None:
        self.movies_path.mkdir(parents=True, exist_ok=True)
        self.tv_path.mkdir(parents=True, exist_ok=True)
        self.temp_rip_path.mkdir(parents=True, exist_ok=True)
        self.disc_cache_db.parent.mkdir(parents=True, exist_ok=True)
