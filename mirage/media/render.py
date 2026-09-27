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


class PhotoRenderer:
    """Holds the heavy models between renders; call release() to free memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

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
            out = face_swapper.apply_post_processing(out, [np.asarray(f.bbox).astype(int) for f in swapped])
            if options.enhance:
                for face in swapped:
                    try:
                        out = self._enhance(out, face)
                    except Exception:
                        log.exception("face enhancement failed; keeping the plain swap")
                        break
            return out

    def _enhance(self, frame: np.ndarray, face) -> np.ndarray:
        """GFPGAN on one face, using the upstream helpers but without the live cache."""
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
        if restored.shape[:2] != (size, size):
            restored = cv2.resize(restored, (size, size), interpolation=cv2.INTER_LANCZOS4)
        fe._paste_back(frame, restored, matrix, output_size=size)
        return frame

    def release(self) -> None:
        """Drop GFPGAN (~1.5 GB with CoreML on an 8 GB Mac) when leaving the mode."""
        try:
            from modules.processors.frame import face_enhancer as fe

            with fe.THREAD_LOCK:
                fe.FACE_ENHANCER = None
        except Exception:
            pass
