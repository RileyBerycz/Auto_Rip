from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from flask_socketio import SocketIO

from dvdflix_core import JobState, RipPipeline, Settings
from dvdflix_core.config import discover_optical_drives
from dvdflix_core.models import RipJob


def _canonical_drive_key(drive: str) -> str:
    p = Path(drive)
    try:
        return str(p.resolve(strict=False))
    except OSError:
        return str(p)


def probe_drive_status(drive: str) -> dict[str, str | bool]:
    exists = Path(drive).exists()
    if not exists:
        return {
            "drive": drive,
            "exists": False,
            "has_disc": False,
            "readable": False,
            "status": "missing",
            "detail": "Drive device node not found",
        }

    try:
        proc = subprocess.run(["lsdvd", "-q", drive], capture_output=True, text=True, check=False)
        stderr = (proc.stderr or "").strip()
        lower = stderr.lower()
        if proc.returncode == 0:
            return {
                "drive": drive,
                "exists": True,
                "has_disc": True,
                "readable": True,
                "status": "ready",
                "detail": "Disc detected and readable",
            }

        if "no medium found" in lower or "can't open disc" in lower:
            return {
                "drive": drive,
                "exists": True,
                "has_disc": False,
                "readable": False,
                "status": "empty",
                "detail": "Drive is empty",
            }

        if "no css library available" in lower or "encrypted dvd support unavailable" in lower:
            return {
                "drive": drive,
                "exists": True,
                "has_disc": True,
                "readable": False,
                "status": "encrypted",
                "detail": "Encrypted disc present, lsdvd cannot read without libdvdcss",
            }

        return {
            "drive": drive,
            "exists": True,
            "has_disc": False,
            "readable": False,
            "status": "error",
            "detail": stderr or "Unknown lsdvd error",
        }
    except FileNotFoundError:
        return {
            "drive": drive,
            "exists": exists,
            "has_disc": False,
            "readable": False,
            "status": "tool-missing",
            "detail": "lsdvd not installed",
        }


def has_disc(drive: str) -> bool:
    status = probe_drive_status(drive)
    return bool(status["has_disc"]) and bool(status["readable"])


class JobManager:
    def __init__(self, socketio: SocketIO, settings_overrides: dict[str, str] | None = None) -> None:
        self.socketio = socketio
        self.settings = Settings.from_overrides(settings_overrides)
        self.pipeline = RipPipeline(self.settings)
        self.executor = ThreadPoolExecutor(max_workers=max(1, len(self.settings.drives) or 1))
        self.jobs: dict[str, RipJob] = {}
        self.inflight_by_drive: dict[str, Future] = {}
        self.lock = threading.Lock()
        self._stop_event = threading.Event()

        # Background monitor allows hands-off operation in the web app.
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def reconfigure(self, settings_overrides: dict[str, str]) -> None:
        with self.lock:
            self.settings = Settings.from_overrides(settings_overrides)
            self.pipeline = RipPipeline(self.settings)

            old_executor = self.executor
            self.executor = ThreadPoolExecutor(max_workers=max(1, len(self.settings.drives) or 1))

        old_executor.shutdown(wait=False)

    def _emit(self, event: str, payload: dict) -> None:
        self.socketio.emit(event, payload)

    def list_jobs(self) -> list[dict]:
        with self.lock:
            ordered = sorted(self.jobs.values(), key=lambda j: j.updated_at, reverse=True)
            return [j.to_dict() for j in ordered]

    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.to_dict() if job else None

    def update_job(self, job_id: str, updates: dict) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False

            if updates.get("title") is not None:
                job.title = str(updates.get("title", ""))
            if updates.get("media_type") is not None:
                job.media_type = str(updates.get("media_type", "movie"))
            if updates.get("error") is not None:
                job.error = str(updates.get("error", ""))
            job.updated_at = datetime.utcnow()
            return True

    def list_history(self, limit: int = 500) -> list[dict[str, str]]:
        return self.pipeline.cache.list_disc_history(limit=limit)

    def update_history(
        self,
        disc_hash: str,
        *,
        title: str,
        year: str,
        media_type: str,
        notes: str,
    ) -> bool:
        return self.pipeline.cache.update_disc_history(
            disc_hash,
            title=title,
            year=year,
            media_type=media_type,
            notes=notes,
        )

    def start_job(self, drive: str) -> dict:
        with self.lock:
            active = self.inflight_by_drive.get(drive)
            if active and not active.done():
                return {"ok": False, "error": f"Drive {drive} already busy"}

        status = probe_drive_status(drive)
        if not status.get("has_disc"):
            return {"ok": False, "error": f"No disc detected in {drive}"}
        if not status.get("readable"):
            return {"ok": False, "error": f"{drive} has disc but is not readable by lsdvd ({status.get('status')})"}

        with self.lock:
            future = self.executor.submit(self._run_pipeline_job, drive)
            self.inflight_by_drive[drive] = future
            return {"ok": True}

    def start_all(self) -> dict:
        result: dict[str, dict] = {}
        for drive in self.settings.drives:
            result[drive] = self.start_job(drive)
        return {"ok": True, "result": result}

    def _run_pipeline_job(self, drive: str) -> None:
        pending = RipJob(id=f"queued-{int(time.time())}-{drive}", drive=drive, state=JobState.pending)
        with self.lock:
            self.jobs[pending.id] = pending
        self._emit("job_update", pending.to_dict())

        job = self.pipeline.run_for_drive(drive)
        job.updated_at = datetime.utcnow()
        with self.lock:
            self.jobs[job.id] = job
            self.inflight_by_drive.pop(drive, None)

        self._emit("job_update", job.to_dict())

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            for drive in self.settings.drives:
                if not has_disc(drive):
                    continue

                with self.lock:
                    active = self.inflight_by_drive.get(drive)
                    if active and not active.done():
                        continue

                self.start_job(drive)
            time.sleep(10)

    def list_drive_statuses(self) -> list[dict[str, str | bool]]:
        configured = list(self.settings.drives)
        detected = discover_optical_drives()

        merged = configured + [d for d in detected if d not in configured]
        canonical_seen: set[str] = set()
        statuses: list[dict[str, str | bool]] = []

        for drive in merged:
            key = _canonical_drive_key(drive)
            if key in canonical_seen:
                continue
            canonical_seen.add(key)

            item = probe_drive_status(drive)
            in_config = drive in configured
            in_detect = drive in detected
            if in_config and in_detect:
                source = "configured+detected"
            elif in_config:
                source = "configured"
            else:
                source = "detected"
            item["source"] = source
            statuses.append(item)

        return statuses

    def shutdown(self) -> None:
        self._stop_event.set()
        self.executor.shutdown(wait=False)
