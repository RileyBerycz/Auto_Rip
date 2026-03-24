from __future__ import annotations

import json
import subprocess
from typing import Any

from .models import DiscInfo, DiscTrack


def scan_disc(drive: str) -> DiscInfo:
    cmd = ["lsdvd", "-Oy", "-x", drive]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"lsdvd failed for {drive}: {proc.stderr.strip()}")

    raw = proc.stdout.strip()
    if raw.startswith("lsdvd ="):
        raw = raw.split("=", 1)[1].strip()

    data: dict[str, Any] = json.loads(raw)
    label = data.get("disc_title") or data.get("title") or "UNKNOWN_DISC"

    tracks: list[DiscTrack] = []
    for title in data.get("track", []):
        minutes = float(title.get("length", 0)) / 60.0
        audios = [a.get("langcode", "und") for a in title.get("audio", []) if isinstance(a, dict)]
        tracks.append(
            DiscTrack(
                number=int(title.get("ix", 0)),
                duration_minutes=round(minutes, 2),
                audio_languages=audios,
            )
        )

    return DiscInfo(drive=drive, label=label, tracks=tracks)
