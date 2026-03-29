from __future__ import annotations

import ast
import json
import subprocess
from typing import Any

from .models import DiscInfo, DiscTrack


def _extract_lsdvd_payload(stdout: str) -> str:
    raw = stdout.strip()
    marker = "lsdvd ="
    idx = raw.find(marker)
    if idx >= 0:
        return raw[idx + len(marker):].strip()
    return raw


def _parse_lsdvd_payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Some lsdvd builds emit Python-style dicts with single quotes.
    parsed = ast.literal_eval(raw)
    if isinstance(parsed, dict):
        return parsed
    raise RuntimeError("lsdvd returned unsupported payload format")


def scan_disc(drive: str) -> DiscInfo:
    cmd = ["lsdvd", "-Oy", "-x", drive]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        lower = stderr.lower()
        if "no medium found" in lower:
            raise RuntimeError(f"No disc detected in {drive}")
        if "no css library available" in lower or "encrypted dvd support unavailable" in lower:
            # lsdvd cannot parse CSS-encrypted metadata, but makemkvcon can often still rip it.
            # Return minimal metadata so the pipeline can continue.
            safe_label = f"ENCRYPTED_{drive.replace('/', '_')}"
            return DiscInfo(drive=drive, label=safe_label, tracks=[])
        raise RuntimeError(f"lsdvd failed for {drive}: {stderr or 'unknown error'}")

    raw = _extract_lsdvd_payload(proc.stdout)
    try:
        data = _parse_lsdvd_payload(raw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"lsdvd returned unparseable data for {drive}: {exc}") from exc
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
