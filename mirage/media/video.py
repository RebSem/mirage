"""Video files: probe, decode and encode with ffmpeg, follow people, render a swap.

ffmpeg does all the media work in child processes that talk raw BGR frames
over pipes, so anything it can read works and no video codec runs in Python:

    FrameReader ─► detect + track ─► swap ─► FrameWriter
    (ffmpeg,       (GPU, thread;     (Neural Engine,  (h264_videotoolbox,
     own thread)    re-id at times)   calling thread)   own thread)

Frames are decoded upright (rotation metadata applied) at one constant frame
rate (the source's nominal rate, or its average for truly variable ones) and
encoded at exactly that rate, so the original audio, copied back in a final
remux, stays in sync.
"""

from __future__ import annotations

import functools
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

import numpy as np

from mirage.media.types import RenderOptions, VideoIdentity, VideoInfo, VideoProgress
from mirage.power import AwakeGuard
from mirage.tracking import FaceSmoother

log = logging.getLogger(__name__)

# bbox (4,) x1, y1, x2, y2 and kps (5, 2), in frame pixels
Detection = tuple[np.ndarray, np.ndarray]

_SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")  # a Finder-launched app has no Homebrew PATH
_PROBE_TIMEOUT = 30.0
_MP4_AUDIO = frozenset({"aac", "alac", "mp3"})             # copied as is; anything else → AAC
_EFFICIENT_CODECS = frozenset({"hevc", "vp9", "av1"})      # need more H.264 bits for the same quality
# Decoders VideoToolbox may accelerate; ffmpeg itself falls back to software if it can't.
_VT_DECODE = frozenset({"h264", "hevc", "mpeg1video", "mpeg2video", "mpeg4", "h263", "prores", "vp9", "av1"})
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})  # PQ, HLG (iPhone videos are HLG by default)
_QUEUE_BYTES = 64 << 20                                    # frames in flight between stages, per queue


class FFmpegMissingError(RuntimeError):
    """ffmpeg/ffprobe are not installed (brew install ffmpeg)."""


class VideoCancelled(Exception):
    """render_video() was cancelled; the partial output has been removed."""


# ── ffmpeg ───────────────────────────────────────────────────────────────


def find_ffmpeg() -> tuple[str, str] | None:
    """Absolute (ffmpeg, ffprobe) paths, or None when either is missing."""
    found: list[str] = []
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if path is None:
            for folder in _SEARCH_DIRS:
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    path = candidate
                    break
        if path is None:
            return None
        found.append(os.path.abspath(path))
    return found[0], found[1]


def _tools() -> tuple[str, str]:
    tools = find_ffmpeg()
    if tools is None:
        raise FFmpegMissingError("ffmpeg is not installed (install it with: brew install ffmpeg)")
    return tools


