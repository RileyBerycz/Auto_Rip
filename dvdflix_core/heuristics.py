from __future__ import annotations

from statistics import pstdev

from .models import DiscInfo


def is_probable_tv_disc(disc: DiscInfo) -> tuple[bool, int]:
    durations = [t.duration_minutes for t in disc.tracks if t.duration_minutes > 0]
    if len(durations) < 3:
        return False, 0

    sitcom_like = [d for d in durations if 18 <= d <= 35]
    drama_like = [d for d in durations if 38 <= d <= 70]
    candidate = sitcom_like if len(sitcom_like) >= len(drama_like) else drama_like

    if len(candidate) < 3:
        return False, 0

    variance = pstdev(candidate)
    if variance <= 4.0:
        return True, len(candidate)
    return False, 0


def pick_feature_track_runtime(disc: DiscInfo) -> int:
    if not disc.tracks:
        return 0
    feature = max(disc.tracks, key=lambda t: t.duration_minutes)
    return int(round(feature.duration_minutes))
