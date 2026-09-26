import json
import logging
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pytest

from mirage import library
from mirage.library import (
    DetectedFace,
    FaceLibrary,
    NoFaceError,
    UnreadableImageError,
    pretty_name,
)

BACKGROUND = 20  # dark backdrop; anything brighter than FACE_LEVEL is "a face"
FACE_LEVEL = 100


def fake_face(image: np.ndarray) -> DetectedFace | None:
    """Deterministic stand-in for the real detector: the bright blob is the face."""
    mask = image.max(axis=2) > FACE_LEVEL
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    b, g, r = (int(round(v)) for v in image[mask].mean(axis=0))
    rng = np.random.default_rng(b << 16 | g << 8 | r)
    embedding = (rng.standard_normal(512) * 3).astype(np.float32)  # deliberately not unit length
    bbox = (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
    return DetectedFace(embedding, bbox)


class FakeEmbedder:
    """Counts calls and records whether two calls ever overlapped."""

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.max_active = 0
        self._active = 0
        self._delay = delay
        self._lock = threading.Lock()

    def __call__(self, image: np.ndarray) -> DetectedFace | None:
        with self._lock:
            self.calls += 1
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self._delay)
            return fake_face(image)
        finally:
            with self._lock:
                self._active -= 1


def make_image(
    width: int = 640,
    height: int = 480,
    box: tuple[int, int, int, int] | None = (270, 170, 370, 290),
    color: tuple[int, int, int] = (60, 170, 230),
) -> np.ndarray:
    image = np.full((height, width, 3), BACKGROUND, dtype=np.uint8)
    if box is not None:
        x1, y1, x2, y2 = box
        image[y1:y2, x1:x2] = color
    return image


def write_png(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    buf.tofile(path)  # works with unicode paths
    return path


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return image


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def lib(tmp_path: Path, embedder: FakeEmbedder) -> FaceLibrary:
    return FaceLibrary(tmp_path / "faces", embedder)


def library_files(lib: FaceLibrary) -> set[str]:
    return {p.name for p in lib.root.iterdir()}


# -- adding -------------------------------------------------------------------


def test_add_file_stores_photo_thumb_and_embedding(lib: FaceLibrary, tmp_path: Path) -> None:
    photo = make_image(2000, 1500, (900, 600, 1100, 850))
    source = write_png(tmp_path / "anna_karenina-2.png", photo)
    before = time.time()
    entry = lib.add_file(source)

    assert len(entry.id) == 12 and int(entry.id, 16) >= 0
    assert entry.name == "anna karenina 2"
    assert before <= entry.created <= time.time()
    assert (entry.image, entry.thumb, entry.embedding) == (
        f"{entry.id}.jpg",
        f"{entry.id}_thumb.jpg",
        f"{entry.id}.npy",
    )
    assert library_files(lib) == {"index.json", entry.image, entry.thumb, entry.embedding}

    assert read_image(lib.image_path(entry.id)).shape == (768, 1024, 3)
    assert read_image(lib.thumb_path(entry.id)).shape == (256, 256, 3)

    stored = np.load(lib.root / entry.embedding)
    expected = fake_face(photo)
    assert expected is not None
    assert stored.dtype == np.float32 and stored.shape == (512,)
    np.testing.assert_array_equal(stored, expected.embedding)  # stored as returned, not normalised
    assert abs(float(np.linalg.norm(stored)) - 1.0) > 0.5

    index = json.loads((lib.root / "index.json").read_text(encoding="utf-8"))
    assert index["version"] == 1
    assert [f["id"] for f in index["faces"]] == [entry.id]


def test_small_images_are_not_upscaled(lib: FaceLibrary) -> None:
    entry = lib.add_image(make_image(320, 240, (100, 60, 200, 180)), "Small")
    assert read_image(lib.image_path(entry.id)).shape == (240, 320, 3)


def test_add_image_cleans_names(lib: FaceLibrary) -> None:
    image = make_image()
    assert lib.add_image(image, "  Mona \n  Lisa  ").name == "Mona Lisa"
    assert lib.add_image(image, "   ").name == "Face"
    assert lib.add_image(image, "x" * 100).name == "x" * 40
    assert lib.add_image(image, "under_score").name == "under_score"  # explicit names kept


def test_add_file_explicit_name_wins(lib: FaceLibrary, tmp_path: Path) -> None:
    source = write_png(tmp_path / "IMG_0042.png", make_image())
    assert lib.add_file(source, name="Me").name == "Me"


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("anna_karenina-2", "anna karenina 2"),
        ("IMG_0042", "IMG 0042"),
        ("my.photo..final", "my photo final"),
        ("  spaced   out  ", "spaced out"),
        ("___--..", "Face"),
        ("", "Face"),
        ("a" * 60, "a" * 40),
        ("Лёва_Толстой", "Лёва Толстой"),
    ],
)
def test_pretty_name(stem: str, expected: str) -> None:
    assert pretty_name(stem) == expected