class _StderrTail:
    """Drains a child's stderr in a thread (a full pipe would stall ffmpeg) and keeps the tail."""

    def __init__(self, pipe) -> None:
        self._tail = bytearray()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, args=(pipe,), name="mirage-ffmpeg-stderr", daemon=True)
        self._thread.start()

    def _drain(self, pipe) -> None:
        try:
            while chunk := pipe.read(4096):
                with self._lock:
                    self._tail += chunk
                    del self._tail[:-8192]
        except (OSError, ValueError):
            pass

    def join(self, timeout: float = 2.0) -> None:
        self._thread.join(timeout)

    def text(self) -> str:
        with self._lock:
            data = bytes(self._tail)
        lines = [line.strip() for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
        return " | ".join(lines[-6:]) or "no details from ffmpeg"


def _stop(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg (pid %s) did not exit after kill", proc.pid)


def _close_quietly(*pipes) -> None:
    for pipe in pipes:
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass


# ── probing ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Stream:
    """What the reader and writer need beyond VideoInfo (kept out of the shared types)."""

    info: VideoInfo
    index: int                 # absolute index of the video stream in the file
    rate: str                  # exact rational frame rate, e.g. "30000/1001"
    bit_rate: int | None       # video bits per second, if known
    pix_fmt: str
    matrix: str                # YUV↔RGB matrix for the scale filter: bt709 | bt601 | bt2020
    hdr: bool
    sar: str | None            # non-square pixels, e.g. "32/27"
    audio_index: int | None
    audio_codec: str


def probe(path: str | os.PathLike) -> VideoInfo:
    """Size (upright), frame rate, length and audio of a video. ValueError if it isn't one."""
    return replace(_inspect(path).info)


def _inspect(path: str | os.PathLike) -> _Stream:
    path = os.fspath(path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"{path} does not exist") from None
    return _inspect_cached(path, st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=32)
def _inspect_cached(path: str, mtime_ns: int, size: int) -> _Stream:
    import json

    name = os.path.basename(path)
    cmd = [_tools()[1], "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ValueError(f"{name}: reading the file took too long") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"{name} is not a video Mirage can read ({detail[-1] if detail else 'unknown format'})")
    try:
        data = json.loads(result.stdout or b"{}")
    except ValueError:
        raise ValueError(f"{name} is not a video Mirage can read") from None
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    if video is None:
        raise ValueError(f"{name} has no video in it")
    formats = str(fmt.get("format_name", "")).split(",")
    if any(f == "image2" or f.endswith("_pipe") for f in formats):
        raise ValueError(f"{name} is a picture, not a video")

    coded_w, coded_h = int(video.get("width") or 0), int(video.get("height") or 0)
    if coded_w <= 0 or coded_h <= 0:
        raise ValueError(f"{name}: the video has no picture size")
    rotation = _rotation(video)
    width, height = (coded_h, coded_w) if rotation in (90, 270) else (coded_w, coded_h)

    avg, nominal = _fraction(video.get("avg_frame_rate")), _fraction(video.get("r_frame_rate"))
    fps = float(avg or nominal or 30)
    # Frames are re-timed to one constant rate for decoding and encoding. Phone videos are
    # variable-rate around a nominal rate (avg 29.98, r 30/1): use the nominal one then,
    # the average when they disagree (r can be a timebase like 90000/1).
    rate = nominal if nominal and avg and abs(nominal - avg) <= avg / 100 else (avg or nominal or Fraction(30))
    duration = _float(video.get("duration")) or _float(fmt.get("duration")) or 0.0
    frames = int(_float(video.get("nb_frames")) or 0) or int(round(duration * fps))
    if frames <= 1 and duration <= 0:
        raise ValueError(f"{name} is a picture, not a video")

    audio = [s for s in streams if s.get("codec_type") == "audio"]
    bit_rate = int(_float(video.get("bit_rate")) or 0) or None
    if bit_rate is None and _float(fmt.get("bit_rate")):
        rest = sum(int(_float(s.get("bit_rate")) or 0) for s in audio)
        bit_rate = max(0, int(_float(fmt.get("bit_rate")) or 0) - rest) or None

    info = VideoInfo(
        path=path,
        width=width,
        height=height,
        fps=fps,
        frames=frames,
        duration=duration,
        has_audio=bool(audio),
        rotation=rotation,
        codec=str(video.get("codec_name") or ""),
    )
    transfer = str(video.get("color_transfer") or "")
    sar = str(video.get("sample_aspect_ratio") or "").replace(":", "/")
    return _Stream(
        info=info,
        index=int(video.get("index") or 0),
        rate=f"{rate.numerator}/{rate.denominator}",
        bit_rate=bit_rate,
        pix_fmt=str(video.get("pix_fmt") or ""),
        matrix=_matrix(str(video.get("color_space") or ""), coded_w, coded_h),
        hdr=transfer in _HDR_TRANSFERS,
        sar=sar if sar and _fraction(sar) not in (None, 1) else None,
        audio_index=int(audio[0].get("index") or 0) if audio else None,
        audio_codec=str(audio[0].get("codec_name") or "") if audio else "",
    )


def _rotation(stream: dict) -> int:
    """Clockwise degrees to turn the frames for display (the classic `rotate` tag's sense)."""
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            # ffprobe reports the display matrix counter-clockwise (iPhone portrait: -90)
            return int(round(-float(side["rotation"]) / 90.0)) * 90 % 360
    tag = (stream.get("tags") or {}).get("rotate")
    if tag:
        return int(round(float(tag) / 90.0)) * 90 % 360
    return 0


def _matrix(color_space: str, width: int, height: int) -> str:
    if color_space == "bt709":
        return "bt709"
    if color_space in ("smpte170m", "bt470bg", "fcc"):
        return "bt601"
    if color_space.startswith("bt2020"):
        return "bt2020"
    # untagged: players assume BT.709 for HD and BT.601 for SD
    return "bt709" if height >= 720 or width >= 1280 else "bt601"


def _fraction(text) -> Fraction | None:
    try:
        value = Fraction(str(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if 0 < value <= 1000 else None


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


# ── decoding ─────────────────────────────────────────────────────────────


def _decode_modes(stream: _Stream) -> list[str]:
    """Decoders to try in order: VideoToolbox (tone-mapping HDR on the GPU), then software."""
    modes: list[str] = []
    if sys.platform == "darwin" and stream.info.codec in _VT_DECODE:
        if stream.hdr:
            modes.append("vt-hdr")
        modes.append("vt")
    modes.append("sw")
    return modes


def _decode_cmd(
    ffmpeg: str,
    stream: _Stream,
    mode: str,
    width: int,
    height: int,
    *,
    seek: float | None = None,
    single: bool = False,
) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if mode == "vt":
        cmd += ["-hwaccel", "videotoolbox"]
    elif mode == "vt-hdr":
        # frames stay on the GPU, where ffmpeg's autorotate can't reach: turn them there
        cmd += ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld", "-noautorotate"]
    if seek is not None:
        cmd += ["-ss", f"{seek:.3f}"]
    cmd += ["-i", stream.info.path, "-map", f"0:{stream.index}", "-an", "-sn", "-dn"]
    filters = []
    matrix = stream.matrix
    if mode == "vt-hdr":
        # VideoToolbox tone-maps HLG/PQ to SDR BT.709; plain decoding would look washed out
        filters.append("scale_vt=color_matrix=bt709:color_primaries=bt709:color_transfer=bt709")
        turn = {90: "clock", 180: "reversal", 270: "cclock"}.get(stream.info.rotation)
        if turn:
            filters.append(f"transpose_vt=dir={turn}")
        high_depth = any(bits in stream.pix_fmt for bits in ("10", "12"))
        filters += ["hwdownload", f"format={'p010le' if high_depth else 'nv12'}"]
        matrix = "bt709"
    # an explicit size guarantees the byte count per frame the reader expects
    filters.append(f"scale={width}:{height}:in_color_matrix={matrix}:flags=bicubic")
    filters.append("format=bgr24")
    cmd += ["-vf", ",".join(filters)]
    if single:
        cmd += ["-frames:v", "1"]
    else:
        cmd += ["-fps_mode", "cfr", "-r", stream.rate]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    return cmd


def sample_frames(path: str | os.PathLike, info: VideoInfo, count: int = 8) -> list[tuple[float, np.ndarray]]:
    """About `count` evenly spaced (time, BGR frame) pairs, upright; unreadable spots are skipped."""
    if count <= 0:
        return []
    stream = _inspect(path)
    ffmpeg = _tools()[0]
    duration = info.duration or (info.frames / info.fps if info.fps else 0.0)
    times = [duration * (i + 0.5) / count for i in range(count)] if duration > 0 else [0.0]
    shape = (info.height, info.width, 3)
    size = info.width * info.height * 3
    # one-off frames decode fast in software; HDR still goes through VideoToolbox to be tone-mapped
    modes = ["vt-hdr", "sw"] if "vt-hdr" in _decode_modes(stream) else ["sw"]

    def grab(t: float) -> np.ndarray | None:
        for mode in modes:
            cmd = _decode_cmd(ffmpeg, stream, mode, info.width, info.height, seek=t, single=True)
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=_PROBE_TIMEOUT).stdout
            except subprocess.TimeoutExpired:
                continue
            if len(out) >= size:
                return np.frombuffer(out, np.uint8, count=size).reshape(shape).copy()
        return None

    with ThreadPoolExecutor(max_workers=min(4, len(times))) as pool:
        frames = list(pool.map(grab, times))
    return [(t, frame) for t, frame in zip(times, frames, strict=True) if frame is not None]


class FrameReader:
    """Decoded frames of a video as upright BGR uint8 arrays (context manager and iterator).

    Frames come at one constant rate, the one FrameWriter encodes at for this
    source (variable-rate phone videos are evened out by dropping or repeating
    the odd frame).
    """

    def __init__(self, path: str | os.PathLike, info: VideoInfo) -> None:
        self.path = os.fspath(path)
        self.info = info
        self.frames_read = 0
        self.mode = ""                 # decoder in use: vt-hdr | vt | sw
        self._stream = _inspect(self.path)
        self._shape = (info.height, info.width, 3)
        self._frame_bytes = info.width * info.height * 3
        self._modes = _decode_modes(self._stream)
        self._proc: subprocess.Popen | None = None
        self._stderr: _StderrTail | None = None
        self._io_lock = threading.Lock()   # close() from another thread waits for a read in progress
        self._closed = False

    def __enter__(self) -> FrameReader:
        if self._proc is None:
            self._start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __iter__(self) -> Iterator[np.ndarray]:
        while (frame := self.read()) is not None:
            yield frame

    def read(self) -> np.ndarray | None:
        """The next frame, or None at the end. RuntimeError if ffmpeg fails part-way."""
        if self._closed:
            return None
        if self._proc is None:
            self._start()
        while True:
            frame = self._read_frame()
            if frame is not None:
                self.frames_read += 1
                return frame
            if self._closed:
                return None
            proc = self._proc
            code = proc.wait() if proc is not None else 0
            if self.frames_read == 0 and self._modes:
                log.info("%s decoder gave no frames (%s); trying %s", self.mode, self._stderr_text(), self._modes[0])
                self._start()
                continue
            if code != 0 and not self._closed:
                raise RuntimeError(f"ffmpeg could not decode {os.path.basename(self.path)}: {self._stderr_text()}")
            return None

    def close(self) -> None:
        """Stop decoding. Safe to call from another thread to unblock a read()."""
        self._closed = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()                # wakes a blocked read with EOF before we take the lock
        with self._io_lock:
            self._stop_process()

    def _start(self) -> None:
        with self._io_lock:
            self._stop_process()
            if self._closed:
                return
            self.mode = self._modes.pop(0)
            cmd = _decode_cmd(_tools()[0], self._stream, self.mode, self.info.width, self.info.height)
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
            )
            self._stderr = _StderrTail(self._proc.stderr)

    def _stop_process(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        _stop(proc)
        _close_quietly(proc.stdout)
        if self._stderr is not None:
            self._stderr.join()
        _close_quietly(proc.stderr)

    def _read_frame(self) -> np.ndarray | None:
        buf = bytearray(self._frame_bytes)
        view = memoryview(buf)
        got = 0
        with self._io_lock:
            proc = self._proc
            if proc is None or proc.stdout is None:
                return None
            while got < self._frame_bytes:
                try:
                    n = proc.stdout.readinto(view[got:])
                except (OSError, ValueError):
                    n = 0
                if not n:
                    break
                got += n
        if got < self._frame_bytes:
            return None                # end of stream (a trailing partial frame is dropped)
        return np.frombuffer(buf, dtype=np.uint8).reshape(self._shape)

    def _stderr_text(self) -> str:
        return self._stderr.text() if self._stderr is not None else "no details from ffmpeg"


# ── encoding ─────────────────────────────────────────────────────────────

_VT_ENCODE_OK: set[tuple[int, int]] = set()


def _videotoolbox_works(ffmpeg: str, width: int, height: int) -> bool:
    """Can the hardware H.264 encoder open at this size right now? (~0.2 s, successes cached.)

    It only reports failure once the first frame arrives, too late to switch
    encoders cleanly in the real pipeline, so a tiny dry run decides.
    """
    if sys.platform != "darwin":
        return False
    key = (width, height)
    if key in _VT_ENCODE_OK:
        return True
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=gray:s={width}x{height}:r=30:d=0.1",
        "-c:v", "h264_videotoolbox", "-b:v", "4M", "-f", "null", "-",
    ]
    try:
        ok = subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if ok:
        _VT_ENCODE_OK.add(key)
    return ok


def _target_bitrate(stream: _Stream | None) -> int | None:
    if stream is None or not stream.bit_rate:
        return None
    factor = 1.1 * (1.5 if stream.info.codec in _EFFICIENT_CODECS else 1.0)
    return int(min(max(stream.bit_rate * factor, 2_000_000), 40_000_000))


def _rate_string(fps: float) -> str:
    rate = Fraction(fps if fps > 0 else 30).limit_denominator(1001)
    return f"{rate.numerator}/{rate.denominator}"


class FrameWriter:
    """Encodes BGR frames to an H.264 MP4 next to `dst`; close() adds the source's audio.

    Everything goes to hidden temp files in the destination folder; the result
    appears at `dst` only when complete. abort() removes all traces.
    """

    def __init__(self, dst: str | os.PathLike, info: VideoInfo, source_path: str | os.PathLike | None = None) -> None:
        self.dst = Path(dst)
        self.info = info
        self.frames_written = 0
        self.audio_kept = False
        self._stream = _inspect(source_path) if source_path is not None else None
        self._ffmpeg = _tools()[0]
        self._shape = (info.height, info.width, 3)
        tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._tmp_video = self.dst.with_name(f".{self.dst.stem}.{tag}.video.mp4")
        self._tmp_final = self.dst.with_name(f".{self.dst.stem}.{tag}.mp4")
        # with a source, a remux adds audio + metadata; otherwise encode straight to the final temp
        self._encode_to = self._tmp_video if self._stream is not None else self._tmp_final
        self._io_lock = threading.Lock()
        self._state = "open"           # open | closed | aborted
        even_w, even_h = info.width + info.width % 2, info.height + info.height % 2
        self.encoder = "h264_videotoolbox" if _videotoolbox_works(self._ffmpeg, even_w, even_h) else "libx264"
        self._proc = subprocess.Popen(
            self._encode_cmd(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0
        )
        self._stderr = _StderrTail(self._proc.stderr)

    def _encode_cmd(self) -> list[str]:
        info, stream = self.info, self._stream
        rate = stream.rate if stream is not None else _rate_string(info.fps)
        filters = []
        if info.width % 2 or info.height % 2:
            filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")   # 4:2:0 needs even sizes
        filters.append("scale=out_color_matrix=bt709:out_range=tv")
        if stream is not None and stream.sar:
            filters.append(f"setsar={stream.sar}")
        filters.append("format=yuv420p")
        if self.encoder == "h264_videotoolbox":
            bitrate = _target_bitrate(stream)
            gop = max(1, round(float(Fraction(rate)) * 2))
            quality = ["-b:v", str(bitrate)] if bitrate else ["-q:v", "65"]
            codec = ["-c:v", "h264_videotoolbox", "-profile:v", "high", *quality, "-g", str(gop)]
        else:
            codec = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high"]
        cmd = [
            self._ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{info.width}x{info.height}", "-r", rate, "-i", "pipe:0",
            "-an", "-vf", ",".join(filters), *codec, "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        ]
        if self._encode_to == self._tmp_final:
            cmd += ["-movflags", "+faststart"]
        return cmd + ["-f", "mp4", str(self._encode_to)]

    def __enter__(self) -> FrameWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()

    def write(self, frame: np.ndarray) -> None:
        if self._state != "open":
            raise RuntimeError("the video writer is already finished")
        if frame.shape != self._shape or frame.dtype != np.uint8:
            raise ValueError(f"expected a {self.info.width}x{self.info.height} BGR uint8 frame, got {frame.shape} {frame.dtype}")
        view = memoryview(np.ascontiguousarray(frame)).cast("B")
        with self._io_lock:
            stdin = self._proc.stdin
            try:
                if stdin is None:
                    raise ValueError("encoder input is closed")
                while view:
                    view = view[stdin.write(view):]
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"the video encoder stopped: {self._stderr.text()}") from exc
        self.frames_written += 1

    def close(self) -> Path:
        """Finish encoding, add the source's audio, move the result to `dst`."""
        if self._state == "closed":
            return self.dst
        if self._state == "aborted":
            raise RuntimeError("the video writer was aborted")
        try:
            with self._io_lock:
                _close_quietly(self._proc.stdin)
            try:
                code = self._proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                raise RuntimeError("the video encoder did not finish") from None
            self._stderr.join()
            if code != 0 or self.frames_written == 0:
                raise RuntimeError(f"the video encoder failed: {self._stderr.text()}")
            if self._stream is not None:
                self._remux()
            os.replace(self._tmp_final, self.dst)
            self._state = "closed"
        except BaseException:
            self.abort()
            raise
        finally:
            self._tmp_video.unlink(missing_ok=True)
        return self.dst

    def abort(self) -> None:
        """Stop encoding and delete everything written so far. Safe from another thread."""
        if self._state == "closed":
            return
        self._state = "aborted"
        _stop(self._proc)              # a write() blocked on the pipe fails fast now
        with self._io_lock:
            _close_quietly(self._proc.stdin)
        self._stderr.join()
        _close_quietly(self._proc.stderr)
        for path in (self._tmp_video, self._tmp_final):
            path.unlink(missing_ok=True)

    def _remux(self) -> None:
        stream = self._stream
        assert stream is not None
        base = [
            self._ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(self._tmp_video), "-i", stream.info.path, "-map", "0:v:0",
        ]
        tail = ["-c:v", "copy", "-map_metadata", "1", "-movflags", "+faststart", "-f", "mp4", str(self._tmp_final)]
        attempts: list[list[str]] = []
        if stream.audio_index is not None:
            audio = ["-map", f"1:{stream.audio_index}"]
            if stream.audio_codec in _MP4_AUDIO:
                attempts.append(audio + ["-c:a", "copy"])
            attempts.append(audio + ["-c:a", "aac", "-b:a", "192k"])
        attempts.append([])            # last resort: keep the rendered video even without its audio
        error = ""
        for extra in attempts:
            result = subprocess.run(base + extra + tail, capture_output=True, timeout=3600)
            if result.returncode == 0:
                self.audio_kept = bool(extra)
                if stream.audio_index is not None and not extra:
                    log.warning("saved without audio, it could not be carried over: %s", error)
                return
            error = result.stderr.decode("utf-8", "replace").strip()[-300:]
            log.info("remux attempt failed: %s", error)
        raise RuntimeError(f"could not finish the video file: {error}")


def output_path(src: str | os.PathLike) -> Path:
    """`<stem>-mirage.mp4` next to src, or -2, -3, … if taken."""
    src = Path(src)
    candidate = src.with_name(f"{src.stem}-mirage.mp4")
    n = 2
    while candidate.exists():
        candidate = src.with_name(f"{src.stem}-mirage-{n}.mp4")
        n += 1
    return candidate


# ── identity tracking ────────────────────────────────────────────────────


class TrackedFace(NamedTuple):
    identity: int | None       # index into the tracker's identities, or None: leave this face alone
    bbox: np.ndarray           # (4,) smoothed x1, y1, x2, y2
    kps: np.ndarray            # (5, 2) smoothed landmarks


@dataclass
class _Track:
    bbox: np.ndarray           # last raw detection, for overlap matching
    smoother: FaceSmoother
    seen_at: int
    embedded_at: int = -(1 << 30)
    sims: np.ndarray | None = None       # cosine similarity to each identity, from the last embedding
    identity: int | None = None


def _unit(vector: np.ndarray) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float32).reshape(-1)
    return v / max(float(np.linalg.norm(v)), 1e-6)


def _iou_matrix(a: Sequence[np.ndarray], b: Sequence[np.ndarray]) -> np.ndarray:
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)), dtype=np.float32)
    A, B = np.stack(a)[:, None, :], np.stack(b)[None, :, :]
    w = np.clip(np.minimum(A[..., 2], B[..., 2]) - np.maximum(A[..., 0], B[..., 0]), 0, None)
    h = np.clip(np.minimum(A[..., 3], B[..., 3]) - np.maximum(A[..., 1], B[..., 1]), 0, None)
    inter = w * h
    area_a = (A[..., 2] - A[..., 0]) * (A[..., 3] - A[..., 1])
    area_b = (B[..., 2] - B[..., 0]) * (B[..., 3] - B[..., 1])
    return inter / np.maximum(area_a + area_b - inter, 1e-6)


