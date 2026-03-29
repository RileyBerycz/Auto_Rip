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
from dvdflix_core.ripper import build_output_dir, eject_drive


def _canonical_drive_key(drive: str) -> str:
    p = Path(drive)
    try:
        return str(p.resolve(strict=False))
    except OSError:
        return str(p)


def _preferred_display_drive(drive: str) -> str:
    canonical = _canonical_drive_key(drive)
    # If /dev/cdrom or /dev/dvd resolves to /dev/srX, show /dev/srX in UI.
    if canonical.startswith("/dev/sr"):
        return canonical
    return drive


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
                "readable": True,
                "status": "encrypted",
                "detail": "Encrypted disc detected; metadata is limited but rip via MakeMKV is allowed",
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
        self.inflight_job_by_drive: dict[str, str] = {}
        self.cancel_flags: dict[str, threading.Event] = {}
        self.wait_media_change: set[str] = set()
        self.last_auto_eject_attempt: dict[str, float] = {}
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self.auto_eject_cooldown_seconds = 90

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
            if updates.get("progress") is not None:
                try:
                    job.progress = max(0, min(100, int(updates.get("progress", 0))))
                except (TypeError, ValueError):
                    pass
            if updates.get("logs") is not None and isinstance(updates.get("logs"), list):
                job.logs = [str(x) for x in updates.get("logs", [])]
            job.updated_at = datetime.utcnow()
            return True

    def finalize_manual_identification(
        self,
        job_id: str,
        *,
        title: str,
        media_type: str,
        year: int | None,
    ) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "job not found"}
            source_path = Path((job.output_path or "").strip())

        if not source_path.exists() or not source_path.is_dir():
            return {"ok": False, "error": "temp rip output not found"}

        target_root = self.settings.movies_path if media_type == "movie" else self.settings.tv_path
        output_dir = build_output_dir(target_root, title, year)
        try:
            for child in source_path.iterdir():
                child_target = output_dir / child.name
                if child_target.exists():
                    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    child_target = output_dir / f"{child.stem}-{suffix}{child.suffix}"
                child.rename(child_target)
            source_path.rmdir()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "job not found"}
            job.title = title
            job.media_type = media_type
            job.output_path = str(output_dir)
            job.state = JobState.complete
            job.error = ""
            job.progress = 100
            self._append_job_log(job, f"Manual identification applied; moved output to {output_dir}")
            job.updated_at = datetime.utcnow()
            payload = job.to_dict()

        self._emit("job_update", payload)
        return {"ok": True, "output_path": str(output_dir)}

    def _append_job_log(self, job: RipJob, message: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        job.logs.append(f"[{ts}] {message}")
        # Keep latest 500 lines to avoid unbounded memory growth.
        if len(job.logs) > 500:
            job.logs = job.logs[-500:]

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
        drive = _preferred_display_drive(drive)
        drive_key = _canonical_drive_key(drive)
        with self.lock:
            active = self.inflight_by_drive.get(drive_key)
            if active and not active.done():
                return {"ok": False, "error": f"Drive {drive} already busy"}

        status = probe_drive_status(drive)
        if not status.get("has_disc"):
            return {"ok": False, "error": f"No disc detected in {drive}"}
        if not status.get("readable"):
            return {"ok": False, "error": f"{drive} has disc but is not readable by lsdvd ({status.get('status')})"}

        with self.lock:
            future = self.executor.submit(self._run_pipeline_job, drive)
            self.inflight_by_drive[drive_key] = future
            return {"ok": True}

    def cancel_job(self, job_id: str) -> dict:
        with self.lock:
            event = self.cancel_flags.get(job_id)
            if not event:
                return {"ok": False, "error": "job not found or not running"}
            event.set()
            job = self.jobs.get(job_id)
            if job:
                self._append_job_log(job, "Cancellation requested")
                job.updated_at = datetime.utcnow()

        return {"ok": True}

    def cleanup_job_output(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "job not found"}
            output_path = (job.output_path or "").strip()

        if not output_path:
            return {"ok": False, "error": "job has no output path"}

        path = Path(output_path)
        if not path.exists():
            return {"ok": False, "error": f"output path not found: {output_path}"}

        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            else:
                for child in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    if child.is_file() or child.is_symlink():
                        child.unlink(missing_ok=True)
                    elif child.is_dir():
                        child.rmdir()
                path.rmdir()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                self._append_job_log(job, f"Output cleaned: {output_path}")
                job.output_path = ""
                job.updated_at = datetime.utcnow()
        return {"ok": True, "message": "output cleaned"}

    def start_all(self) -> dict:
        result: dict[str, dict] = {}
        seen: set[str] = set()
        for drive in self._combined_drives():
            normalized = _preferred_display_drive(drive)
            key = _canonical_drive_key(normalized)
            if key in seen:
                continue
            seen.add(key)
            result[normalized] = self.start_job(normalized)
        return {"ok": True, "result": result}

    def _combined_drives(self) -> list[str]:
        configured = [_preferred_display_drive(d) for d in self.settings.drives]
        detected = discover_optical_drives()

        merged = configured + [d for d in detected if _preferred_display_drive(d) not in configured]
        seen: set[str] = set()
        unique: list[str] = []
        for drive in merged:
            key = _canonical_drive_key(drive)
            if key in seen:
                continue
            seen.add(key)
            unique.append(drive)
        return unique

    def _maybe_auto_eject_empty(self, drive: str) -> None:
        now = time.time()
        drive_key = _canonical_drive_key(drive)
        with self.lock:
            last = self.last_auto_eject_attempt.get(drive_key, 0.0)
            if now - last < self.auto_eject_cooldown_seconds:
                return
            self.last_auto_eject_attempt[drive_key] = now

        ok, _ = eject_drive(drive)
        if not ok:
            return

        with self.lock:
            job_id = self.inflight_job_by_drive.get(drive_key)
            if not job_id:
                return
            job = self.jobs.get(job_id)
            if not job:
                return
            self._append_job_log(job, "Auto-eject triggered: tray appears empty")
            job.updated_at = datetime.utcnow()
            payload = job.to_dict()
        self._emit("job_update", payload)

    def _run_pipeline_job(self, drive: str) -> None:
        drive = _preferred_display_drive(drive)
        drive_key = _canonical_drive_key(drive)
        safe_drive = drive.replace("/", "_")
        pending = RipJob(id=f"job-{int(time.time() * 1000)}-{safe_drive}", drive=drive, state=JobState.pending)
        pending.progress = 5
        self._append_job_log(pending, f"Queued job for {drive}")
        cancel_event = threading.Event()
        with self.lock:
            self.jobs[pending.id] = pending
            self.cancel_flags[pending.id] = cancel_event
            self.inflight_job_by_drive[drive_key] = pending.id
        self._emit("job_update", pending.to_dict())

        def _on_progress(state: str, progress: int, message: str) -> None:
            with self.lock:
                queued = self.jobs.get(pending.id)
                if not queued:
                    return
                try:
                    queued.state = JobState(state)
                except ValueError:
                    pass
                queued.progress = max(0, min(100, int(progress)))
                self._append_job_log(queued, message)
                queued.updated_at = datetime.utcnow()
                payload = queued.to_dict()
            self._emit("job_update", payload)

        job = self.pipeline.run_for_drive(
            drive,
            progress_cb=_on_progress,
            should_cancel=cancel_event.is_set,
            job_id=pending.id,
        )
        if pending.logs:
            job.logs = pending.logs + (job.logs or [])
        if job.progress <= 0:
            if job.state == JobState.complete:
                job.progress = 100
            elif job.state == JobState.failed:
                job.progress = 100
            elif job.state == JobState.ripping:
                job.progress = 70
        job.updated_at = datetime.utcnow()
        with self.lock:
            self.jobs[job.id] = job
            self.inflight_by_drive.pop(drive_key, None)
            self.inflight_job_by_drive.pop(drive_key, None)
            self.cancel_flags.pop(job.id, None)
            # Avoid instant retry loops; require disc/tray change before auto requeue.
            self.wait_media_change.add(drive_key)

        self._emit("job_update", job.to_dict())

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            seen: set[str] = set()
            for configured in self._combined_drives():
                drive = _preferred_display_drive(configured)
                drive_key = _canonical_drive_key(drive)
                if drive_key in seen:
                    continue
                seen.add(drive_key)

                status = probe_drive_status(drive)
                if status.get("status") == "empty":
                    self._maybe_auto_eject_empty(drive)
                    with self.lock:
                        self.wait_media_change.discard(drive_key)
                    continue

                if not status.get("has_disc"):
                    with self.lock:
                        self.wait_media_change.discard(drive_key)
                    continue

                if not status.get("readable"):
                    continue

                with self.lock:
                    active = self.inflight_by_drive.get(drive_key)
                    if active and not active.done():
                        continue
                    if drive_key in self.wait_media_change:
                        continue

                self.start_job(drive)
            time.sleep(10)

    def list_drive_statuses(self) -> list[dict[str, str | bool]]:
        configured = [_preferred_display_drive(d) for d in self.settings.drives]
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
