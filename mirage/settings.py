"""Persisted user settings: one small JSON file that tolerates anything on disk.

Loading never fails: a missing or corrupt file gives defaults, and a field with a
wrong type or an out-of-range value falls back to its default on its own.
Saving is atomic and never raises, so a read-only disk cannot crash the app.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import numbers
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from mirage import paths

log = logging.getLogger(__name__)

QUALITIES = ("fast", "balanced", "best")
LANGUAGES = ("auto", "en", "ru")
_UNIT_FIELDS = ("opacity", "sharpness")  # floats clamped to 0..1
MODES = ("live", "media")
_CHOICES = {"quality": QUALITIES, "language": LANGUAGES, "mode": MODES}


@dataclass
class Settings:
    camera_uid: str | None = None
    face_id: str | None = None  # None = show my real face ("Original")
    quality: str = "balanced"  # "fast" | "balanced" | "best"
    opacity: float = 1.0  # 0..1, face blend
    sharpness: float = 0.0  # 0..1
    mouth_mask: bool = False  # keep my own mouth
    many_faces: bool = False
    color_fix: bool = False
    poisson_blend: bool = False
    mirror_preview: bool = True  # preview only; virtual cam is never mirrored
    show_fps: bool = False
    language: str = "auto"  # "auto" | "en" | "ru"
    onboarding_done: bool = False
    window_geometry: str | None = None  # base64 of QWidget.saveGeometry()
    mode: str = "live"  # "live" | "media" (Photos & videos)
    me_face_id: str | None = None  # library face marked "This is me" (found first in photos)
    photo_enhance: bool = True  # GFPGAN on swapped faces in photos
    video_enhance: bool = False  # GPEN-256 in videos (slow on M1)


_DEFAULTS = Settings()


def _coerce(name: str, value: Any) -> Any:
    """Return `value` if it fits field `name`, otherwise the field's default."""
    default = getattr(_DEFAULTS, name)
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        # bool is an int subclass; True must not sneak in as 1.0.
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return min(1.0, max(0.0, number)) if name in _UNIT_FIELDS else number
    if name in _CHOICES:
        if not isinstance(value, str):
            return default
        choice = value.strip().lower()
        return choice if choice in _CHOICES[name] else default
    if default is None:  # optional string: camera uid, face id, geometry
        return value if isinstance(value, str) and value else None
    return value if isinstance(value, str) else default


def _from_mapping(data: dict[str, Any]) -> Settings:
    known = {f.name for f in fields(Settings)}
    return Settings(**{name: _coerce(name, data[name]) for name in known if name in data})


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` via a temp file in the same directory + os.replace.

    Readers see either the old file or the new one, never a torn write.
    Raises OSError; the temp file is removed on failure.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load(path: Path | None = None) -> Settings:
    """Read settings; missing file, bad JSON or bad values give defaults."""
    path = path if path is not None else paths.settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as exc:  # ValueError covers JSON and UTF-8 errors
        log.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return Settings()
    if not isinstance(data, dict):
        log.warning("Ignoring settings file %s: top level is not an object", path)
        return Settings()
    return _from_mapping(data)


def save(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically. Failures are logged, never raised."""
    try:
        path = path if path is not None else paths.settings_path()
        clean = _from_mapping(asdict(settings))
        text = json.dumps(asdict(clean), indent=2, sort_keys=True, ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, (text + "\n").encode("utf-8"))
    except OSError as exc:
        log.warning("Could not save settings to %s: %s", path, exc)