class IdentityTracker:
    """Follows faces from frame to frame and says which chosen person each one is.

    Faces are matched to the previous frame by box overlap (IoU); recognition
    (``embed_fn``) runs only for a new face, every ``reid_every`` frames per
    face, and whenever faces overlap (two people crossing could swap tracks).
    A face is identity k if its cosine similarity to k is the best and at least
    ``threshold`` (a face already known as k keeps it down to 75 % of that, so a
    turned head doesn't flicker). Each person is given to at most one face per frame.
    """

    KEEP_RATIO = 0.75

    def __init__(
        self,
        identities: Sequence[np.ndarray],
        threshold: float = 0.40,
        reid_every: int = 12,
        iou_match: float = 0.3,
        keep_missing: int = 5,
    ) -> None:
        self.threshold = threshold
        self.reid_every = max(1, reid_every)
        self.iou_match = iou_match
        self.keep_missing = keep_missing      # frames a face may go undetected and keep its track
        self._identities = np.stack([_unit(e) for e in identities]) if len(identities) else None
        self._tracks: list[_Track] = []
        self.embed_calls = 0

    def update(
        self,
        frame_index: int,
        detections: Sequence[Detection],
        embed_fn: Callable[[int], np.ndarray | None],
    ) -> list[TrackedFace]:
        """One TrackedFace per detection, in the same order."""
        self._tracks = [t for t in self._tracks if frame_index - t.seen_at <= self.keep_missing]
        boxes = [np.asarray(b, dtype=np.float32).reshape(-1)[:4] for b, _ in detections]
        kpss = [np.asarray(k, dtype=np.float32).reshape(-1, 2) for _, k in detections]
        iou = _iou_matrix(boxes, [t.bbox for t in self._tracks])
        overlaps = iou >= self.iou_match

        # greedy: the best-overlapping pairs first
        matched: dict[int, int] = {}
        taken: set[int] = set()
        for d, t in sorted(zip(*np.nonzero(overlaps), strict=True), key=lambda p: -iou[p[0], p[1]]):
            if d not in matched and t not in taken:
                matched[int(d)] = int(t)
                taken.add(int(t))
        crowded_dets = overlaps.sum(axis=1) > 1
        crowded_tracks = overlaps.sum(axis=0) > 1

        tracks: list[_Track] = []
        for d, bbox in enumerate(boxes):
            t = matched.get(d)
            if t is None:
                track = _Track(bbox=bbox, smoother=FaceSmoother(), seen_at=frame_index)
                self._tracks.append(track)
                crowded = False
            else:
                track = self._tracks[t]
                crowded = bool(crowded_dets[d] or crowded_tracks[t])
            track.bbox, track.seen_at = bbox, frame_index
            due = track.sims is None or crowded or frame_index - track.embedded_at >= self.reid_every
            if due and self._identities is not None:
                self.embed_calls += 1
                embedding = embed_fn(d)
                if embedding is not None:
                    track.sims = self._identities @ _unit(embedding)
                    track.embedded_at = frame_index
            tracks.append(track)

        identities = self._assign(tracks)
        out = []
        for d, track in enumerate(tracks):
            bbox, kps = track.smoother.update(boxes[d], kpss[d])
            out.append(TrackedFace(identities[d], bbox, kps))
        return out

    def _assign(self, tracks: list[_Track]) -> list[int | None]:
        candidates = []
        for i, track in enumerate(tracks):
            if track.sims is None:
                continue
            for k, sim in enumerate(track.sims):
                limit = self.threshold * (self.KEEP_RATIO if track.identity == k else 1.0)
                if sim >= limit:
                    candidates.append((float(sim), i, k))
        result: list[int | None] = [None] * len(tracks)
        given: set[int] = set()
        for _, i, k in sorted(candidates, reverse=True):
            if result[i] is None and k not in given:
                result[i] = k
                given.add(k)
        for track, identity in zip(tracks, result, strict=True):
            track.identity = identity
        return result


