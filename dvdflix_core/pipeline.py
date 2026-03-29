from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path

from .clients import OllamaClient, TmdbClient
from .config import Settings
from .disc_cache import DiscCache
from .identifier import DiscIdentifier
from .lsdvd_parser import scan_disc
from .models import JobState, RipJob
from .ripper import build_output_dir, run_makemkv


class RipPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.cache = DiscCache(settings.disc_cache_db)
        self.identifier = DiscIdentifier(
            cache=self.cache,
            ollama=OllamaClient(settings.ollama_url, settings.ollama_model),
            tmdb=TmdbClient(settings.tmdb_api_key),
            runtime_tolerance=settings.runtime_tolerance_minutes,
            omdb_api_key=settings.omdb_api_key,
            tvdb_api_key=settings.tvdb_api_key,
            tvdb_pin=settings.tvdb_pin,
            identify_min_confidence=settings.identify_min_confidence,
            opensubtitles_api_key=settings.opensubtitles_api_key,
            enable_web_search=settings.enable_web_search,
            searxng_url=settings.searxng_url,
        )
        self.identify_lock = threading.Lock()

    def run_for_drive(self, drive: str) -> RipJob:
        job = RipJob(id=str(uuid.uuid4()), drive=drive, state=JobState.pending)
        try:
            disc = scan_disc(drive)
            job.disc_label = disc.label
            job.state = JobState.identifying
            job.updated_at = datetime.utcnow()

            # Keep identification serialized to avoid GPU contention in Ollama.
            with self.identify_lock:
                identified = self.identifier.identify(disc)

            job.title = identified.title
            job.media_type = identified.media_type
            job.state = JobState.ripping
            job.updated_at = datetime.utcnow()

            target_root: Path = self.settings.movies_path
            if identified.media_type == "tv":
                target_root = self.settings.tv_path

            output_dir = build_output_dir(target_root, identified.title, identified.year)
            ok, message = run_makemkv(
                drive,
                output_dir,
                makemkvcon_path=self.settings.makemkvcon_path,
            )
            if not ok:
                job.state = JobState.failed
                job.error = message
            else:
                job.state = JobState.complete
                job.output_path = str(output_dir)
                total_seconds = int(sum(track.duration_minutes * 60 for track in disc.tracks))
                disc_hash = self.cache.compute_disc_hash(disc.label, len(disc.tracks), total_seconds)
                self.cache.record_disc_rip(
                    disc_hash=disc_hash,
                    disc_label=disc.label,
                    title=identified.title,
                    year=str(identified.year or ""),
                    media_type=identified.media_type,
                    drive=drive,
                    output_path=str(output_dir),
                )

            job.updated_at = datetime.utcnow()
            return job
        except Exception as exc:  # noqa: BLE001
            job.state = JobState.failed
            job.error = str(exc)
            job.updated_at = datetime.utcnow()
            return job