@pytest.mark.parametrize(
    "image",
    [
        cv2.cvtColor(make_image(), cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(make_image(), cv2.COLOR_BGR2BGRA),
    ],
    ids=["gray", "bgra"],
)
def test_add_image_accepts_gray_and_bgra(lib: FaceLibrary, image: np.ndarray) -> None:
    entry = lib.add_image(image, "Converted")
    assert read_image(lib.thumb_path(entry.id)).shape == (256, 256, 3)


def test_bad_embedding_is_rejected(tmp_path: Path) -> None:
    def short_embedder(image: np.ndarray) -> DetectedFace:
        return DetectedFace(np.zeros(128, dtype=np.float32), (0.0, 0.0, 10.0, 10.0))

    lib = FaceLibrary(tmp_path / "faces", short_embedder)
    with pytest.raises(ValueError):
        lib.add_image(make_image(), "Short")
    assert lib.list() == []
    assert library_files(lib) == set()


def test_float64_embedding_is_stored_as_float32(tmp_path: Path) -> None:
    def f64_embedder(image: np.ndarray) -> DetectedFace:
        return DetectedFace(np.linspace(-2, 2, 512), (270.0, 170.0, 370.0, 290.0))

    lib = FaceLibrary(tmp_path / "faces", f64_embedder)
    entry = lib.add_image(make_image(), "F64")
    assert lib.embedding(entry.id).dtype == np.float32
    np.testing.assert_allclose(lib.embedding(entry.id), np.linspace(-2, 2, 512), rtol=1e-6)


# -- errors -------------------------------------------------------------------


def test_unreadable_files_raise(lib: FaceLibrary, tmp_path: Path, embedder: FakeEmbedder) -> None:
    text = tmp_path / "notes.jpg"
    text.write_text("definitely not a jpeg", encoding="utf-8")
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    folder = tmp_path / "folder.png"
    folder.mkdir()

    for path in (text, empty, folder, tmp_path / "missing.png"):
        with pytest.raises(UnreadableImageError):
            lib.add_file(path)
    assert embedder.calls == 0
    assert lib.list() == []
    assert library_files(lib) == set()


def test_no_face_raises_and_writes_nothing(lib: FaceLibrary, tmp_path: Path) -> None:
    source = write_png(tmp_path / "wall.png", make_image(box=None))
    with pytest.raises(NoFaceError):
        lib.add_file(source)
    with pytest.raises(NoFaceError):
        lib.add_image(make_image(box=None), "Wall")
    assert lib.list() == []
    assert library_files(lib) == set()


def test_error_types_are_value_errors() -> None:
    assert issubclass(NoFaceError, ValueError)
    assert issubclass(UnreadableImageError, ValueError)


def test_failed_index_write_rolls_back(
    lib: FaceLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = library.write_atomic

    def flaky_write(path: Path, data: bytes) -> None:
        if path.name == "index.json":
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(library, "write_atomic", flaky_write)
    with pytest.raises(OSError):
        lib.add_image(make_image(), "Doomed")
    assert lib.list() == []
    assert library_files(lib) == set()


# -- ordering and editing -----------------------------------------------------


def add_three(lib: FaceLibrary) -> list[str]:
    colors = [(200, 40, 40), (40, 200, 40), (40, 40, 200)]
    return [lib.add_image(make_image(color=c), n).id for c, n in zip(colors, "abc")]


def test_list_keeps_insertion_order_and_move_persists(
    lib: FaceLibrary, embedder: FakeEmbedder
) -> None:
    a, b, c = add_three(lib)
    assert [e.id for e in lib.list()] == [a, b, c]

    lib.move(c, 0)
    assert [e.id for e in lib.list()] == [c, a, b]
    lib.move(c, 99)  # clamped to the end
    assert [e.id for e in lib.list()] == [a, b, c]
    lib.move(b, -5)  # clamped to the start
    assert [e.id for e in lib.list()] == [b, a, c]

    reloaded = FaceLibrary(lib.root, embedder)
    assert [e.id for e in reloaded.list()] == [b, a, c]
    with pytest.raises(KeyError):
        lib.move("000000000000", 0)


def test_rename_persists(lib: FaceLibrary, embedder: FakeEmbedder) -> None:
    a, _, _ = add_three(lib)
    lib.rename(a, "  Grace   Hopper ")
    assert lib.get(a).name == "Grace Hopper"
    lib.rename(a, "   ")  # blank keeps the old name
    assert lib.get(a).name == "Grace Hopper"
    lib.rename(a, "y" * 80)
    assert lib.get(a).name == "y" * 40

    assert FaceLibrary(lib.root, embedder).get(a).name == "y" * 40
    with pytest.raises(KeyError):
        lib.rename("000000000000", "Nobody")


def test_get_returns_a_copy(lib: FaceLibrary) -> None:
    entry = lib.add_image(make_image(), "Original")
    entry.name = "Hacked"
    lib.list()[0].name = "Hacked too"
    assert lib.get(entry.id).name == "Original"
    assert lib.get("000000000000") is None


def test_remove_deletes_files_and_persists(lib: FaceLibrary, embedder: FakeEmbedder) -> None:
    a, b, c = add_three(lib)
    removed = lib.get(b)
    lib.embedding(b)  # warm the cache
    lib.remove(b)

    assert [e.id for e in lib.list()] == [a, c]
    assert lib.get(b) is None
    for name in (removed.image, removed.thumb, removed.embedding):
        assert not (lib.root / name).exists()
    with pytest.raises(KeyError):
        lib.embedding(b)
    with pytest.raises(KeyError):
        lib.image_path(b)

    lib.remove(b)  # already gone: no-op
    assert [e.id for e in FaceLibrary(lib.root, embedder).list()] == [a, c]


# -- embeddings ---------------------------------------------------------------


def test_embedding_is_cached_and_read_only(lib: FaceLibrary, embedder: FakeEmbedder) -> None:
    entry = lib.add_image(make_image(), "Cached")
    first = lib.embedding(entry.id)
    assert lib.embedding(entry.id) is first
    assert first.dtype == np.float32 and first.shape == (512,)
    with pytest.raises(ValueError):
        first[0] = 1.0

    # A fresh library loads from disk once, then serves from memory.
    reloaded = FaceLibrary(lib.root, embedder)
    from_disk = reloaded.embedding(entry.id)
    np.testing.assert_array_equal(from_disk, first)
    (lib.root / entry.embedding).unlink()
    assert reloaded.embedding(entry.id) is from_disk


def test_switching_faces_does_not_call_the_embedder(
    lib: FaceLibrary, embedder: FakeEmbedder
) -> None:
    ids = add_three(lib)
    calls = embedder.calls
    for face_id in ids * 10:
        lib.embedding(face_id)
    assert embedder.calls == calls


# -- thumbnails ---------------------------------------------------------------


def test_thumbnail_is_square_and_centred_on_face(lib: FaceLibrary) -> None:
    color = (60, 170, 230)
    entry = lib.add_image(make_image(800, 600, (500, 100, 600, 220), color), "Thumb")
    thumb = read_image(lib.thumb_path(entry.id))
    assert thumb.shape == (256, 256, 3)

    assert np.abs(thumb[128, 128].astype(int) - color).max() <= 6  # face in the middle
    assert thumb[5, 5].max() < FACE_LEVEL  # background in the corner
    # Box is 100x120, crop side 120 * 1.8 = 216 -> face spans 100/216 of the width.
    face_width = int((thumb[128].max(axis=1) > FACE_LEVEL).sum())
    assert abs(face_width - round(256 * 100 / 216)) <= 4


def test_thumbnail_pads_when_face_is_at_the_edge(lib: FaceLibrary) -> None:
    entry = lib.add_image(make_image(400, 300, (0, 0, 200, 200)), "Edge")
    thumb = read_image(lib.thumb_path(entry.id))
    assert thumb.shape == (256, 256, 3)
    assert thumb[128, 128].max() > FACE_LEVEL
    assert thumb[0, 0].max() > FACE_LEVEL  # padding repeats the edge, no black hole


def test_thumbnail_survives_a_face_filling_the_photo(lib: FaceLibrary) -> None:
    entry = lib.add_image(make_image(300, 300, (0, 0, 300, 300)), "Close-up")
    assert read_image(lib.thumb_path(entry.id)).shape == (256, 256, 3)


# -- loading ------------------------------------------------------------------


def test_entries_with_missing_files_are_dropped_on_load(
    lib: FaceLibrary, embedder: FakeEmbedder, caplog: pytest.LogCaptureFixture
) -> None:
    a, b, c = add_three(lib)
    (lib.root / f"{b}.npy").unlink()
    (lib.root / f"{c}_thumb.jpg").unlink()

    with caplog.at_level(logging.WARNING):
        reloaded = FaceLibrary(lib.root, embedder)
    assert [e.id for e in reloaded.list()] == [a]
    assert "Dropped 2" in caplog.text
    index = json.loads((lib.root / "index.json").read_text(encoding="utf-8"))
    assert [f["id"] for f in index["faces"]] == [a]


@pytest.mark.parametrize("content", ["{broken", "[]", '{"version": 1, "faces": "nope"}'])
def test_corrupt_index_starts_empty(
    tmp_path: Path, embedder: FakeEmbedder, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "faces"
    root.mkdir()
    (root / "index.json").write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        lib = FaceLibrary(root, embedder)
    assert lib.list() == []
    assert caplog.records
    assert (root / "index.corrupt.json").read_text(encoding="utf-8") == content  # kept for recovery
    lib.add_image(make_image(), "Fresh start")
    assert len(FaceLibrary(root, embedder).list()) == 1


def test_index_cannot_point_outside_the_library(tmp_path: Path, embedder: FakeEmbedder) -> None:
    root = tmp_path / "faces"
    root.mkdir()
    for name in ("evil.jpg", "evil_thumb.jpg", "evil.npy"):
        (tmp_path / name).write_bytes(b"x")
    hostile = {
        "id": "abcdefabcdef",
        "name": "Evil",
        "created": 0,
        "image": "../evil.jpg",
        "thumb": "../evil_thumb.jpg",
        "embedding": "../evil.npy",
    }
    index = {"version": 1, "faces": [hostile]}
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    lib = FaceLibrary(root, embedder)
    assert lib.list() == []
    lib.remove("abcdefabcdef")
    assert (tmp_path / "evil.jpg").exists()


# -- paths and threads --------------------------------------------------------


def test_unicode_paths(tmp_path: Path, embedder: FakeEmbedder) -> None:
    root = tmp_path / "Библиотека лиц ✨"
    source = write_png(tmp_path / "фото" / "Анна_Каренина.png", make_image())
    lib = FaceLibrary(root, embedder)
    entry = lib.add_file(source)
    assert entry.name == "Анна Каренина"
    assert read_image(lib.thumb_path(entry.id)).shape == (256, 256, 3)

    reloaded = FaceLibrary(root, embedder)
    assert [e.name for e in reloaded.list()] == ["Анна Каренина"]
    np.testing.assert_array_equal(reloaded.embedding(entry.id), lib.embedding(entry.id))


def test_concurrent_adds_from_threads(tmp_path: Path) -> None:
    embedder = FakeEmbedder(delay=0.002)
    lib = FaceLibrary(tmp_path / "faces", embedder)
    images = [make_image(color=(110 + i, 40 + 3 * i, 250 - 2 * i)) for i in range(32)]
    stop = threading.Event()

    def reader() -> None:  # the UI thread keeps reading while imports run
        while not stop.wait(0.001):
            for entry in lib.list():
                lib.embedding(entry.id)

    watcher = threading.Thread(target=reader)
    watcher.start()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            names = [f"Face {i}" for i in range(len(images))]
            entries = list(pool.map(lib.add_image, images, names))
    finally:
        stop.set()
        watcher.join()

    assert len({e.id for e in entries}) == 32
    assert embedder.max_active == 1  # the embedder is never called concurrently
    listed = lib.list()
    assert {e.id for e in listed} == {e.id for e in entries}

    reloaded = FaceLibrary(lib.root, embedder)
    assert [e.id for e in reloaded.list()] == [e.id for e in listed]
    for entry, image in zip(entries, images):
        expected = fake_face(image)
        assert expected is not None
        np.testing.assert_array_equal(reloaded.embedding(entry.id), expected.embedding)
    assert not [p for p in lib.root.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("sips") is None, reason="HEIC import uses macOS sips"
)
def test_heic_import_on_macos(lib: FaceLibrary, tmp_path: Path) -> None:
    png = write_png(tmp_path / "source.png", make_image())
    heic = tmp_path / "iPhone_photo.heic"
    command = ["sips", "-s", "format", "heic", str(png), "--out", str(heic)]
    subprocess.run(command, check=True, capture_output=True)
    entry = lib.add_file(heic)
    assert entry.name == "iPhone photo"
    assert read_image(lib.thumb_path(entry.id)).shape == (256, 256, 3)