# ── rendering ────────────────────────────────────────────────────────────


@dataclass
class VideoHooks:
    """The models a render uses. default_hooks() builds the real ones; tests pass fakes."""

    detect: Callable[[np.ndarray], list[Detection]]                                  # frame → faces
    embed: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray | None]         # frame, bbox, kps → (512,)
    swap: Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray]     # frame, bbox, kps, source → frame
    enhance: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray] | None = None


class _Source:
    """What the swapper needs from a source face (an L2-normalised identity)."""

    __slots__ = ("normed_embedding",)

    def __init__(self, embedding: np.ndarray) -> None:
        self.normed_embedding = _unit(embedding)


VIDEO_DET_SIZE = 640
_DETECTOR = None
_DETECTOR_LOCK = threading.Lock()


def _video_detector():
    """A 640 px face detector of our own on the GPU (CoreML CPUAndGPU), CPU as fallback.

    Separate from the live analyser (320 px) so a render and Live can run at once.
    """
    global _DETECTOR
    with _DETECTOR_LOCK:
        if _DETECTOR is None:
            from insightface.model_zoo import model_zoo

            from modules.model_downloader import ensure_insightface_pack

            ensure_insightface_pack("buffalo_l")
            path = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_l", "det_10g.onnx")
            detector = model_zoo.get_model(path, providers=["CPUExecutionProvider"])
            detector.prepare(ctx_id=0, input_size=(VIDEO_DET_SIZE, VIDEO_DET_SIZE), det_thresh=0.5)
            _move_detector_to_gpu(detector, path)
            _DETECTOR = detector
    return _DETECTOR


