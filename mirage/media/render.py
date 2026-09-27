"""Full-resolution photo render: swap the planned faces, then restore detail.

inswapper works on a 128 px face, which looks soft on a large photo, so each
swapped face is restored with GFPGAN (512 → 1024 px, ~0.4 s per face on an M1
via CoreML). Only swapped faces are enhanced; everyone else is left exactly as
in the original.
"""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

from mirage.media.types import Plan, RenderOptions, TargetFace

log = logging.getLogger(__name__)


class _Source:
    __slots__ = ("normed_embedding",)

    def __init__(self, embedding: np.ndarray):
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)
        self.normed_embedding = emb / max(float(np.linalg.norm(emb)), 1e-6)


def _face_alpha(size: int) -> np.ndarray:
    """Feathered ellipse around the face in FFHQ-aligned space (0..1, float32)."""
    alpha = np.zeros((size, size), np.float32)
    center = (int(size * 0.5), int(size * 0.54))
    axes = (int(size * 0.36), int(size * 0.44))
    cv2.ellipse(alpha, center, axes, 0, 0, 360, 1.0, -1)
    k = max(3, int(size * 0.06) | 1)
    return cv2.GaussianBlur(alpha, (k, k), 0)


def _blend_face(frame: np.ndarray, face: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Warp an aligned face back into ``frame`` inside its ellipse, touching only that region."""
    size = face.shape[0]
    inverse = cv2.invertAffineTransform(matrix)
    corners = np.array([[0, 0, 1], [size, 0, 1], [0, size, 1], [size, size, 1]], np.float64)
    pts = corners @ inverse.T
    h, w = frame.shape[:2]
    x0, y0 = max(0, int(np.floor(pts[:, 0].min()))), max(0, int(np.floor(pts[:, 1].min())))
    x1, y1 = min(w, int(np.ceil(pts[:, 0].max()))), min(h, int(np.ceil(pts[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        return frame
    local = inverse.copy()
    local[:, 2] -= (x0, y0)
    roi = (x1 - x0, y1 - y0)
    warped = cv2.warpAffine(face, local, roi, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
    alpha = cv2.warpAffine(_face_alpha(size), local, roi, flags=cv2.INTER_LINEAR)[..., None]
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(warped * alpha + region * (1 - alpha), 0, 255).astype(np.uint8)
    return frame


class PhotoRenderer:
    """Holds the heavy models between renders; call release() to free memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enhance_failed = False

    def render(self, image: np.ndarray, targets: list[TargetFace], plan: Plan,
               embeddings: dict[str, np.ndarray], options: RenderOptions) -> np.ndarray:
        from insightface.app.common import Face

        from modules.face_analyser import ensure_landmarks
        from modules.processors.frame import face_swapper

        import modules.globals as G
        from mirage.upstream import configure_upstream

        configure_upstream()
        if face_swapper.get_face_swapper() is None:
            raise RuntimeError("the face swap model could not be loaded")
        with self._lock:
            out = image.copy()
            swapped = []
            for target in targets:
                source_id = plan.get(target.index)
                if not source_id or source_id not in embeddings:
                    continue
                face = Face(bbox=np.asarray(target.bbox, dtype=np.float32), kps=target.kps.astype(np.float32),
                            det_score=target.score)
                if G.mouth_mask:
                    ensure_landmarks(image, [face])  # the real mouth comes from the original
                out = face_swapper.swap_face(_Source(embeddings[source_id]), face, out)
                swapped.append(face)
            if not swapped:
                return out
            self.enhance_failed = False
            if options.enhance:
                for face in swapped:
                    try:
                        out = self._enhance(out, face)
                    except Exception:
                        log.exception("face enhancement failed; keeping the plain swap")
                        self.enhance_failed = True
                        break
            # Sharpness last, so GFPGAN doesn't regenerate the pixels it touched.
            return face_swapper.apply_post_processing(out, [np.asarray(f.bbox).astype(int) for f in swapped])

    def _enhance(self, frame: np.ndarray, face) -> np.ndarray:
        """GFPGAN on one face, blended back through a soft face-shaped mask.

        The upstream paste-back uses the whole aligned square (about twice the
        face's width), which re-synthesises hair, background and neighbouring
        faces at 512 px. Here only an ellipse around the face is replaced, at
        the model's native 1024 px output.
        """
        from modules.processors.frame import face_enhancer as fe
        from modules.processors.frame._onnx_enhancer import run_inference

        session = fe.get_face_enhancer()
        inp = session.get_inputs()[0]
        try:
            size = int(inp.shape[2]) if int(inp.shape[2]) > 0 else 512
        except (TypeError, ValueError, IndexError):
            size = 512
        aligned, matrix = fe._align_face(frame, face.kps.astype(np.float32), output_size=size)
        if aligned is None or matrix is None:
            return frame
        restored = fe._postprocess_face(run_inference(session, inp.name, fe._preprocess_face(aligned)))
        out_size = restored.shape[0]
        scaled = matrix.astype(np.float64) * (out_size / size)   # aligned(1024) ← frame
        return _blend_face(frame, restored, scaled)

    def release(self) -> None:
        """Drop GFPGAN (~1.5 GB with CoreML on an 8 GB Mac) when leaving the mode."""
        try:
            from modules.processors.frame import face_enhancer as fe

            with fe.THREAD_LOCK:
                fe.FACE_ENHANCER = None
        except Exception:
            pass
