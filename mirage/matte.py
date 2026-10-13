"""Person segmentation with Apple's Vision framework (``VNGeneratePersonSegmentationRequest``).

It ships with macOS, needs no download and runs on the Neural Engine: about
4 ms (fast), 20 ms (balanced) per 640×480 frame on an M1. The mask it returns
is soft but low-resolution; ``compose.refine_matte`` snaps it to the picture.

A ``PersonSegmenter`` is not thread-safe: create and use it on one thread
(the engine's ``mirage-matte`` thread).
"""

from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

QUALITIES = ("fast", "balanced", "accurate")
# PyObjC loads framework symbols lazily, and two threads doing that at once can
# fail (KeyError on a symbol); everything below resolves them under this lock.
_LOAD_LOCK = threading.Lock()
# Vision sets itself up on the first request and crashes (in
# VNGenerateSemanticSegmentationCompoundRequest) if two threads make their
# first request at once, e.g. the warm-up and the first live frame. Requests
# take turns; live there is only one thread asking, so this costs nothing.
_PERFORM_LOCK = threading.Lock()


class _CoreVideo:
    """The few CoreVideo calls we use, looked up once."""

    def __init__(self) -> None:
        import Quartz as q

        self.create = q.CVPixelBufferCreate
        self.lock = q.CVPixelBufferLockBaseAddress
        self.unlock = q.CVPixelBufferUnlockBaseAddress
        self.base = q.CVPixelBufferGetBaseAddress
        self.row = q.CVPixelBufferGetBytesPerRow
        self.width = q.CVPixelBufferGetWidth
        self.height = q.CVPixelBufferGetHeight
        self.bgra = q.kCVPixelFormatType_32BGRA
        self.one8 = q.kCVPixelFormatType_OneComponent8
        self.iosurface = q.kCVPixelBufferIOSurfacePropertiesKey
        self.read_only = q.kCVPixelBufferLock_ReadOnly


def available() -> bool:
    try:
        import Vision

        return hasattr(Vision, "VNGeneratePersonSegmentationRequest")
    except Exception:
        return False


class PersonSegmenter:
    def __init__(self, quality: str = "balanced"):
        with _LOAD_LOCK:
            import Vision as v

            self._cv = _CoreVideo()
            self._levels = {
                "fast": v.VNGeneratePersonSegmentationRequestQualityLevelFast,
                "balanced": v.VNGeneratePersonSegmentationRequestQualityLevelBalanced,
                "accurate": v.VNGeneratePersonSegmentationRequestQualityLevelAccurate,
            }
            self._request = v.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
            self._request.setOutputPixelFormat_(self._cv.one8)
            # A sequence handler lets Vision use the previous frames, which keeps the mask steady.
            self._handler = v.VNSequenceRequestHandler.alloc().init()
        self._quality = ""
        self._buffer = None
        self._buffer_size: tuple[int, int] | None = None
        self.set_quality(quality)

    def set_quality(self, quality: str) -> None:
        if quality == self._quality:
            return
        self._request.setQualityLevel_(self._levels.get(quality, self._levels["balanced"]))
        self._quality = quality

    def _pixel_buffer(self, bgr: np.ndarray):
        cv = self._cv
        h, w = bgr.shape[:2]
        if self._buffer is None or self._buffer_size != (w, h):
            err, buf = cv.create(None, w, h, cv.bgra, {cv.iosurface: {}}, None)
            if err != 0 or buf is None:
                raise RuntimeError(f"CVPixelBufferCreate failed ({err})")
            self._buffer, self._buffer_size = buf, (w, h)
        buf = self._buffer
        cv.lock(buf, 0)
        try:
            row = cv.row(buf)
            raw = cv.base(buf).as_buffer(row * h)
            view = np.frombuffer(raw, np.uint8).reshape(h, row)[:, : w * 4].reshape(h, w, 4)
            view[..., :3] = bgr
            view[..., 3] = 255
        finally:
            cv.unlock(buf, 0)
        return buf

    def mask(self, bgr: np.ndarray) -> np.ndarray:
        """The person mask of a BGR frame: uint8, 0 = background, 255 = person, at
        Vision's own resolution (resize it to the frame)."""
        cv = self._cv
        with _PERFORM_LOCK:
            ok, error = self._handler.performRequests_onCVPixelBuffer_error_(
                [self._request], self._pixel_buffer(bgr), None)
        results = self._request.results()
        if not ok or not results:
            raise RuntimeError(f"person segmentation failed: {error}")
        buf = results[0].pixelBuffer()
        cv.lock(buf, cv.read_only)
        try:
            h, w = cv.height(buf), cv.width(buf)
            row = cv.row(buf)
            raw = cv.base(buf).as_buffer(row * h)
            return np.frombuffer(raw, np.uint8).reshape(h, row)[:, :w].copy()
        finally:
            cv.unlock(buf, cv.read_only)


def warm_up() -> None:
    """Load Vision's segmentation model once (1–2 s the first time) so turning a
    background on during a call doesn't stall the video."""
    import objc

    try:
        with objc.autorelease_pool():
            seg = PersonSegmenter("balanced")
            seg.mask(np.zeros((96, 128, 3), np.uint8))
    except Exception:
        log.warning("person segmentation warm-up failed", exc_info=True)