def _move_detector_to_gpu(detector, path: str) -> None:
    cpu_session = detector.session
    try:
        import onnxruntime

        from modules.onnx_optimize import IS_APPLE_SILICON, optimize_for_coreml

        if not IS_APPLE_SILICON or "CoreMLExecutionProvider" not in onnxruntime.get_available_providers():
            return
        # constant-folded for the fixed input size: one CoreML partition instead of many
        optimized = optimize_for_coreml(path, input_shape=(1, 3, VIDEO_DET_SIZE, VIDEO_DET_SIZE))
        options = onnxruntime.SessionOptions()
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = [
            ("CoreMLExecutionProvider", {"ModelFormat": "MLProgram", "MLComputeUnits": "CPUAndGPU"}),
            "CPUExecutionProvider",
        ]
        detector.session = onnxruntime.InferenceSession(optimized, sess_options=options, providers=providers)
        detector.detect(np.zeros((VIDEO_DET_SIZE, VIDEO_DET_SIZE, 3), np.uint8), max_num=0, metric="default")
    except Exception as exc:
        log.warning("video face detector stays on the CPU: %s", exc)
        detector.session = cpu_session


def default_hooks(options: RenderOptions | None = None) -> VideoHooks:
    """The real models (loaded now, so a missing model fails before the render starts)."""
    import importlib

    from insightface.app.common import Face

    from mirage.upstream import configure_upstream

    configure_upstream()  # before the analyser is first created (it caches its config)
    import modules.globals as G
    from modules.face_analyser import ensure_landmarks, get_face_analyser
    from modules.gpu_processing import gpu_sharpen
    from modules.processors.frame import face_swapper

    detector = _video_detector()
    recognizer = get_face_analyser().models["recognition"]
    if face_swapper.get_face_swapper() is None:
        raise RuntimeError("the face swap model could not be loaded")

    def detect(frame: np.ndarray) -> list[Detection]:
        bboxes, kpss = detector.detect(frame, max_num=0, metric="default")
        if kpss is None:
            return []
        return [(bboxes[i, :4], kpss[i]) for i in range(bboxes.shape[0])]

    def embed(frame: np.ndarray, bbox: np.ndarray, kps: np.ndarray) -> np.ndarray:
        return np.asarray(recognizer.get(frame, Face(bbox=bbox, kps=kps)), dtype=np.float32)

    def swap(frame: np.ndarray, bbox: np.ndarray, kps: np.ndarray, source: np.ndarray) -> np.ndarray:
        # the Look settings (blend, keep my mouth, smooth edges) come from modules.globals as in Live
        face = Face(bbox=np.asarray(bbox, np.float32), kps=np.asarray(kps, np.float32), det_score=1.0)
        if G.mouth_mask:
            ensure_landmarks(frame, [face])
        out = face_swapper.swap_face(_Source(source), face, frame)
        sharpness = float(getattr(G, "sharpness", 0.0))
        if sharpness > 0:
            # like face_swapper.apply_post_processing, minus its cross-frame blending state
            h, w = out.shape[:2]
            x1, y1 = max(0, int(bbox[0])), max(0, int(bbox[1]))
            x2, y2 = min(w, int(bbox[2])), min(h, int(bbox[3]))
            if x2 > x1 and y2 > y1:
                out[y1:y2, x1:x2] = gpu_sharpen(out[y1:y2, x1:x2], strength=sharpness, sigma=2)
        return out

    enhance = None
    if options is not None and options.video_enhance:
        enhancer = importlib.import_module("modules.processors.frame.face_enhancer_gpen256")
        enhancer.get_enhancer()

        def enhance(frame: np.ndarray, bbox: np.ndarray, kps: np.ndarray) -> np.ndarray:
            return enhancer.enhance_face(frame, Face(bbox=bbox, kps=np.asarray(kps, np.float32)))

    return VideoHooks(detect=detect, embed=embed, swap=swap, enhance=enhance)


