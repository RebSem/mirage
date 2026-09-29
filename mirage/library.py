"""Face library: imported photos, round-avatar thumbnails and cached embeddings.

Layout of the library directory:

    index.json          {"version": 1, "faces": [FaceEntry, ...]} in user order
    <id>.jpg            the photo, longest side <= 1024
    <id>_thumb.jpg      256x256 crop centred on the face
    <id>.npy            the face embedding, float32 (512,)

Switching faces only needs the cached embedding, so it is instant. Every file is
written atomically and all state changes happen under one lock, so the UI thread
and import workers can use the same FaceLibrary.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import math
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from mirage.settings import write_atomic

log = logging.getLogger(__name__)

INDEX_VERSION = 1
EMBEDDING_SIZE = 512
MAX_IMAGE_SIDE = 1024
THUMB_SIZE = 256
THUMB_ZOOM = 1.8  # face box is enlarged this much before the square crop
JPEG_QUALITY = 92
NAME_MAX = 40
DEFAULT_NAME = "Face"
DETECT_MAX_SIDE = 2048

_ID_RE = re.compile(r"[0-9a-f]{12}")
_NAME_SEPARATORS = re.compile(r"[_\-.]+")


class DetectedFace(NamedTuple):
    embedding: np.ndarray  # float32, shape (512,)
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in the given image
    gender: int | None = None  # insightface: 1 = male, 0 = female (for suggestions)
    age: float | None = None


Embedder = Callable[[np.ndarray], DetectedFace | None]  # BGR uint8 image in


class NoFaceError(ValueError):
    """The photo was read, but the embedder found no face in it."""


class UnreadableImageError(ValueError):
    """The file is missing, unreadable, or not an image we can decode."""


@dataclass
class FaceEntry:
    id: str  # 12 hex chars
    name: str
    created: float  # unix time
    image: str  # file name inside the library dir
    thumb: str
    embedding: str
    gender: int | None = None  # used to suggest natural-looking swaps in photos
    age: float | None = None


def _clean_gender(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        g = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return g if g in (0, 1) else None


def _clean_age(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        age = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(age, 1) if math.isfinite(age) and 0 <= age <= 120 else None


def _clean_name(name: str) -> str:
    """Collapse whitespace and cut to NAME_MAX; "" when nothing is left."""
    return " ".join(str(name).split())[:NAME_MAX].rstrip()


def pretty_name(stem: str) -> str:
    """Turn a file stem like "anna_karenina-2" into "anna karenina 2"."""
    return _clean_name(_NAME_SEPARATORS.sub(" ", stem)) or DEFAULT_NAME


def _decode(data: np.ndarray) -> np.ndarray | None:
    if data.size == 0:
        return None
    try:
        # IMREAD_COLOR also applies the EXIF orientation of phone photos.
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except cv2.error:
        return None


def _decode_with_sips(path: Path) -> np.ndarray | None:
    """macOS only: convert formats OpenCV lacks (iPhone HEIC) with the built-in sips."""
    sips = shutil.which("sips") if sys.platform == "darwin" else None
    if sips is None:
        return None
    with tempfile.TemporaryDirectory(prefix="mirage-import-") as tmp:
        out = Path(tmp) / "converted.png"  # lossless; sips bakes in the rotation
        try:
            subprocess.run(
                [sips, "-s", "format", "png", str(path), "--out", str(out)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return _decode(np.fromfile(out, dtype=np.uint8))
        except (OSError, subprocess.SubprocessError):
            return None


def _read_image(path: Path) -> np.ndarray:
    try:
        # np.fromfile + imdecode instead of imread: works with any unicode path.
        data = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise UnreadableImageError(f"cannot read {path}: {exc}") from exc
    image = _decode(data)
    if image is None:
        image = _decode_with_sips(path)
    if image is None:
        raise UnreadableImageError(f"not an image: {path}")
    return image


def _as_bgr(image: np.ndarray) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.size == 0 or image.dtype != np.uint8:
        raise UnreadableImageError("expected a non-empty uint8 image")
    if image.ndim == 2 or (image.ndim == 3 and image.shape[2] == 1):
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    if image.ndim == 3 and image.shape[2] == 3:
        return np.ascontiguousarray(image)
    raise UnreadableImageError(f"unsupported image shape {image.shape}")


def _as_embedding(value: np.ndarray) -> np.ndarray:
    embedding = np.array(value, dtype=np.float32).reshape(-1)  # own copy, as returned
    if embedding.shape != (EMBEDDING_SIZE,) or not np.isfinite(embedding).all():
        raise ValueError(f"embedder returned a bad embedding, shape {embedding.shape}")
    embedding.setflags(write=False)
    return embedding


def _fit(image: np.ndarray, bbox: tuple[float, ...]) -> tuple[np.ndarray, tuple[float, ...]]:
    """Shrink so the longest side is <= MAX_IMAGE_SIDE; map the box along."""
    h, w = image.shape[:2]
    scale = MAX_IMAGE_SIDE / max(h, w)
    if scale >= 1.0:
        return image, bbox
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    sx, sy = size[0] / w, size[1] / h
    x1, y1, x2, y2 = bbox
    return small, (x1 * sx, y1 * sy, x2 * sx, y2 * sy)


def _thumbnail(image: np.ndarray, bbox: tuple[float, ...]) -> np.ndarray:
    """Square crop centred on the face box enlarged THUMB_ZOOM times, THUMB_SIZE^2."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if all(map(math.isfinite, (x1, y1, x2, y2))) and x2 - x1 >= 1 and y2 - y1 >= 1:
        # Keep the centre on the image so the crop always overlaps it.
        cx = min(max((x1 + x2) / 2, 0.0), w - 1.0)
        cy = min(max((y1 + y2) / 2, 0.0), h - 1.0)
        side = max(x2 - x1, y2 - y1) * THUMB_ZOOM
    else:  # unusable box: plain centre square
        cx, cy, side = w / 2, h / 2, float(min(w, h))
    size = max(1, round(side))
    left, top = round(cx - size / 2), round(cy - size / 2)
    right, bottom = left + size, top + size
    crop = image[max(0, top) : min(h, bottom), max(0, left) : min(w, right)]
    pad = (max(0, -top), max(0, bottom - h), max(0, -left), max(0, right - w))
    if any(pad):  # the enlarged box runs off the photo: extend its edges
        crop = cv2.copyMakeBorder(crop, *pad, cv2.BORDER_REPLICATE)
    interpolation = cv2.INTER_AREA if size > THUMB_SIZE else cv2.INTER_CUBIC
    return cv2.resize(crop, (THUMB_SIZE, THUMB_SIZE), interpolation=interpolation)


