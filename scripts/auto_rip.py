from __future__ import annotations

import curses
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from dvdflix_core import RipPipeline, Settings

POLL_SECONDS = 8


def has_disc(drive: str) -> bool:
    try:
        proc = subprocess.run(["lsdvd", "-q", drive], capture_output=True, text=True, check=False)
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def try_eject(drive: str) -> None:
    subprocess.run(["eject", drive], capture_output=True, text=True, check=False)


def draw_screen(stdscr: curses.window, drives: list[str], drive_state: dict[str, str], logs: deque[str]) -> None:
    stdscr.erase()
    stdscr.addstr(0, 0, "DVDFlix auto_rip daemon", curses.A_BOLD)
    stdscr.addstr(1, 0, f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    stdscr.addstr(3, 0, "Drive status:", curses.A_UNDERLINE)

    row = 4
    for drive in drives:
        stdscr.addstr(row, 0, f"- {drive}: {drive_state.get(drive, 'idle')}")
        row += 1

    row += 1
    stdscr.addstr(row, 0, "Recent events:", curses.A_UNDERLINE)
    row += 1

    max_y, _ = stdscr.getmaxyx()
    visible = max(1, max_y - row - 1)
    for entry in list(logs)[-visible:]:
        if row >= max_y - 1:
            break
        stdscr.addstr(row, 0, entry[:120])
        row += 1

    stdscr.addstr(max_y - 1, 0, "Press q to quit.")
    stdscr.refresh()


def append_log(logs: deque[str], message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    logs.append(f"[{ts}] {message}")


def daemon(stdscr: curses.window) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)

    settings = Settings()
    pipeline = RipPipeline(settings)

    drives = settings.drives
    logs: deque[str] = deque(maxlen=200)
    drive_state: dict[str, str] = {d: "idle" for d in drives}
    inflight: dict[str, Future] = {}
    lock = threading.Lock()

    append_log(logs, f"Monitoring drives: {', '.join(drives)}")

    def run_job(drive: str):
        with lock:
            drive_state[drive] = "identifying/ripping"
        append_log(logs, f"Disc detected in {drive}. Starting pipeline.")
        job = pipeline.run_for_drive(drive)
        with lock:
            if job.state.value == "complete":
                drive_state[drive] = "complete"
                append_log(logs, f"{drive}: complete -> {job.output_path}")
                try_eject(drive)
                append_log(logs, f"{drive}: eject attempted")
            else:
                drive_state[drive] = "failed"
                append_log(logs, f"{drive}: failed -> {job.error}")
        return job

    with ThreadPoolExecutor(max_workers=max(1, len(drives))) as pool:
        while True:
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                append_log(logs, "Shutdown requested.")
                break

            for drive in drives:
                future = inflight.get(drive)
                if future and future.done():
                    inflight.pop(drive, None)

                if drive in inflight:
                    continue

                if has_disc(drive):
                    if drive_state.get(drive) in {"complete", "failed"}:
                        # Wait for manual media swap before re-queueing this drive.
                        continue
                    inflight[drive] = pool.submit(run_job, drive)
                else:
                    if drive_state.get(drive) != "idle":
                        drive_state[drive] = "idle"
                        append_log(logs, f"{drive}: tray empty")

            draw_screen(stdscr, drives, drive_state, logs)
            time.sleep(POLL_SECONDS)


def main() -> None:
    curses.wrapper(daemon)


if __name__ == "__main__":
    main()