_END = object()


class _Pipeline:
    """Shared stop/error state for the render threads; blocking queue calls that give up on stop."""

    def __init__(self, cancel: threading.Event) -> None:
        self.cancel = cancel
        self.stop = threading.Event()
        self.error: BaseException | None = None

    def fail(self, exc: BaseException) -> None:
        if self.error is None:
            self.error = exc
        self.stop.set()

    def stopped(self) -> bool:
        return self.stop.is_set() or self.cancel.is_set()

    def put(self, q: queue.Queue, item) -> bool:
        while not self.stopped():
            try:
                q.put(item, timeout=0.1)
                return True
            except queue.Full:
                pass
        return False

    def get(self, q: queue.Queue):
        while not self.stopped():
            try:
                return q.get(timeout=0.1)
            except queue.Empty:
                pass
        return _END

    def check(self) -> None:
        if self.error is not None:
            raise self.error
        if self.cancel.is_set():
            raise VideoCancelled()


def _read_stage(reader: FrameReader, out: queue.Queue, pipe: _Pipeline) -> None:
    try:
        for frame in reader:
            if not pipe.put(out, frame):
                return
        pipe.put(out, _END)
    except BaseException as exc:
        pipe.fail(exc)


def _analyse_stage(
    hooks: VideoHooks | None,
    tracker: IdentityTracker,
    sources: Sequence[np.ndarray | None],
    src: queue.Queue,
    out: queue.Queue,
    pipe: _Pipeline,
) -> None:
    """Detection (GPU), tracking and the occasional recognition, a few frames ahead of the swaps.

    Keeping recognition here leaves the calling thread nothing but swaps, the
    Neural Engine work that sets the pace.
    """
    try:
        index = 0
        while (frame := pipe.get(src)) is not _END:
            targets: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
            if hooks is not None:
                faces = hooks.detect(frame)
                tracked = tracker.update(index, faces, lambda d, f=frame, fs=faces: hooks.embed(f, fs[d][0], fs[d][1]))
                for identity, bbox, kps in tracked:
                    source = sources[identity] if identity is not None else None
                    if source is not None:
                        targets.append((bbox, kps, source))
            if not pipe.put(out, (frame, targets)):
                return
            index += 1
        pipe.put(out, _END)
    except BaseException as exc:
        pipe.fail(exc)


