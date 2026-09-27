"""Find every face in a photo: box, landmarks, identity, gender and age.

Runs on the CPU (it's a one-off per photo, ~0.1–0.4 s on an M1), so it never
competes with a live session for the Neural Engine.
"""

from __future__ import annotations

import os
import threading

import numpy as np

from mirage.media.plan import number_left_to_right
from mirage.media.types import TargetFace

SMALL_FACE = 0.06          # faces narrower than 6 % of the image → try a finer pass
NMS_IOU = 0.4

_GENDERAGE = None
_GENDERAGE_LOCK = threading.Lock()
_DETECT_LOCK = threading.Lock()   # the shared CPU detector isn't re-entrant


def _genderage():
    global _GENDERAGE
    with _GENDERAGE_LOCK:
        if _GENDERAGE is None:
            from insightface.model_zoo import model_zoo

            path = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_l", "genderage.onnx")
            model = model_zoo.get_model(path, providers=["CPUExecutionProvider"])
            model.prepare(ctx_id=0)
            _GENDERAGE = model
    return _GENDERAGE


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def _merge(dets: list[tuple[np.ndarray, np.ndarray]]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Non-maximum suppression across detection passes (rows are x1,y1,x2,y2,score)."""
    dets = sorted(dets, key=lambda d: -float(d[0][4]))
    kept: list[tuple[np.ndarray, np.ndarray]] = []
    for box, kps in dets:
        if all(_iou(box, k[0]) < NMS_IOU for k in kept):
            kept.append((box, kps))
    return kept


def detect_faces(image: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """(box with score, 5 landmarks) for every face; a finer pass when faces are small."""
    from mirage.faces_ai import _photo_detector

    detector = _photo_detector()
    h, w = image.shape[:2]
    with _DETECT_LOCK:
        bboxes, kpss = detector.detect(image, max_num=0, metric="default")
        dets = [(bboxes[i], kpss[i]) for i in range(bboxes.shape[0])]
        smallest = min(((b[2] - b[0]) / w for b, _k in dets), default=0.0)
        if max(h, w) > 1400 and (not dets or smallest < SMALL_FACE):
            b2, k2 = detector.detect(image, input_size=(1280, 1280), max_num=0, metric="default")
            dets += [(b2[i], k2[i]) for i in range(b2.shape[0])]
    return _merge(dets)


def analyze_image(image: np.ndarray) -> list[TargetFace]:
    """Every face in a BGR photo, numbered left to right."""
    from insightface.app.common import Face

    from modules.face_analyser import get_face_analyser

    from mirage.upstream import configure_upstream

    if image is None or image.ndim != 3:
        return []
    configure_upstream()
    recognizer = get_face_analyser().models["recognition"]
    attributes = _genderage()
    targets: list[TargetFace] = []
    for box, kps in detect_faces(image):
        face = Face(bbox=box[:4].astype(np.float32), kps=kps.astype(np.float32), det_score=float(box[4]))
        recognizer.get(image, face)
        gender = age = None
        try:
            attributes.get(image, face)
            gender, age = int(face.gender), float(face.age)
        except Exception:
            pass
        targets.append(TargetFace(
            index=0,
            bbox=tuple(float(v) for v in box[:4]),
            kps=face.kps.astype(np.float32),
            score=float(box[4]),
            embedding=np.asarray(face.embedding, dtype=np.float32),
            gender=gender,
            age=age,
        ))
    return number_left_to_right(targets)


def main_attributes(image: np.ndarray) -> tuple[int | None, float | None]:
    """Gender/age of the largest face (used to fill in older library entries)."""
    faces = analyze_image(image)
    if not faces:
        return None, None
    main = max(faces, key=lambda t: t.area)
    return main.gender, main.age
