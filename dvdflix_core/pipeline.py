from __future__ import annotations

import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

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

    def run_for_drive(
        self,
        drive: str,
        progress_cb: Callable[[str, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        job_id: str | None = None,
    ) -> RipJob:
        job = RipJob(id=job_id or str(uuid.uuid4()), drive=drive, state=JobState.pending)
        try:
            if should_cancel and should_cancel():
                job.state = JobState.canceled
                job.progress = 100
                if progress_cb:
                    progress_cb(JobState.canceled.value, 100, "Cancelled before scan")
                return job

            if progress_cb:
                progress_cb(JobState.pending.value, 5, f"Starting scan for {drive}")
            disc = scan_disc(drive)
            job.disc_label = disc.label
            job.state = JobState.identifying
            job.updated_at = datetime.utcnow()
            if progress_cb:
                progress_cb(JobState.identifying.value, 25, f"Disc label detected: {disc.label}")

            if should_cancel and should_cancel():
                job.state = JobState.canceled
                job.progress = 100
                if progress_cb:
                    progress_cb(JobState.canceled.value, 100, "Cancelled during identification")
                return job

            # Keep identification serialized to avoid GPU contention in Ollama.
            with self.identify_lock:
                identified = self.identifier.identify(disc)

            confidence_pct = int(round(float(identified.confidence or 0.0) * 100))
            needs_manual_review = confidence_pct < int(self.settings.identify_min_confidence)

            job.title = identified.title
            job.media_type = identified.media_type
            job.state = JobState.ripping
            job.updated_at = datetime.utcnow()
            if progress_cb:
                progress_cb(
                    JobState.ripping.value,
                    55,
                    f"Identified as {identified.media_type}: {identified.title} ({confidence_pct}% confidence)",
                )

            target_root: Path = self.settings.movies_path
            if identified.media_type == "tv":
                target_root = self.settings.tv_path

            # Rip into temp first; only move to library after successful completion.
            temp_title = f"{identified.title} [{job.id[:8]}]"
            temp_output_dir = build_output_dir(self.settings.temp_rip_path, temp_title, identified.year)
            if progress_cb:
                progress_cb(JobState.ripping.value, 58, f"Ripping to temp path: {temp_output_dir}")
            ok, message, cancelled = run_makemkv(
                drive,
                temp_output_dir,
                makemkvcon_path=self.settings.makemkvcon_path,
                should_cancel=should_cancel,
                log_cb=(lambda line: progress_cb(JobState.ripping.value, 70, line)) if progress_cb else None,
            )
            if cancelled:
                job.state = JobState.canceled
                job.error = message
                shutil.rmtree(temp_output_dir, ignore_errors=True)
                if progress_cb:
                    progress_cb(JobState.canceled.value, 100, "Cancelled; partial output cleaned")
            elif not ok:
                job.state = JobState.failed
                job.error = message
                shutil.rmtree(temp_output_dir, ignore_errors=True)
                if progress_cb:
                    progress_cb(JobState.failed.value, 100, f"Rip failed: {message}")
            else:
                if needs_manual_review:
                    job.state = JobState.needs_review
                    job.output_path = str(temp_output_dir)
                    job.progress = 100
                    job.error = (
                        f"Identification confidence {confidence_pct}% is below threshold "
                        f"{self.settings.identify_min_confidence}%. Awaiting manual identification."
                    )
                    if progress_cb:
                        progress_cb(
                            JobState.needs_review.value,
                            100,
                            f"Rip complete to temp: {temp_output_dir}. Awaiting manual identification.",
                        )
                else:
                    output_dir = build_output_dir(target_root, identified.title, identified.year)
                    for child in temp_output_dir.iterdir():
                        shutil.move(str(child), str(output_dir / child.name))
                    shutil.rmtree(temp_output_dir, ignore_errors=True)

                    job.state = JobState.complete
                    job.output_path = str(output_dir)
                    job.progress = 100
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
                    if progress_cb:
                        progress_cb(JobState.complete.value, 100, f"Rip complete: {output_dir}")

            job.updated_at = datetime.utcnow()
            return job
        except Exception as exc:  # noqa: BLE001
            job.state = JobState.failed
            job.error = str(exc)
            job.progress = 100
            if progress_cb:
                progress_cb(JobState.failed.value, 100, f"Pipeline error: {exc}")
            job.updated_at = datetime.utcnow()
            return job
