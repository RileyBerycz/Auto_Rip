from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable


def sanitize_filename(name: str) -> str:
    keep = "-_.() "
    return "".join(ch for ch in name if ch.isalnum() or ch in keep).strip().replace("  ", " ")


def build_output_dir(base_path: Path, title: str, year: int | None = None) -> Path:
    folder = sanitize_filename(title)
    if year:
        folder = f"{folder} ({year})"
    out = base_path / folder
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_makemkv(
    drive: str,
    output_dir: Path,
    makemkvcon_path: str = "makemkvcon",
    should_cancel: Callable[[], bool] | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> tuple[bool, str, bool]:
    # Use `all` to avoid lsdvd 1-based vs makemkv 0-based title index mismatch.
    cmd = [makemkvcon_path, "mkv", "all", drive, str(output_dir)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    lines: list[str] = []
    cancelled = False
    while True:
        if should_cancel and should_cancel():
            cancelled = True
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            break

        line = proc.stdout.readline()
        if line:
            text = line.rstrip("\n")
            lines.append(text)
            if log_cb and text:
                log_cb(text)
        elif proc.poll() is not None:
            break
        else:
            time.sleep(0.1)

    rc = proc.wait()
    output = "\n".join(lines[-200:]).strip()
    if cancelled:
        return False, "Cancelled by user", True
    if rc != 0:
        return False, output or f"makemkvcon exited with code {rc}", False
    return True, output, False


def eject_drive(drive: str) -> tuple[bool, str]:
    """Eject optical drive. Used when identification fails or user rejects auto-identification."""
    cmd = ["eject", drive]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, "Drive ejected successfully"
