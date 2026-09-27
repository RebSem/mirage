"""Video pipeline: probe, reader/writer, identity tracking, render job with fake models.

Clips are synthesised with ffmpeg (testsrc2 + sine); no models, camera or
display. Tests that need ffmpeg are skipped when it is not installed.
"""

import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from mirage.media import video as V
from mirage.media.types import RenderOptions, VideoIdentity

TOOLS = V.find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(TOOLS is None, reason="ffmpeg is not installed")

W, H, FPS, SECONDS = 320, 240, 24, 2
FRAMES = FPS * SECONDS


# ── helpers ──────────────────────────────────────────────────────────────


def _ffmpeg(*args: str) -> None:
    assert TOOLS is not None
    subprocess.run([TOOLS[0], "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args], check=True, timeout=60)


def _video_codec() -> list[str]:
    """H.264 when this ffmpeg has libx264, else its built-in MPEG-4 encoder."""
    assert TOOLS is not None
    encoders = subprocess.run([TOOLS[0], "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if " libx264 " in encoders:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    return ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]


def _make_clip(path: Path, size: tuple[int, int] = (W, H), seconds: float = SECONDS, audio: bool = True) -> Path:
    video = ["-f", "lavfi", "-i", f"testsrc2=s={size[0]}x{size[1]}:r={FPS}:d={seconds}"]
    sound = ["-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-c:a", "aac"] if audio else []
    _ffmpeg(*video, *sound, *_video_codec(), str(path))
    return path


def _mean_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def _read_all(path: Path) -> list[np.ndarray]:
    with V.FrameReader(path, V.probe(path)) as reader:
        return list(reader)


def _leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("."))


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if TOOLS is None:
        pytest.skip("ffmpeg is not installed")
    folder = tmp_path_factory.mktemp("clips")
    plain = _make_clip(folder / "plain.mp4")
    # iPhone-style portrait: stored landscape, display matrix says turn 90° clockwise
    rotated = folder / "rotated.mp4"
    _ffmpeg("-display_rotation", "-90", "-i", str(plain), "-c", "copy", str(rotated))
    silent = _make_clip(folder / "silent.mp4", audio=False)
    return {"plain": plain, "rotated": rotated, "silent": silent}


@pytest.fixture
def clip_copy(clips: dict[str, Path], tmp_path: Path):
    """A private copy of a clip, so outputs land in a folder of the test's own."""

    def make(name: str) -> Path:
        dst = tmp_path / f"{name}.mp4"
        dst.write_bytes(clips[name].read_bytes())
        return dst

    return make


# ── find_ffmpeg / output_path (no ffmpeg needed) ─────────────────────────


def _fake_tool(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_find_ffmpeg_falls_back_to_homebrew_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(V.shutil, "which", lambda name: None)
    monkeypatch.setattr(V, "_SEARCH_DIRS", (str(tmp_path / "missing"), str(tmp_path)))
    assert V.find_ffmpeg() is None
    ffmpeg, ffprobe = _fake_tool(tmp_path, "ffmpeg"), _fake_tool(tmp_path, "ffprobe")
    assert V.find_ffmpeg() == (str(ffmpeg), str(ffprobe))


def test_find_ffmpeg_prefers_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    on_path = {name: str(_fake_tool(tmp_path, name)) for name in ("ffmpeg", "ffprobe")}
    monkeypatch.setattr(V.shutil, "which", on_path.get)
    monkeypatch.setattr(V, "_SEARCH_DIRS", ())
    found = V.find_ffmpeg()
    assert found == (on_path["ffmpeg"], on_path["ffprobe"]) and all(os.path.isabs(p) for p in found)


def test_output_path_never_overwrites(tmp_path: Path):
    src = tmp_path / "holiday.mov"
    src.write_bytes(b"x")
    first = V.output_path(src)
    assert first == tmp_path / "holiday-mirage.mp4"
    first.write_bytes(b"x")
    second = V.output_path(src)
    assert second == tmp_path / "holiday-mirage-2.mp4"
    second.write_bytes(b"x")
    assert V.output_path(src) == tmp_path / "holiday-mirage-3.mp4"


# ── identity tracker (pure numpy) ────────────────────────────────────────


def _identities(n: int, seed: int = 0) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [rng.normal(size=512).astype(np.float32) for _ in range(n)]


def _face(x: float, y: float = 100, w: float = 60) -> tuple[np.ndarray, np.ndarray]:
    bbox = np.array([x, y, x + w, y + w], dtype=np.float32)
    kps = np.array(
        [[x + 18, y + 24], [x + 42, y + 24], [x + 30, y + 36], [x + 21, y + 48], [x + 39, y + 48]], dtype=np.float32
    )
    return bbox, kps


def _blend(target: np.ndarray, other: np.ndarray, similarity: float) -> np.ndarray:
    """A vector with the given cosine similarity to `target` (other ⟂-ised)."""
    t = target / np.linalg.norm(target)
    o = other - (other @ t) * t
    o /= np.linalg.norm(o)
    return (similarity * t + np.sqrt(1 - similarity**2) * o).astype(np.float32)


def test_tracker_reidentifies_on_a_cadence_not_every_frame():
    ids = _identities(2)
    tracker = V.IdentityTracker(ids, reid_every=12)
    calls: list[int] = []
    for frame in range(50):
        result = tracker.update(frame, [_face(100 + frame % 3)], lambda d, f=frame: calls.append(f) or ids[1])
        assert [r.identity for r in result] == [1]
    assert calls == [0, 12, 24, 36, 48]
    assert tracker.embed_calls == 5


def test_tracker_keeps_identities_when_two_people_cross():
    ids = _identities(3)
    tracker = V.IdentityTracker(ids[:2], reid_every=12)
    calls = 0
    for frame in range(41):
        people = [(0, _face(5.0 * frame)), (1, _face(200 - 5.0 * frame))]
        people.sort(key=lambda p: float(p[1][0][0]))       # detector order changes as they cross
        noise = np.random.default_rng(frame).normal(scale=0.02, size=512).astype(np.float32)

        def embed(d: int, people=people, noise=noise) -> np.ndarray:
            nonlocal calls
            calls += 1
            return ids[people[d][0]] + noise

        result = tracker.update(frame, [p[1] for p in people], embed)
        assert [r.identity for r in result] == [p[0] for p in people], f"frame {frame}"
    assert calls < 41, "recognition must not run for every face on every frame"


def test_tracker_leaves_strangers_alone_and_gives_each_person_once():
    ids = _identities(3)
    tracker = V.IdentityTracker(ids[:2])
    stranger = tracker.update(0, [_face(0)], lambda d: ids[2])
    assert stranger[0].identity is None
    tracker = V.IdentityTracker(ids[:2])
    both_look_like_0 = [_blend(ids[0], ids[2], 0.9), _blend(ids[0], ids[2], 0.6)]
    result = tracker.update(0, [_face(0), _face(300)], lambda d: both_look_like_0[d])
    assert [r.identity for r in result] == [0, None]


def test_tracker_hysteresis_keeps_a_known_face_through_a_weak_look():
    ids = _identities(3)
    tracker = V.IdentityTracker(ids[:2], threshold=0.40, reid_every=1)
    looks = {0: ids[0], 1: _blend(ids[0], ids[2], 0.33), 2: _blend(ids[0], ids[2], 0.2)}
    got = [tracker.update(f, [_face(100)], lambda d, f=f: looks[f])[0].identity for f in range(3)]
    assert got == [0, 0, None]
    fresh = V.IdentityTracker(ids[:2], threshold=0.40)
    assert fresh.update(0, [_face(100)], lambda d: looks[1])[0].identity is None


def test_tracker_forgets_faces_that_leave_and_smooths_boxes():
    ids = _identities(1)
    tracker = V.IdentityTracker(ids, keep_missing=5)
    calls: list[int] = []

    def embed(d: int, frame: int) -> np.ndarray:
        calls.append(frame)
        return ids[0]

    tracker.update(0, [_face(100)], lambda d: embed(d, 0))
    jittered = tracker.update(1, [_face(104)], lambda d: embed(d, 1))[0]
    assert 100 < jittered.bbox[0] < 104 and jittered.kps.shape == (5, 2)
    for frame in range(2, 9):
        assert tracker.update(frame, [], lambda d, f=frame: embed(d, f)) == []
    tracker.update(9, [_face(100)], lambda d: embed(d, 9))
    assert calls == [0, 9]


def test_tracker_without_identities_never_runs_recognition():
    tracker = V.IdentityTracker([])
    result = tracker.update(0, [_face(0)], lambda d: pytest.fail("embed_fn called"))
    assert result[0].identity is None


# ── probe / sample_frames ────────────────────────────────────────────────


@needs_ffmpeg
def test_probe_reads_size_rate_length_and_audio(clips: dict[str, Path]):
    info = V.probe(clips["plain"])
    assert (info.width, info.height, info.rotation) == (W, H, 0)
    assert info.fps == pytest.approx(FPS)
    assert info.frames == FRAMES
    assert info.duration == pytest.approx(SECONDS, abs=0.1)
    assert info.has_audio and info.codec in ("h264", "mpeg4")
    assert V.probe(clips["silent"]).has_audio is False


@needs_ffmpeg
def test_probe_applies_rotation(clips: dict[str, Path]):
    info = V.probe(clips["rotated"])
    assert info.rotation == 90
    assert (info.width, info.height) == (H, W)


@needs_ffmpeg
def test_probe_rejects_non_videos(tmp_path: Path):
    text = tmp_path / "notes.mp4"
    text.write_text("definitely not a video")
    with pytest.raises(ValueError, match="notes.mp4"):
        V.probe(text)
    picture = tmp_path / "still.png"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=64x48:d=1", "-frames:v", "1", str(picture))
    with pytest.raises(ValueError, match="picture"):
        V.probe(picture)
    with pytest.raises(FileNotFoundError):
        V.probe(tmp_path / "missing.mp4")


@needs_ffmpeg
def test_sample_frames_are_evenly_spaced_and_upright(clips: dict[str, Path]):
    info = V.probe(clips["plain"])
    samples = V.sample_frames(clips["plain"], info, count=8)
    assert len(samples) == 8
    times = [t for t, _ in samples]
    assert times == sorted(times) and 0 <= times[0] < 0.3 and SECONDS - 0.3 < times[-1] < SECONDS
    assert all(frame.shape == (H, W, 3) and frame.dtype == np.uint8 for _, frame in samples)
    assert _mean_diff(samples[0][1], samples[-1][1]) > 5        # different moments, not one frame 8 times
    rotated = V.probe(clips["rotated"])
    assert all(frame.shape == (W, H, 3) for _, frame in V.sample_frames(clips["rotated"], rotated, count=3))


# ── FrameReader ──────────────────────────────────────────────────────────


@needs_ffmpeg
def test_reader_yields_every_frame_upright(clips: dict[str, Path]):
    frames = _read_all(clips["plain"])
    assert len(frames) == FRAMES
    assert frames[0].shape == (H, W, 3) and frames[0].dtype == np.uint8 and frames[0].flags.writeable
    turned = _read_all(clips["rotated"])
    assert len(turned) == FRAMES and turned[0].shape == (W, H, 3)
    assert _mean_diff(turned[0], np.rot90(frames[0], k=-1)) < 2    # turned clockwise, as displayed


@needs_ffmpeg
def test_reader_falls_back_when_a_decoder_fails(clips: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    real_cmd = V._decode_cmd

    def broken_first(ffmpeg, stream, mode, *args, **kwargs):
        cmd = real_cmd(ffmpeg, stream, mode, *args, **kwargs)
        return cmd[:1] + ["-no-such-option"] + cmd[1:] if mode == "vt" else cmd

    monkeypatch.setattr(V, "_decode_modes", lambda stream: ["vt", "sw"])
    monkeypatch.setattr(V, "_decode_cmd", broken_first)
    with V.FrameReader(clips["plain"], V.probe(clips["plain"])) as reader:
        assert sum(1 for _ in reader) == FRAMES
        assert reader.mode == "sw"


@needs_ffmpeg
def test_reader_handles_big_frames_and_close_from_another_thread(tmp_path: Path):
    big = _make_clip(tmp_path / "big.mp4", size=(3840, 2160), seconds=0.25, audio=False)
    info = V.probe(big)
    reader = V.FrameReader(big, info)
    with reader:
        first = reader.read()
        assert first is not None and first.shape == (2160, 3840, 3)
        time.sleep(0.2)                         # let ffmpeg fill the pipe and block
        closer = threading.Thread(target=reader.close)
        closer.start()
        closer.join(5)
        assert not closer.is_alive()
        assert reader.read() is None


# ── FrameWriter ──────────────────────────────────────────────────────────


@needs_ffmpeg
def test_writer_roundtrip_keeps_frames_rate_and_audio(clip_copy):
    src = clip_copy("plain")
    info = V.probe(src)
    dst = src.with_name("out.mp4")
    source_frames = _read_all(src)
    with V.FrameWriter(dst, info, src) as writer:
        for frame in source_frames:
            writer.write(frame)
    assert writer.audio_kept
    out = V.probe(dst)
    assert abs(out.frames - FRAMES) <= 1
    assert out.fps == pytest.approx(FPS)
    assert (out.width, out.height, out.codec) == (W, H, "h264")
    assert out.has_audio
    again = _read_all(dst)
    assert _mean_diff(again[10], source_frames[10]) < 6
    assert _leftovers(dst.parent) == []


@needs_ffmpeg
def test_writer_without_source_has_no_audio(clip_copy):
    src = clip_copy("plain")
    info = V.probe(src)
    dst = src.with_name("mute.mp4")
    with V.FrameWriter(dst, info) as writer:
        for frame in _read_all(src)[:10]:
            writer.write(frame)
    out = V.probe(dst)
    assert not out.has_audio and abs(out.frames - 10) <= 1


@needs_ffmpeg
def test_writer_falls_back_to_libx264(clip_copy, monkeypatch: pytest.MonkeyPatch):
    encoders = subprocess.run([TOOLS[0], "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if " libx264 " not in encoders:
        pytest.skip("this ffmpeg has no libx264")
    monkeypatch.setattr(V, "_videotoolbox_works", lambda *args: False)
    src = clip_copy("silent")
    info = V.probe(src)
    dst = src.with_name("x264.mp4")
    with V.FrameWriter(dst, info, src) as writer:
        assert writer.encoder == "libx264"
        for frame in _read_all(src)[:12]:
            writer.write(frame)
    assert V.probe(dst).codec == "h264"


@needs_ffmpeg
def test_writer_abort_leaves_nothing_behind(clip_copy):
    src = clip_copy("plain")
    info = V.probe(src)
    dst = src.with_name("partial.mp4")
    frames = _read_all(src)
    writer = V.FrameWriter(dst, info, src)
    for frame in frames[:10]:
        writer.write(frame)
    writer.abort()
    assert not dst.exists() and _leftovers(dst.parent) == []
    with pytest.raises(KeyError):
        with V.FrameWriter(dst, info, src) as failing:
            failing.write(frames[0])
            raise KeyError("boom")
    assert not dst.exists() and _leftovers(dst.parent) == []
    with pytest.raises(ValueError):
        with V.FrameWriter(dst, info, src) as wrong_size:
            wrong_size.write(np.zeros((10, 10, 3), np.uint8))
    assert not dst.exists()


# ── render_video with fake models ────────────────────────────────────────

GREEN = (0, 255, 0)
BOX = (100, 60, 200, 160)          # x1, y1, x2, y2 in the 320x240 test clip


class FakeModels:
    """Detects one fixed face for the first `face_frames` frames; the swap paints it green."""

    def __init__(self, identity: np.ndarray, face_frames: int = FRAMES, fail_at: int | None = None) -> None:
        self.identity = identity
        self.face_frames = face_frames
        self.fail_at = fail_at
        self.detected = 0
        self.embeds = 0
        self.swaps = 0
        self.on_swap = None

    def hooks(self) -> V.VideoHooks:
        return V.VideoHooks(detect=self.detect, embed=self.embed, swap=self.swap)

    def detect(self, frame: np.ndarray) -> list:
        self.detected += 1
        return [_face(BOX[0], BOX[1], BOX[2] - BOX[0])] if self.detected <= self.face_frames else []

    def embed(self, frame: np.ndarray, bbox: np.ndarray, kps: np.ndarray) -> np.ndarray:
        self.embeds += 1
        return self.identity

    def swap(self, frame: np.ndarray, bbox: np.ndarray, kps: np.ndarray, source: np.ndarray) -> np.ndarray:
        self.swaps += 1
        if self.on_swap is not None:
            self.on_swap(self.swaps)
        if self.fail_at is not None and self.swaps >= self.fail_at:
            raise RuntimeError("model exploded")
        x1, y1, x2, y2 = (int(v) for v in bbox)
        frame[y1:y2, x1:x2] = GREEN
        return frame


def _is_green(frame: np.ndarray) -> bool:
    x1, y1, x2, y2 = BOX
    b, g, r = frame[y1 + 10 : y2 - 10, x1 + 10 : x2 - 10].reshape(-1, 3).mean(axis=0)
    return g > 200 and b < 60 and r < 60


@needs_ffmpeg
def test_render_swaps_the_chosen_person_and_keeps_audio(clip_copy):
    src = clip_copy("plain")
    person, face = _identities(2)
    models = FakeModels(person, face_frames=24)
    events = []
    dst = V.render_video(
        src, V.output_path(src), [VideoIdentity(person, face)], RenderOptions(), progress=events.append, hooks=models.hooks()
    )
    assert dst == src.with_name("plain-mirage.mp4") and dst.exists()
    out = V.probe(dst)
    assert out.has_audio and abs(out.frames - FRAMES) <= 1 and out.fps == pytest.approx(FPS)
    frames = _read_all(dst)
    originals = _read_all(src)
    assert all(_is_green(f) for f in frames[:22])
    assert not any(_is_green(f) for f in frames[26:])
    assert _mean_diff(frames[40], originals[40]) < 6          # frames without faces pass through
    assert models.swaps == 24 and models.embeds <= 3          # recognition every 12 frames, not every frame
    stages = [e.stage for e in events]
    assert stages[0] == "probe" and "render" in stages and stages[-1] == "done"
    assert events[-1].done == events[-1].total == len(frames)
    assert events[-1].extra["encoder"] in ("h264_videotoolbox", "libx264")
    assert _leftovers(dst.parent) == []


@needs_ffmpeg
def test_render_leaves_strangers_alone(clip_copy):
    src = clip_copy("silent")
    person, stranger, face = _identities(3)
    models = FakeModels(stranger)
    dst = V.render_video(src, src.with_name("out.mp4"), [VideoIdentity(person, face)], RenderOptions(), hooks=models.hooks())
    assert models.swaps == 0
    assert not V.probe(dst).has_audio
    assert not any(_is_green(f) for f in _read_all(dst))


@needs_ffmpeg
def test_render_cancel_removes_the_partial_file(clip_copy):
    src = clip_copy("plain")
    person, face = _identities(2)
    models = FakeModels(person)
    cancel = threading.Event()
    models.on_swap = lambda n: cancel.set() if n == 5 else None
    dst = src.with_name("cancelled.mp4")
    with pytest.raises(V.VideoCancelled):
        V.render_video(src, dst, [VideoIdentity(person, face)], RenderOptions(), cancel=cancel, hooks=models.hooks())
    assert not dst.exists() and _leftovers(src.parent) == []
    assert models.swaps < FRAMES


@needs_ffmpeg
def test_render_errors_are_reraised_without_output(clip_copy):
    src = clip_copy("plain")
    person, face = _identities(2)
    models = FakeModels(person, fail_at=3)
    dst = src.with_name("failed.mp4")
    with pytest.raises(RuntimeError, match="model exploded"):
        V.render_video(src, dst, [VideoIdentity(person, face)], RenderOptions(), hooks=models.hooks())
    assert not dst.exists() and _leftovers(src.parent) == []
    with pytest.raises(ValueError):
        V.render_video(src, src, [], RenderOptions(), hooks=models.hooks())


# ── HDR (macOS VideoToolbox) ─────────────────────────────────────────────


@needs_ffmpeg
@pytest.mark.skipif(sys.platform != "darwin", reason="VideoToolbox is macOS only")
def test_hlg_video_is_tone_mapped_on_videotoolbox(tmp_path: Path):
    hlg = tmp_path / "hlg.mov"
    try:
        _ffmpeg(
            "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=0.5",
            "-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc,format=p010le",
            "-c:v", "hevc_videotoolbox", "-profile:v", "main10", "-b:v", "2M", "-tag:v", "hvc1", str(hlg),
        )
        turned = tmp_path / "hlg-portrait.mov"
        _ffmpeg("-display_rotation", "-90", "-i", str(hlg), "-c", "copy", str(turned))
    except subprocess.CalledProcessError:
        pytest.skip("this Mac cannot encode HEVC 10-bit")
    info = V.probe(turned)
    assert V._inspect(turned).hdr and (info.width, info.height) == (H, W)
    with V.FrameReader(turned, info) as reader:
        frames = list(reader)
        assert reader.mode == "vt-hdr"
    assert len(frames) == FPS // 2 and frames[0].shape == (W, H, 3)
