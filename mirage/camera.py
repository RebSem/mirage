"""Camera discovery.

On macOS, OpenCV's AVFoundation backend opens ``cv2.VideoCapture(index)`` by
position in the list of video + muxed devices sorted by uniqueID. Indices
therefore shift when a device (e.g. an iPhone Continuity Camera) appears or
disappears, so Mirage remembers cameras by uid and resolves the index right
before opening.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Our own output; capturing from it would feed the stream back into itself.
VIRTUAL_CAMERA_NAMES = ("OBS Virtual Camera",)


@dataclass(frozen=True)
class CameraInfo:
    index: int
    name: str
    uid: str | None
    builtin: bool


def order_devices(devices: list[tuple[str, str, bool]]) -> list[CameraInfo]:
    """(name, uid, builtin) in any order → cameras with OpenCV indices.

    Indices follow OpenCV's uniqueID sort (virtual cameras included), then
    virtual cameras are dropped and the built-in camera is listed first.
    """
    by_uid = sorted(devices, key=lambda d: d[1])
    cams = [
        CameraInfo(index=i, name=name, uid=uid, builtin=builtin)
        for i, (name, uid, builtin) in enumerate(by_uid)
        if not any(v in name for v in VIRTUAL_CAMERA_NAMES)
    ]
    return sorted(cams, key=lambda c: (not c.builtin, c.index))


def _darwin_devices() -> list[tuple[str, str, bool]]:
    import AVFoundation as AVF

    found = list(AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo))
    found += list(AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeMuxed))
    builtin_type = str(AVF.AVCaptureDeviceTypeBuiltInWideAngleCamera)
    return [
        (str(d.localizedName()), str(d.uniqueID()), str(d.deviceType()) == builtin_type)
        for d in found
    ]


def _probe_devices(limit: int = 6) -> list[CameraInfo]:
    import cv2

    cams = []
    for i in range(limit):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append(CameraInfo(index=i, name=f"Camera {i}", uid=None, builtin=i == 0))
        cap.release()
    return cams


def list_cameras() -> list[CameraInfo]:
    if sys.platform == "darwin":
        try:
            return order_devices(_darwin_devices())
        except Exception as exc:  # pyobjc missing or AVFoundation hiccup
            log.warning("AVFoundation camera listing failed: %s", exc)
    return _probe_devices()


def virtual_camera_installed() -> bool:
    """True when OBS Virtual Camera shows up as a macOS camera device."""
    if sys.platform != "darwin":
        return False
    try:
        return any(any(v in name for v in VIRTUAL_CAMERA_NAMES) for name, _uid, _b in _darwin_devices())
    except Exception:
        return False


def resolve(uid: str | None, fallback: CameraInfo | None = None) -> CameraInfo | None:
    """Fresh CameraInfo for a remembered uid (None if it's gone)."""
    cams = list_cameras()
    if uid is not None:
        return next((c for c in cams if c.uid == uid), None)
    if fallback is not None:
        return next((c for c in cams if c.index == fallback.index), fallback)
    return cams[0] if cams else None
