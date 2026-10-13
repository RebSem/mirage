"""Virtual backgrounds: the built-in ones (drawn in code, nothing to download) and
your own pictures.

A background choice is one string, stored in ``Settings.background``:

* ``"none"``: the camera as it is;
* ``"blur"``: your room, softly blurred;
* ``"preset:<name>"``: one of :data:`PRESETS`, painted at any size;
* ``"image:<id>"``: a picture you added (``<app_support>/backgrounds``).
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from mirage import paths

log = logging.getLogger(__name__)

NONE, BLUR = "none", "blur"
PRESET_PREFIX, IMAGE_PREFIX = "preset:", "image:"
MAX_SIDE = 1920          # pictures are stored at most this big (the camera is 1280×720 at most)


# ── built-in backgrounds ─────────────────────────────────────────────────
#
# Each is a soft "mesh gradient" (blurred colour blobs over a base), plus a
# little grain so a 1280×720 gradient never shows bands in Zoom's compression.

def _grain(h: int, w: int, amount: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, amount, (h, w, 1)).astype(np.float32)


def _mesh(w: int, h: int, base: tuple[int, int, int],
          blobs: list[tuple[float, float, float, tuple[int, int, int]]], seed: int) -> np.ndarray:
    """Base colour + soft round blobs (x, y, radius as fractions; BGR colour)."""
    sw, sh = 160, 90  # paint small, scale up: smooth and fast
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    img = np.empty((sh, sw, 3), np.float32)
    img[:] = base
    aspect = sw / sh
    for cx, cy, r, color in blobs:
        d = np.sqrt(((xx / sw - cx) * aspect) ** 2 + (yy / sh - cy) ** 2) / r
        weight = np.clip(1.0 - d, 0.0, 1.0)[..., None]
        weight = weight * weight * (3.0 - 2.0 * weight)
        img = img * (1.0 - weight) + np.array(color, np.float32) * weight
    img = cv2.GaussianBlur(img, (0, 0), 6.0)
    out = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC) + _grain(h, w, 1.6, seed)
    return np.clip(out, 0, 255).astype(np.uint8)


def _studio(w: int, h: int) -> np.ndarray:
    """A portrait studio: a soft spotlight on a slate backdrop, dark at the edges."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w * 0.5) / (w * 0.62)) ** 2 + ((yy - h * 0.42) / (h * 0.78)) ** 2)
    light = np.clip(1.0 - d, 0.0, 1.0)[..., None] ** 1.6
    edge, centre = np.array((40, 33, 28), np.float32), np.array((128, 116, 104), np.float32)
    out = edge + (centre - edge) * light + _grain(h, w, 1.8, 11)
    return np.clip(out, 0, 255).astype(np.uint8)


def _office(w: int, h: int) -> np.ndarray:
    """An office in the evening, out of focus: warm wall, a window, a few lamps."""
    rng = np.random.default_rng(23)
    sw, sh = 320, 180
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    top, bottom = np.array((52, 62, 74), np.float32), np.array((26, 30, 36), np.float32)
    img = top + (bottom - top) * (yy / sh)[..., None]
    # a tall window on the left, cool daylight
    window = ((xx > sw * 0.06) & (xx < sw * 0.30) & (yy > sh * 0.08) & (yy < sh * 0.78)).astype(np.float32)
    img += window[..., None] * np.array((60, 50, 38), np.float32)
    # a shelf line and a desk edge
    img[int(sh * 0.62):int(sh * 0.64), int(sw * 0.45):] += np.array((30, 40, 52), np.float32)
    img[int(sh * 0.86):, :] *= 0.75
    # bokeh: soft discs of warm (and a few cool) light
    for _ in range(26):
        cx, cy = rng.uniform(0.32, 1.0) * sw, rng.uniform(0.05, 0.7) * sh
        r = rng.uniform(4.0, 13.0)
        warm = rng.random() < 0.8
        color = np.array((70, 150, 235) if warm else (220, 170, 120), np.float32) * rng.uniform(0.35, 0.8)
        disc = np.clip(1.2 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r, 0.0, 1.0)[..., None]
        img += disc * color
    img = cv2.GaussianBlur(img, (0, 0), 5.0)
    out = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC) + _grain(h, w, 1.8, 29)
    return np.clip(out, 0, 255).astype(np.uint8)


@dataclass(frozen=True)
class Preset:
    name: str                       # stable id, stored in settings
    paint: Callable[[int, int], np.ndarray]


PRESETS: tuple[Preset, ...] = (
    Preset("studio", _studio),
    Preset("office", _office),
    Preset("aurora", lambda w, h: _mesh(w, h, (40, 18, 16), [
        (0.15, 0.25, 0.55, (210, 70, 90)), (0.80, 0.20, 0.50, (220, 60, 150)),
        (0.60, 0.95, 0.65, (150, 170, 30)), (0.95, 0.75, 0.40, (230, 120, 60))], 31)),
    Preset("sunset", lambda w, h: _mesh(w, h, (120, 110, 235), [
        (0.10, 0.15, 0.60, (150, 170, 255)), (0.85, 0.20, 0.55, (140, 90, 230)),
        (0.50, 1.00, 0.70, (120, 60, 160)), (0.95, 0.90, 0.45, (170, 110, 120))], 37)),
    Preset("lagoon", lambda w, h: _mesh(w, h, (170, 150, 60), [
        (0.15, 0.20, 0.55, (210, 200, 120)), (0.85, 0.15, 0.50, (200, 170, 40)),
        (0.40, 0.95, 0.65, (120, 160, 40)), (0.95, 0.85, 0.40, (230, 210, 170))], 41)),
    Preset("daylight", lambda w, h: _mesh(w, h, (214, 226, 234), [
        (0.20, 0.15, 0.60, (236, 244, 248)), (0.85, 0.30, 0.55, (196, 214, 228)),
        (0.50, 1.05, 0.70, (178, 196, 212)), (0.05, 0.90, 0.40, (200, 214, 222))], 43)),
)
PRESET_NAMES = tuple(p.name for p in PRESETS)


