from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from flask_socketio import SocketIO

from dvdflix_core import JobState, RipPipeline, Settings
from dvdflix_core.models import RipJob


def has_disc(drive: str) -> bool:
    try:
        proc = subprocess.run(["lsdvd", "-q", drive], capture_output=True, text=True, check=False)
        return proc.returncode == 0
    except FileNotFoundError:
        return False


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

    def start_job(self, drive: str) -> dict:
        with self.lock:
            active = self.inflight_by_drive.get(drive)
            if active and not active.done():
                return {"ok": False, "error": f"Drive {drive} already busy"}

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

    def shutdown(self) -> None:
        self._stop_event.set()
        self.executor.shutdown(wait=False)
