from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _ffprobe_stream_info(src: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(src),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffprobe failed")
    return json.loads(proc.stdout)


def get_video_resolution(src: Path) -> tuple[int, int]:
    info = _ffprobe_stream_info(src)
    streams = info.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {src}")

    width = streams[0].get("width")
    height = streams[0].get("height")
    if width is None or height is None:
        raise RuntimeError(f"Video resolution missing in {src}")
    return int(width), int(height)


def _normalize_even(value: int) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def get_handbrake_resolution(width: int, height: int) -> tuple[int, int] | None:
    if height <= 720:
        target_height = 720
    elif height <= 1080:
        target_height = 1080
    else:
        return width, height

    if target_height == height:
        return width, height

    scaled_width = _normalize_even(int(round(width * (target_height / height))))
    return scaled_width, target_height


def build_handbrake_command(
    src: Path,
    dst: Path,
    preset: str = "default",
) -> list[str]:
    quality_presets: dict[str, int] = {
        "default": 22,
        "high": 20,
        "hq": 20,
        "fast": 24,
        "ultrafast": 28,
    }
    quality = quality_presets.get(preset.lower(), 22)

    cmd = [
        "HandBrakeCLI",
        "-i",
        str(src),
        "-o",
        str(dst),
        "-e",
        "x265",
        "-q",
        str(quality),
        "-f",
        "av_mkv",
        "--all-audio",
        "--all-subtitles",
        "--audio-copy-mask",
        "ac3,dts,dts-hd,truehd,eac3,flac",
        "--audio-fallback",
        "ffac3",
    ]

    try:
        width, height = get_video_resolution(src)
        target = get_handbrake_resolution(width, height)
        if target and target != (width, height):
            target_width, target_height = target
            cmd.extend(
                [
                    "--auto-anamorphic",
                    "--loose-anamorphic",
                    "-w",
                    str(target_width),
                    "-l",
                    str(target_height),
                ]
            )
    except Exception:
        pass

    return cmd


def encode_file(src: Path, dst: Path, preset: str = "default") -> tuple[bool, str]:
    if not src.exists():
        return False, f"Source not found: {src}"
    if dst.exists():
        return False, f"Destination already exists: {dst}"

    cmd = build_handbrake_command(src, dst, preset=preset)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "HandBrakeCLI failed").strip()
    return True, "encoded"
