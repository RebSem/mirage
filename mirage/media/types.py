"""Plain data shared by the photo and video pipelines (no Qt, no models)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TargetFace:
    """A face found in a photo (or in a video's sample frame)."""

    index: int                                   # stable number shown in the UI (1-based order: left → right)
    bbox: tuple[float, float, float, float]      # x1, y1, x2, y2 in original image pixels
    kps: np.ndarray                              # (5, 2) float32 landmarks, original pixels
    score: float                                 # detector confidence
    embedding: np.ndarray                        # (512,) float32 identity embedding (raw, not normalised)
    gender: int | None = None                    # insightface: 1 = male, 0 = female
    age: float | None = None

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True)
class SourceInfo:
    """A library face that can be worn, with optional attributes for suggestions."""

    id: str
    name: str
    gender: int | None = None
    age: float | None = None


# target index → library face id, or None to leave that face untouched
Plan = dict[int, "str | None"]


@dataclass
class RenderOptions:
    enhance: bool = True          # GFPGAN on swapped faces (photos); GPEN-256 for video when enabled
    video_enhance: bool = False   # video enhancement is slow on M1, off unless asked


@dataclass
class VideoInfo:
    path: str
    width: int                    # display size (rotation applied)
    height: int
    fps: float
    frames: int                   # best estimate (may be 0 if unknown)
    duration: float               # seconds
    has_audio: bool
    rotation: int = 0             # degrees from metadata (0/90/180/270)
    codec: str = ""


@dataclass
class VideoIdentity:
    """A person in the video to swap: who they are, and whose face they get."""

    embedding: np.ndarray         # (512,) identity of the target person (from a sample frame)
    source_embedding: np.ndarray  # (512,) the library face to put on them
    label: str = ""


@dataclass
class VideoProgress:
    done: int
    total: int
    fps: float                    # processing speed
    eta_seconds: float | None
    stage: str = "render"         # probe | render | encode | done
    extra: dict = field(default_factory=dict)