def _encode_jpeg(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


def _encode_npy(array: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, array, allow_pickle=False)
    return buf.getvalue()


class FaceLibrary:
    """Thread-safe store of faces. Unknown ids raise KeyError (remove() ignores them)."""

    def __init__(self, root: Path, embedder: Embedder) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        self._lock = threading.RLock()
        self._embed_lock = threading.Lock()  # embedders are rarely thread-safe
        self._reserved: set[str] = set()
        self._cache: dict[str, np.ndarray] = {}
        self._entries: list[FaceEntry] = []
        self._load()

    # -- reading ---------------------------------------------------------------

    def list(self) -> list[FaceEntry]:
        """All faces in user order (copies; edit through rename/move/remove)."""
        with self._lock:
            return [replace(entry) for entry in self._entries]

    def get(self, face_id: str) -> FaceEntry | None:
        with self._lock:
            entry = self._find(face_id)
            return replace(entry) if entry is not None else None

    def embedding(self, face_id: str) -> np.ndarray:
        """The face's embedding as a read-only float32 array, cached in memory."""
        with self._lock:
            cached = self._cache.get(face_id)
            if cached is not None:
                return cached
            entry = self._require(face_id)
            array = _as_embedding(np.load(self.root / entry.embedding, allow_pickle=False))
            self._cache[face_id] = array
            return array

    def image_path(self, face_id: str) -> Path:
        with self._lock:
            return self.root / self._require(face_id).image

    def thumb_path(self, face_id: str) -> Path:
        with self._lock:
            return self.root / self._require(face_id).thumb

    # -- adding ----------------------------------------------------------------

    def add_file(self, path: Path, name: str | None = None) -> FaceEntry:
        """Import a photo. Raises UnreadableImageError or NoFaceError."""
        path = Path(path)
        image = _read_image(path)
        return self.add_image(image, name if name is not None else pretty_name(path.stem))

    def add_image(self, image: np.ndarray, name: str) -> FaceEntry:
        """Import a BGR (or gray/BGRA) uint8 image. Raises NoFaceError without a face."""
        image = _as_bgr(image)
        # Detect on a capped copy: a 48 MP photo (plus padded retries) would
        # otherwise allocate gigabytes. The box is mapped back afterwards.
        scale = min(1.0, DETECT_MAX_SIDE / max(image.shape[:2]))
        probe = image if scale >= 1.0 else cv2.resize(
            image, (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
        with self._embed_lock:
            face = self._embedder(probe)
        if face is None:
            raise NoFaceError("no face found in the image")
        embedding = _as_embedding(face.embedding)

        # All the heavy work happens outside the lock so readers never wait on it.
        bbox_full = tuple(float(v) / scale for v in face.bbox)
        stored, bbox = _fit(image, bbox_full)
        image_jpg = _encode_jpeg(stored)
        thumb_jpg = _encode_jpeg(_thumbnail(stored, bbox))
        embedding_npy = _encode_npy(embedding)

        face_id = self._reserve_id()
        written: list[Path] = []
        try:
            entry = FaceEntry(
                id=face_id,
                name=_clean_name(name) or DEFAULT_NAME,
                created=time.time(),
                image=f"{face_id}.jpg",
                thumb=f"{face_id}_thumb.jpg",
                embedding=f"{face_id}.npy",
                gender=_clean_gender(face.gender),
                age=_clean_age(face.age),
            )
            for file_name, data in (
                (entry.image, image_jpg),
                (entry.thumb, thumb_jpg),
                (entry.embedding, embedding_npy),
            ):
                write_atomic(self.root / file_name, data)
                written.append(self.root / file_name)
            with self._lock:
                self._entries.append(entry)
                try:
                    self._write_index()
                except BaseException:
                    self._entries.pop()  # the lock guarantees it is still last
                    raise
                self._cache[face_id] = embedding
        except BaseException:
            for target in written:
                with contextlib.suppress(OSError):
                    target.unlink(missing_ok=True)
            raise
        finally:
            with self._lock:
                self._reserved.discard(face_id)
        return replace(entry)

    # -- editing ---------------------------------------------------------------

    def remove(self, face_id: str) -> None:
        with self._lock:
            entry = self._find(face_id)
            if entry is None:
                return
            index = self._entries.index(entry)
            del self._entries[index]
            try:
                self._write_index()  # index first: a crash leaves orphans, not holes
            except BaseException:
                self._entries.insert(index, entry)
                raise
            self._cache.pop(face_id, None)
            for file_name in (entry.image, entry.thumb, entry.embedding):
                with contextlib.suppress(OSError):
                    (self.root / file_name).unlink(missing_ok=True)

    def set_attributes(self, face_id: str, gender: int | None, age: float | None) -> None:
        """Remember gender/age for suggestions (filled in lazily for older faces)."""
        with self._lock:
            entry = self._require(face_id)
            new = (_clean_gender(gender), _clean_age(age))
            if (entry.gender, entry.age) == new:
                return
            previous = (entry.gender, entry.age)
            entry.gender, entry.age = new
            try:
                self._write_index()
            except BaseException:
                entry.gender, entry.age = previous
                raise

    def rename(self, face_id: str, name: str) -> None:
        """Rename a face; a blank name keeps the current one."""
        with self._lock:
            entry = self._require(face_id)
            clean = _clean_name(name)
            if not clean or clean == entry.name:
                return
            previous, entry.name = entry.name, clean
            try:
                self._write_index()
            except BaseException:
                entry.name = previous
                raise

    def move(self, face_id: str, index: int) -> None:
        """Move a face to position `index` (clamped to the list) and persist the order."""
        with self._lock:
            entry = self._require(face_id)
            previous = list(self._entries)
            self._entries.remove(entry)
            self._entries.insert(min(max(index, 0), len(self._entries)), entry)
            if self._entries == previous:
                return
            try:
                self._write_index()
            except BaseException:
                self._entries[:] = previous
                raise

    # -- internals -------------------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _find(self, face_id: str) -> FaceEntry | None:
        return next((e for e in self._entries if e.id == face_id), None)

    def _require(self, face_id: str) -> FaceEntry:
        entry = self._find(face_id)
        if entry is None:
            raise KeyError(face_id)
        return entry

    def _reserve_id(self) -> str:
        with self._lock:
            while True:
                face_id = secrets.token_hex(6)
                taken = face_id in self._reserved or self._find(face_id) is not None
                files = (f"{face_id}.jpg", f"{face_id}_thumb.jpg", f"{face_id}.npy")
                if not taken and not any((self.root / name).exists() for name in files):
                    self._reserved.add(face_id)
                    return face_id

    def _write_index(self) -> None:
        data = {"version": INDEX_VERSION, "faces": [asdict(e) for e in self._entries]}
        text = json.dumps(data, indent=2, ensure_ascii=False)
        write_atomic(self._index_path, (text + "\n").encode("utf-8"))

    def _load(self) -> None:
        """Read index.json into self._entries, dropping entries whose files are gone."""
        path = self._index_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._rebuild_from_files()  # e.g. the index was deleted by hand
            return
        except ValueError as exc:
            log.warning("Face library index %s is corrupt, rebuilding from files: %s", path, exc)
            self._set_index_aside()
            self._rebuild_from_files()
            return
        except OSError as exc:
            # Unreadable (permissions, a disk error). Starting empty would let the next
            # import overwrite it and lose every face, so treat it like a corrupt index:
            # keep it aside (names stay in that copy) and rebuild from the face files.
            log.warning("Face library index %s can't be read, rebuilding from files: %s", path, exc)
            self._set_index_aside()
            self._rebuild_from_files()
            return
        faces = data.get("faces") if isinstance(data, dict) else None
        if not isinstance(faces, list):
            log.warning("Face library index %s has no face list, rebuilding from files", path)
            self._set_index_aside()
            self._rebuild_from_files()
            return
        version = data.get("version")
        if version != INDEX_VERSION:
            log.warning("Face library index version %r, expected %d", version, INDEX_VERSION)

        seen: set[str] = set()
        for item in faces:
            entry = self._parse_entry(item)
            if entry is not None and entry.id not in seen:
                seen.add(entry.id)
                self._entries.append(entry)
        dropped = len(faces) - len(self._entries)
        if dropped:
            log.warning("Dropped %d face(s) with missing files or a broken index entry", dropped)
            try:
                self._write_index()
            except OSError as exc:
                log.warning("Could not rewrite face library index: %s", exc)

    def _set_index_aside(self) -> None:
        """Keep an unusable index as index.corrupt-<time>.json; never overwrite an older copy."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.root / f"index.corrupt-{stamp}.json"
        n = 1
        while target.exists():
            n += 1
            target = self.root / f"index.corrupt-{stamp}-{n}.json"
        with contextlib.suppress(OSError):
            self._index_path.replace(target)

    def _rebuild_from_files(self) -> None:
        """Recover faces whose three files (<id>.jpg, <id>_thumb.jpg, <id>.npy) are all present."""
        found = []
        for npy in self.root.glob("*.npy"):
            face_id = npy.stem
            if not _ID_RE.fullmatch(face_id):
                continue
            if (self.root / f"{face_id}.jpg").is_file() and (self.root / f"{face_id}_thumb.jpg").is_file():
                found.append((npy.stat().st_mtime, face_id))
        if not found:
            return
        for created, face_id in sorted(found):
            self._entries.append(FaceEntry(
                id=face_id, name=DEFAULT_NAME, created=created,
                image=f"{face_id}.jpg", thumb=f"{face_id}_thumb.jpg", embedding=f"{face_id}.npy",
            ))
        log.warning("Recovered %d face(s) from files; their names were reset", len(found))
        try:
            self._write_index()
        except OSError as exc:
            log.warning("Could not write the rebuilt face library index: %s", exc)

    def _parse_entry(self, item: object) -> FaceEntry | None:
        if not isinstance(item, dict):
            return None
        try:
            created = float(item.get("created", 0.0))
            entry = FaceEntry(
                id=str(item["id"]),
                name=_clean_name(item.get("name", "")) or DEFAULT_NAME,
                created=created if math.isfinite(created) else 0.0,
                image=str(item["image"]),
                thumb=str(item["thumb"]),
                embedding=str(item["embedding"]),
                gender=_clean_gender(item.get("gender")),
                age=_clean_age(item.get("age")),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not _ID_RE.fullmatch(entry.id):
            return None
        for file_name in (entry.image, entry.thumb, entry.embedding):
            # Plain file names only: an index must never point outside the library.
            if Path(file_name).name != file_name or file_name.startswith("."):
                return None
            if not (self.root / file_name).is_file():
                return None
        return entry
