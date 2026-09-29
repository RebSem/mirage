"""Send processed live frames straight to the OBS Virtual Camera.

Local addition: Zoom/Meet get the swapped video even when the Live Preview
window is covered or minimized (no OBS window capture needed). While
streaming, the process also opts out of macOS App Nap so processing isn't
throttled in the background.

Output is always OUT_WIDTH x OUT_HEIGHT: macOS cameras can switch between
4:3 and 16:9 mid-session (e.g. when another app touches the camera), and
reopening the virtual camera on every switch makes Zoom's video restart.
"""

import platform
import threading
import time

import cv2
import numpy as np

OUT_WIDTH, OUT_HEIGHT = 1280, 720
OUT_FPS = 30
RETRY_SECONDS = 3.0

_lock = threading.Lock()
_cam = None
_retry_at = 0.0
_activity = None


def _begin_activity() -> None:
    global _activity
    if platform.system() != "Darwin" or _activity is not None:
        return
    try:
        from Foundation import (
            NSActivityLatencyCritical,
            NSActivityUserInitiated,
            NSProcessInfo,
        )
        _activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiated | NSActivityLatencyCritical,
            "Deep-Live-Cam virtual camera",
        )
    except Exception as exc:
        print(f"[virtualcam] App Nap opt-out failed: {exc}")


def _end_activity() -> None:
    global _activity
    if _activity is None:
        return
    try:
        from Foundation import NSProcessInfo
        NSProcessInfo.processInfo().endActivity_(_activity)
    except Exception:
        pass
    _activity = None


def _close_locked() -> None:
    global _cam
    if _cam is not None:
        try:
            _cam.close()
        except Exception:
            pass
        _cam = None
    _end_activity()


def _fit(frame: np.ndarray) -> np.ndarray:
    """Center-crop to the output aspect ratio, then scale to the output size."""
    h, w = frame.shape[:2]
    if (w, h) == (OUT_WIDTH, OUT_HEIGHT):
        return frame
    target = OUT_WIDTH / OUT_HEIGHT
    if w / h > target:
        cw = int(round(h * target))
        x = (w - cw) // 2
        frame = frame[:, x:x + cw]
    elif w / h < target:
        ch = int(round(w / target))
        y = (h - ch) // 2
        frame = frame[y:y + ch]
    return cv2.resize(frame, (OUT_WIDTH, OUT_HEIGHT), interpolation=cv2.INTER_LINEAR)


def send(frame) -> None:
    """Push one BGR frame; opens the camera lazily, retries after failures."""
    global _cam, _retry_at
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return
    with _lock:
        if _cam is None:
            if time.monotonic() < _retry_at:
                return
            try:
                import pyvirtualcam
                _cam = pyvirtualcam.Camera(
                    OUT_WIDTH, OUT_HEIGHT, OUT_FPS,
                    fmt=pyvirtualcam.PixelFormat.BGR, backend="obs",
                )
            except Exception as exc:
                _retry_at = time.monotonic() + RETRY_SECONDS
                print(f"[virtualcam] not available ({exc}), retrying in {RETRY_SECONDS:.0f}s")
                return
            print(f"[virtualcam] streaming to {_cam.device} at {OUT_WIDTH}x{OUT_HEIGHT}")
            _begin_activity()
        try:
            out = _fit(frame)
            _cam.send(np.ascontiguousarray(out, dtype=np.uint8))
        except Exception as exc:
            print(f"[virtualcam] send failed: {exc}")
            _close_locked()
            _retry_at = time.monotonic() + RETRY_SECONDS


def is_streaming() -> bool:
    """True while frames are going out to the virtual camera."""
    return _cam is not None


def close() -> None:
    """Release the camera; the next live session opens it again."""
    global _retry_at
    with _lock:
        _close_locked()
        _retry_at = 0.0
