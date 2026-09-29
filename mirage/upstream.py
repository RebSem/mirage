"""One place that configures the upstream Deep-Live-Cam engine for Mirage.

Must run before the first face-analyser use: insightface fixes the detector
size and providers when the analyser is created, and it is then cached.
"""

from __future__ import annotations

import threading

# Live faces are big: a 320x320 detector finds them in ~9 ms on M1 vs ~26 ms
# at 640 (photo import keeps its own 640 detector, see faces_ai).
LIVE_DET_SIZE = 320

_done = False
_lock = threading.Lock()


def configure_upstream() -> None:
    """Point the upstream engine at CoreML and keep it quiet (no classic UI). Idempotent."""
    global _done
    with _lock:
        if _done:
            return
        import onnxruntime

        import modules.globals as G
        from mirage import paths

        # The engine finds its models through third_party/deep-live-cam/models,
        # a link to <repo>/models; make sure the folder it points at exists.
        paths.models_dir()

        G.headless = True
        G.det_size = LIVE_DET_SIZE
        available = onnxruntime.get_available_providers()
        G.execution_providers = [p for p in ("CoreMLExecutionProvider", "CPUExecutionProvider") if p in available]
        G.frame_processors = ["face_swapper"]
        G.live_mirror = False
        G.map_faces = False
        G.fp_ui = {"face_enhancer": False, "face_enhancer_gpen256": False, "face_enhancer_gpen512": False}
        _done = True