def _write_stage(writer: FrameWriter, src: queue.Queue, pipe: _Pipeline) -> None:
    try:
        while (frame := pipe.get(src)) is not _END:
            writer.write(frame)
    except BaseException as exc:
        pipe.fail(exc)


class _Reporter:
    """Progress about four times a second, speed measured over the last few seconds."""

    def __init__(self, callback: Callable[[VideoProgress], None] | None, total: int, extra: dict) -> None:
        self._callback = callback
        self.total = total
        self.extra = extra
        self._marks: deque[tuple[float, int]] = deque()
        self._last = 0.0
        self._started = time.monotonic()

    def send(self, stage: str, done: int, fps: float = 0.0, eta: float | None = None) -> None:
        if self._callback is not None:
            self._callback(VideoProgress(done, max(self.total, done), fps, eta, stage, dict(self.extra)))

    def frame(self, done: int) -> None:
        now = time.monotonic()
        self._marks.append((now, done))
        while len(self._marks) > 2 and now - self._marks[0][0] > 3.0:
            self._marks.popleft()
        if now - self._last < 0.25:
            return
        self._last = now
        (t0, d0), (t1, d1) = self._marks[0], self._marks[-1]
        fps = (d1 - d0) / (t1 - t0) if t1 > t0 else 0.0
        total = max(self.total, done)
        eta = (total - done) / fps if fps > 0 and self.total > 0 else None
        self.send("render", done, fps, eta)

    def average_fps(self, done: int) -> float:
        elapsed = time.monotonic() - self._started
        return done / elapsed if elapsed > 0 else 0.0


