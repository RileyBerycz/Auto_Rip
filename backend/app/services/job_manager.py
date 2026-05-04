from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from dvdflix_core import JobState, RipPipeline, Settings
from dvdflix_core.config import discover_optical_drives
from dvdflix_core.encoder import build_handbrake_command, get_video_resolution
from dvdflix_core.models import RipJob
from dvdflix_core.nfo import create_nfo_for_job
from dvdflix_core.ripper import build_output_dir, eject_drive

from .sse_manager import SSEManager


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
    def __init__(self, sse_manager: SSEManager, settings_overrides: dict[str, str] | None = None) -> None:
        self.sse_manager = sse_manager
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

        # Encode queue mirrors legacy script behavior: one encode worker, FIFO queue.
        self.encode_executor = ThreadPoolExecutor(max_workers=1)
        self.encode_queue_lock = threading.Lock()
        self.encode_enqueued_paths: set[str] = set()
        self.encode_pending_count_by_job: dict[str, int] = {}
        self.encode_failed_count_by_job: dict[str, int] = {}
        self.encode_nfo_after_complete: set[str] = set()
        self.encode_suffix = ".x265.mkv"

        # Background monitor allows hands-off operation in the web app.
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        # Allow disabling the automatic monitor loop for testing or hosts
        # that prefer manual control. Set DISABLE_AUTO_RIP=true in the
        # environment to prevent the monitor from starting.
        if os.environ.get("DISABLE_AUTO_RIP", "false").lower() not in ("1", "true", "yes"):
            self.monitor_thread.start()

    def reconfigure(self, settings_overrides: dict[str, str]) -> None:
        with self.lock:
            self.settings = Settings.from_overrides(settings_overrides)
            self.pipeline = RipPipeline(self.settings)

            old_executor = self.executor
            self.executor = ThreadPoolExecutor(max_workers=max(1, len(self.settings.drives) or 1))

        old_executor.shutdown(wait=False)

    def _emit(self, event: str, payload: dict, room: str = None) -> None:
        self.sse_manager.emit(event, payload, room)

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
            job.year = year
            job.output_path = str(output_dir)
            job.state = JobState.complete
            job.error = ""
            job.progress = 100
            self._append_job_log(job, f"Manual identification applied; moved output to {output_dir}")
            job.updated_at = datetime.utcnow()
            payload = job.to_dict()

        self._emit("job_update", payload)
        queued_count = self._queue_encode_for_job(job_id, source="manual-identification")
        if queued_count:
            self.encode_nfo_after_complete.add(job_id)
        else:
            self._create_nfo_for_job(job_id)
        return {"ok": True, "output_path": str(output_dir)}

    def _set_job_encoding_started(self, job_id: str, queued_files: int, source: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.state = JobState.encoding
            # Keep progress high so UI indicates rip done while encode is running.
            job.progress = max(job.progress, 95)
            self._append_job_log(
                job,
                f"Encoding queued ({queued_files} file(s), source={source})",
            )
            job.updated_at = datetime.utcnow()
            payload = job.to_dict()
        self._emit("job_update", payload)

    def _queue_encode_for_job(self, job_id: str, source: str) -> int:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or not job.output_path:
                return 0
            output_root = Path(job.output_path)

        if not output_root.exists():
            return 0
        if not shutil.which("HandBrakeCLI"):
            with self.lock:
                job = self.jobs.get(job_id)
                if not job:
                    return 0
                self._append_job_log(job, "Encoding skipped: HandBrakeCLI not available")
                job.updated_at = datetime.utcnow()
                self._emit("job_update", job.to_dict())
            return 0

        if output_root.is_file():
            mkv_files = [output_root] if output_root.suffix.lower() == ".mkv" else []
        else:
            mkv_files = sorted(
                (p for p in output_root.rglob("*.mkv") if not p.name.endswith(self.encode_suffix)),
                key=lambda p: p.stat().st_size,
                reverse=True,
            )

        if not mkv_files:
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    self._append_job_log(job, f"No MKV files found to encode at {output_root}")
                    job.state = JobState.complete
                    job.progress = 100
                    job.updated_at = datetime.utcnow()
                    self._emit("job_update", job.to_dict())
            return 0

        queued_count = 0
        with self.encode_queue_lock:
            for src in mkv_files:
                src_abs = str(src.resolve(strict=False))
                if src_abs in self.encode_enqueued_paths:
                    continue
                self.encode_enqueued_paths.add(src_abs)
                self.encode_pending_count_by_job[job_id] = self.encode_pending_count_by_job.get(job_id, 0) + 1
                queued_count += 1
                self.encode_executor.submit(self._encode_file_for_job, job_id, src_abs)

        if queued_count:
            self._set_job_encoding_started(job_id, queued_count, source)
        return queued_count

    def _get_handbrake_preset_for_path(self, src: Path) -> str:
        try:
            _, height = get_video_resolution(src)
            if height <= 720:
                return self.settings.handbrake_preset_dvd or self.settings.handbrake_preset
        except Exception:
            pass
        return self.settings.handbrake_preset_bluray or self.settings.handbrake_preset

    def queue_library_encode(self, scope: str) -> dict:
        if scope not in {"all", "movies", "tv"}:
            return {"ok": False, "error": "scope must be one of all|movies|tv"}

        targets: list[Path] = []
        if scope in {"all", "movies"}:
            targets.append(self.settings.movies_path)
        if scope in {"all", "tv"}:
            targets.append(self.settings.tv_path)
        if not targets:
            return {"ok": False, "error": "scope must be one of all|movies|tv"}

        task_ids: list[str] = []
        for root in targets:
            if not root.exists():
                continue
            job_id = str(uuid.uuid4())
            job = RipJob(
                id=job_id,
                drive="",
                state=JobState.pending,
                title=f"Library encode ({scope})",
                media_type="movie" if root == self.settings.movies_path else "tv",
                output_path=str(root),
            )
            with self.lock:
                self.jobs[job_id] = job
            self._queue_encode_for_job(job_id, source=f"library-encode:{scope}")
            task_ids.append(job_id)

        if not task_ids:
            return {"ok": False, "error": "No valid library roots found to encode"}

        return {"ok": True, "job_ids": task_ids}

    def queue_library_encode_item(self, path: Path, scope: str) -> dict:
        if scope not in {"movies", "tv"}:
            return {"ok": False, "error": "scope must be movies or tv"}

        if not path.exists():
            return {"ok": False, "error": f"path not found: {path}"}

        root = self.settings.movies_path if scope == "movies" else self.settings.tv_path
        resolved_root = root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
            return {"ok": False, "error": f"path must be inside {resolved_root}"}

        job_id = str(uuid.uuid4())
        job = RipJob(
            id=job_id,
            drive="",
            state=JobState.pending,
            title=f"Library encode item ({scope})",
            media_type=scope,
            output_path=str(path),
        )
        with self.lock:
            self.jobs[job_id] = job
        self._queue_encode_for_job(job_id, source=f"library-encode-item:{scope}")
        return {"ok": True, "job_id": job_id}

    def _finalize_encode_state(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return

            pending = self.encode_pending_count_by_job.get(job_id, 0)
            failed = self.encode_failed_count_by_job.get(job_id, 0)
            if pending > 0:
                return

            self.encode_pending_count_by_job.pop(job_id, None)
            self.encode_failed_count_by_job.pop(job_id, None)

            if failed:
                job.error = f"Encoding completed with {failed} failure(s). Check logs."
                self._append_job_log(job, job.error)
            else:
                job.error = ""
                self._append_job_log(job, "Encoding complete")

            job.state = JobState.complete
            job.progress = 100
            job.updated_at = datetime.utcnow()
            payload = job.to_dict()

        self._emit("job_update", payload)

        if job_id in self.encode_nfo_after_complete:
            self.encode_nfo_after_complete.discard(job_id)
            self._create_nfo_for_job(job_id)

    def _create_nfo_for_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or not job.output_path:
                return
            output_dir = Path(job.output_path)
            self._append_job_log(job, "Postprocessing: generating metadata NFO")
            job.state = JobState.postprocessing
            job.updated_at = datetime.utcnow()
            self._emit("job_update", job.to_dict())

        ok = create_nfo_for_job(output_dir, job.title, job.media_type, job.year, self.settings.tmdb_api_key)
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            if ok:
                self._append_job_log(job, "NFO generated successfully")
            else:
                self._append_job_log(job, "NFO generation skipped or failed")
            job.updated_at = datetime.utcnow()
            self._emit("job_update", job.to_dict())

    def _encode_file_for_job(self, job_id: str, src_abs: str) -> None:
        src = Path(src_abs)
        temp_root = Path(self.settings.temp_rip_path or "/tmp")
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_out = temp_root / f"{src.stem}.encoding-temp{src.suffix}"
        failed = False

        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                self._append_job_log(job, f"Encoding start: {src.name}")
                job.updated_at = datetime.utcnow()
                self._emit("job_update", job.to_dict())

        try:
            if not src.exists():
                failed = True
                raise FileNotFoundError(f"Source missing for encode: {src}")

            if temp_out.exists():
                temp_out.unlink(missing_ok=True)

            preset = self._get_handbrake_preset_for_path(src)
            cmd = build_handbrake_command(src, temp_out, preset=preset)
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                failed = True
                msg = (proc.stderr or proc.stdout or "HandBrakeCLI failed").strip()
                raise RuntimeError(msg)

            # Replace original with encoded output, matching legacy script behavior.
            try:
                os.replace(str(temp_out), str(src))
            except OSError:
                if src.exists():
                    src.unlink(missing_ok=True)
                shutil.move(str(temp_out), str(src))

            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    self._append_job_log(job, f"Encoding done: {src.name}")
                    job.updated_at = datetime.utcnow()
                    self._emit("job_update", job.to_dict())
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    self._append_job_log(job, f"Encoding failed for {src.name}: {exc}")
                    job.updated_at = datetime.utcnow()
                    self._emit("job_update", job.to_dict())
        finally:
            if temp_out.exists():
                temp_out.unlink(missing_ok=True)

            with self.encode_queue_lock:
                self.encode_enqueued_paths.discard(src_abs)
                pending = self.encode_pending_count_by_job.get(job_id, 0)
                self.encode_pending_count_by_job[job_id] = max(0, pending - 1)
                if failed:
                    self.encode_failed_count_by_job[job_id] = self.encode_failed_count_by_job.get(job_id, 0) + 1

            self._finalize_encode_state(job_id)

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

        if job.state in {JobState.complete, JobState.failed, JobState.needs_review, JobState.canceled}:
            ok, message = eject_drive(drive)
            with self.lock:
                finished_job = self.jobs.get(job.id)
                if finished_job:
                    finished_job.updated_at = datetime.utcnow()
                    if ok:
                        self._append_job_log(finished_job, "Drive ejected after job completion")
                    else:
                        self._append_job_log(finished_job, f"Drive eject failed after job: {message}")
                    self._emit("job_update", finished_job.to_dict())

        if job.state == JobState.complete and job.output_path:
            queued_count = self._queue_encode_for_job(job.id, source="auto-rip")
            if queued_count:
                self.encode_nfo_after_complete.add(job.id)
            else:
                self._create_nfo_for_job(job.id)

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            seen: set[str] = set()
            statuses: list[dict[str, str | bool]] = []
            for configured in self._combined_drives():
                drive = _preferred_display_drive(configured)
                drive_key = _canonical_drive_key(drive)
                if drive_key in seen:
                    continue
                seen.add(drive_key)

                status = probe_drive_status(drive)
                statuses.append(status)
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

            if statuses:
                summary = {
                    "total": len(statuses),
                    "with_disc": sum(1 for item in statuses if item.get("has_disc")),
                    "readable": sum(1 for item in statuses if item.get("readable")),
                }
                self._emit("drive_update", {"drives": statuses, "summary": summary})
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
        self.encode_executor.shutdown(wait=False)
        self.executor.shutdown(wait=False)
