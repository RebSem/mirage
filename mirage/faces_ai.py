"""Glue between Mirage and the upstream face detector.

Heavy imports (insightface, onnxruntime) happen lazily on first use so the
window can appear before the models load.
"""

from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

from mirage.library import DetectedFace

RANDOM_FACE_URL = "https://thispersondoesnotexist.com/random-person.jpeg"

# Close-up portraits fill the frame and defeat the 640x640 detector; a dark
# border makes the face smaller relative to the image.
_PAD_RATIOS = (0.0, 0.3, 0.6)


_PHOTO_DETECTOR = None
_PHOTO_DETECTOR_LOCK = threading.Lock()


def _photo_detector():
    """A 640x640 detector on the CPU just for imported photos.

    Live detection runs at 320 (fast, faces are big); photos can have small
    faces, and an import can afford ~100 ms.
    """
    global _PHOTO_DETECTOR
    with _PHOTO_DETECTOR_LOCK:
        if _PHOTO_DETECTOR is None:
            from insightface.model_zoo import model_zoo

            from modules.model_downloader import ensure_insightface_pack

            ensure_insightface_pack("buffalo_l")
            path = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_l", "det_10g.onnx")
            detector = model_zoo.get_model(path, providers=["CPUExecutionProvider"])
            detector.prepare(ctx_id=0, input_size=(640, 640), det_thresh=0.5)
            _PHOTO_DETECTOR = detector
    return _PHOTO_DETECTOR


def embed(image: np.ndarray) -> DetectedFace | None:
    """Main (largest) face of a BGR photo: its identity embedding and box, or None."""
    from insightface.app.common import Face

    from modules.face_analyser import get_face_analyser

    from mirage.upstream import configure_upstream

    if image is None or image.ndim != 3:
        return None
    configure_upstream()  # before the analyser is first created (it caches its config)
    recognizer = get_face_analyser().models["recognition"]
    detector = _photo_detector()
    for ratio in _PAD_RATIOS:
        pad = int(max(image.shape[:2]) * ratio)
        probe = image if pad == 0 else cv2.copyMakeBorder(
            image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        bboxes, kpss = detector.detect(probe, max_num=0, metric="default")
        if bboxes.shape[0] == 0:
            continue
        areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
        i = int(areas.argmax())
        face = Face(bbox=bboxes[i, :4], kps=kpss[i], det_score=bboxes[i, 4])
        recognizer.get(probe, face)
        gender = age = None
        try:  # for "natural-looking" suggestions in Photos & videos
            from mirage.media.analyze import _genderage

            _genderage().get(probe, face)
            gender, age = int(face.gender), float(face.age)
        except Exception:
            pass
        x1, y1, x2, y2 = (float(v) - pad for v in face.bbox[:4])
        return DetectedFace(np.asarray(face.embedding, dtype=np.float32), (x1, y1, x2, y2), gender, age)
    return None


def fetch_random_face(timeout: float = 15.0) -> np.ndarray:
    """Download a generated face (thispersondoesnotexist.com) as a BGR image."""
    import requests

    response = requests.get(
        f"{RANDOM_FACE_URL}?{time.time_ns()}",
        headers={"User-Agent": "Mozilla/5.0 (Mirage)"},
        timeout=timeout,
    )
    response.raise_for_status()
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("response is not an image")
    return image