def render_video(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    identities: list[VideoIdentity],
    options: RenderOptions,
    progress: Callable[[VideoProgress], None] | None = None,
    cancel: threading.Event | None = None,
    hooks: VideoHooks | None = None,
) -> Path:
    """Swap the chosen people in a video and save it to `dst` (H.264 MP4, original audio).

    Faces are matched to `identities` by who they are, not where they are.
    Raises VideoCancelled when `cancel` is set; on any failure the partial
    output is removed and the error re-raised.
    """
    src, dst = Path(src), Path(dst)
    if dst.resolve() == src.resolve():
        raise ValueError("the output would overwrite the original video")
    cancel = cancel or threading.Event()
    info = probe(src)
    reporter = _Reporter(progress, info.frames, {})
    reporter.send("probe", 0)
    sources = [ident.source_embedding for ident in identities]
    swapping = any(s is not None for s in sources)
    if hooks is None and swapping:
        hooks = default_hooks(options)
    if cancel.is_set():
        raise VideoCancelled()
    tracker = IdentityTracker([ident.embedding for ident in identities])
    enhance = hooks.enhance if hooks is not None and options.video_enhance else None

    guard = AwakeGuard()
    guard.hold("Mirage is rendering a video")
    reader = FrameReader(src, info)
    writer: FrameWriter | None = None
    threads: list[threading.Thread] = []
    pipe = _Pipeline(cancel)
    try:
        writer = FrameWriter(dst, info, src)
        depth = max(2, min(4, _QUEUE_BYTES // max(1, info.width * info.height * 3)))
        decoded: queue.Queue = queue.Queue(maxsize=depth)
        analysed: queue.Queue = queue.Queue(maxsize=depth)
        finished: queue.Queue = queue.Queue(maxsize=depth)
        stages = {
            "read": (_read_stage, (reader, decoded, pipe)),
            "detect": (_analyse_stage, (hooks if swapping else None, tracker, sources, decoded, analysed, pipe)),
            "write": (_write_stage, (writer, finished, pipe)),
        }
        threads = [
            threading.Thread(target=target, args=args, name=f"mirage-video-{name}", daemon=True)
            for name, (target, args) in stages.items()
        ]
        for thread in threads:
            thread.start()
        reporter.extra.update(encoder=writer.encoder)
        reporter.send("render", 0)

        done = swapped_frames = 0
        while (item := pipe.get(analysed)) is not _END:
            frame, targets = item
            for bbox, kps, source in targets:
                frame = hooks.swap(frame, bbox, kps, source)
            if enhance is not None:
                for bbox, kps, _ in targets:
                    frame = enhance(frame, bbox, kps)
            swapped_frames += bool(targets)
            if not pipe.put(finished, frame):
                break
            done += 1
            reporter.extra.update(decoder=reader.mode, swapped_frames=swapped_frames)
            reporter.frame(done)
        pipe.check()
        pipe.put(finished, _END)
        while threads[2].is_alive():          # the writer drains the last frames
            threads[2].join(0.1)
            pipe.check()
        pipe.check()
        if done == 0:
            raise RuntimeError(f"no frames could be decoded from {src.name}")
        reporter.total = done
        reporter.send("encode", done)
        result = writer.close()
        reporter.send("done", done, reporter.average_fps(done), 0.0)
        return result
    except BaseException:
        pipe.stop.set()
        reader.close()                         # unblocks the reader thread
        if writer is not None:
            writer.abort()                     # unblocks the writer thread, deletes the partial file
        for thread in threads:
            thread.join(5.0)
        raise
    finally:
        reader.close()
        guard.release()
