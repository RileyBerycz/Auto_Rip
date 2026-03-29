from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobState(str, Enum):
    pending = "pending"
    identifying = "identifying"
    ripping = "ripping"
    encoding = "encoding"
    postprocessing = "postprocessing"
    canceled = "canceled"
    complete = "complete"
    failed = "failed"


@dataclass(slots=True)
class DiscTrack:
    number: int
    duration_minutes: float
    audio_languages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiscInfo:
    drive: str
    label: str
    tracks: list[DiscTrack] = field(default_factory=list)


@dataclass(slots=True)
class IdentificationResult:
    media_type: str
    title: str
    year: int | None
    confidence: float
    season: int | None = None
    episodes: int | None = None


@dataclass(slots=True)
class RipJob:
    id: str
    drive: str
    state: JobState
    disc_label: str = ""
    title: str = ""
    media_type: str = "movie"
    output_path: str = ""
    error: str = ""
    progress: int = 0
    logs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "drive": self.drive,
            "state": self.state.value,
            "disc_label": self.disc_label,
            "title": self.title,
            "media_type": self.media_type,
            "output_path": self.output_path,
            "error": self.error,
            "progress": self.progress,
            "logs": self.logs,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }
