from __future__ import annotations

import subprocess
from pathlib import Path


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


def run_makemkv(drive: str, output_dir: Path, makemkvcon_path: str = "makemkvcon") -> tuple[bool, str]:
    # Use `all` to avoid lsdvd 1-based vs makemkv 0-based title index mismatch.
    cmd = [makemkvcon_path, "mkv", "all", drive, str(output_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout.strip()


def eject_drive(drive: str) -> tuple[bool, str]:
    """Eject optical drive. Used when identification fails or user rejects auto-identification."""
    cmd = ["eject", drive]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, "Drive ejected successfully"