def render_preset(name: str, width: int = 1280, height: int = 720) -> np.ndarray:
    """A built-in background as a BGR image of the given size."""
    for preset in PRESETS:
        if preset.name == name:
            return preset.paint(width, height)
    raise KeyError(name)


# ── choices ──────────────────────────────────────────────────────────────

def parse(choice: str | None) -> tuple[str, str]:
    """``"preset:aurora"`` → ``("preset", "aurora")``; anything odd → ``("none", "")``."""
    if not isinstance(choice, str):
        return NONE, ""
    if choice in (NONE, BLUR):
        return choice, ""
    for prefix in (PRESET_PREFIX, IMAGE_PREFIX):
        if choice.startswith(prefix) and len(choice) > len(prefix):
            return prefix[:-1], choice[len(prefix):]
    return NONE, ""


def is_valid(choice: str) -> bool:
    kind, value = parse(choice)
    if kind == "preset":
        return value in PRESET_NAMES
    if kind == "image":
        return len(value) == 12 and all(c in "0123456789abcdef" for c in value)
    return kind == choice


# ── your own pictures ────────────────────────────────────────────────────

@dataclass
class BackgroundEntry:
    id: str        # 12 hex chars
    name: str
    created: float


def _pretty(stem: str) -> str:
    name = " ".join(stem.replace("_", " ").replace("-", " ").split())
    return (name[:40] or "Background").strip()


class BackgroundLibrary:
    """``<root>/index.json`` plus one ``<id>.jpg`` per picture. Thread-safe."""

    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else paths.app_support_dir() / "backgrounds"
        self._lock = threading.Lock()
        self._entries: list[BackgroundEntry] = []
        self._load()

    def list(self) -> list[BackgroundEntry]:
        with self._lock:
            return list(self._entries)

    def get(self, bg_id: str) -> BackgroundEntry | None:
        with self._lock:
            return next((e for e in self._entries if e.id == bg_id), None)

    def path(self, bg_id: str) -> Path:
        return self.root / f"{bg_id}.jpg"

    def load(self, bg_id: str) -> np.ndarray | None:
        data = np.fromfile(self.path(bg_id), np.uint8) if self.path(bg_id).is_file() else None
        return cv2.imdecode(data, cv2.IMREAD_COLOR) if data is not None and data.size else None

    def add_file(self, path: Path) -> BackgroundEntry:
        """Copy a picture in (HEIC and other formats through macOS ``sips``). Raises
        ``UnreadableImageError`` (from ``mirage.library``) if it isn't one."""
        from mirage.library import UnreadableImageError, _read_image

        image = _read_image(Path(path))
        if image is None or image.ndim != 3 or min(image.shape[:2]) < 32:
            raise UnreadableImageError(str(path))
        return self.add_image(image, _pretty(Path(path).stem))

    def add_image(self, image: np.ndarray, name: str) -> BackgroundEntry:
        from mirage.settings import write_atomic

        h, w = image.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        if scale < 1.0:
            image = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise OSError("could not encode the picture")
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            bg_id = secrets.token_hex(6)
            while any(e.id == bg_id for e in self._entries):
                bg_id = secrets.token_hex(6)
            write_atomic(self.path(bg_id), data.tobytes())
            entry = BackgroundEntry(bg_id, name, time.time())
            self._entries.append(entry)
            self._write_index()
        return entry

    def remove(self, bg_id: str) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e.id != bg_id]
            self._write_index()
        self.path(bg_id).unlink(missing_ok=True)

    def _write_index(self) -> None:
        from mirage.settings import write_atomic

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "backgrounds": [asdict(e) for e in self._entries]}
            write_atomic(self.root / "index.json", json.dumps(data, indent=2, ensure_ascii=False).encode())
        except OSError as exc:
            log.warning("could not save the background list: %s", exc)

    def _load(self) -> None:
        index = self.root / "index.json"
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            items = data.get("backgrounds", []) if isinstance(data, dict) else []
        except FileNotFoundError:
            items = []
        except (OSError, ValueError):
            log.warning("ignoring a damaged %s", index)
            items = []
        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            bg_id, name, created = item.get("id"), item.get("name"), item.get("created", 0.0)
            if (isinstance(bg_id, str) and is_valid(IMAGE_PREFIX + bg_id) and isinstance(name, str)
                    and self.path(bg_id).is_file()):
                entries.append(BackgroundEntry(bg_id, name, float(created) if isinstance(created, int | float) else 0.0))
        known = {e.id for e in entries}
        if self.root.is_dir():  # pictures whose index entry got lost come back, named "Background"
            for file in sorted(self.root.glob("*.jpg"), key=lambda f: f.stat().st_mtime):
                if file.stem not in known and is_valid(IMAGE_PREFIX + file.stem):
                    entries.append(BackgroundEntry(file.stem, "Background", file.stat().st_mtime))
        self._entries = entries


def load_choice(choice: str, library: BackgroundLibrary, size: tuple[int, int] = (1280, 720)) -> np.ndarray | None:
    """The picture for an ``image``/``preset`` choice (None for none/blur or a missing picture)."""
    kind, value = parse(choice)
    if kind == "preset" and value in PRESET_NAMES:
        return render_preset(value, *size)
    if kind == "image":
        return library.load(value)
    return None
