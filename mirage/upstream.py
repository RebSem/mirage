"""One place that configures the upstream Deep-Live-Cam engine for Mirage.

Must run before the first face-analyser use: insightface fixes the detector
size and providers when the analyser is created, and it is then cached.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# Live faces are big: a 320x320 detector finds them in ~9 ms on M1 vs ~26 ms
# at 640 (photo import keeps its own 640 detector, see faces_ai).
LIVE_DET_SIZE = 320

_done = False
_lock = threading.Lock()


COREML = "CoreMLExecutionProvider"


def coreml_cache_for(model_path: str | os.PathLike, root: Path) -> Path:
    """The compiled-model folder for this exact model file.

    ONNX Runtime keys its CoreML cache by the model's path only, so a model
    replaced in place would be served stale. One folder per path, size and
    modification time avoids that; older folders of the same model are removed.
    """
    path = Path(model_path).resolve()
    st = path.stat()
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", path.name)
    folder = root / f"{stem}-{st.st_size}-{st.st_mtime_ns}"
    pattern = re.compile(re.escape(stem) + r"-\d+-\d+")
    if root.is_dir():
        for old in root.iterdir():
            if old != folder and old.is_dir() and pattern.fullmatch(old.name):
                shutil.rmtree(old, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def with_coreml_cache(model_path, providers, provider_options, root: Path):
    """providers/provider_options as InferenceSession takes them, with a cache folder
    added to the CoreML entry. Returns (providers, provider_options)."""
    if not providers:
        return providers, provider_options
    entries = []
    for i, entry in enumerate(providers):
        if isinstance(entry, (tuple, list)):
            name, opts = entry[0], dict(entry[1] or {})
        else:
            name = entry
            opts = dict(provider_options[i]) if provider_options and i < len(provider_options) else {}
        entries.append((name, opts))
    if not any(name == COREML and "ModelCacheDirectory" not in opts for name, opts in entries):
        return providers, provider_options
    cache = str(coreml_cache_for(model_path, root))
    entries = [(name, {**opts, "ModelCacheDirectory": cache} if name == COREML else opts) for name, opts in entries]
    return entries, None


def _cache_compiled_coreml_models() -> None:
    """Keep CoreML's compiled models on disk between launches.

    Without it every session start compiles its model for the Neural Engine or
    GPU again (about 5 s for the swap model, 15-20 s for everything at launch),
    and it does so holding Python's lock, so the window stalls meanwhile. With
    it the next start of the same model takes a fraction of a second.
    """
    import onnxruntime as ort

    original = ort.InferenceSession.__init__
    if getattr(original, "_mirage_coreml_cache", False):
        return
    from mirage.paths import cache_dir

    root = cache_dir() / "coreml"

    def init(self, path_or_bytes, sess_options=None, providers=None, provider_options=None, **kwargs):
        cached = None
        if isinstance(path_or_bytes, (str, os.PathLike)):
            try:
                cached = with_coreml_cache(path_or_bytes, providers, provider_options, root)
            except OSError:
                log.warning("no CoreML cache for %s", path_or_bytes, exc_info=True)
        if cached is None or cached == (providers, provider_options):
            original(self, path_or_bytes, sess_options, providers, provider_options, **kwargs)
            return
        try:
            original(self, path_or_bytes, sess_options, *cached, **kwargs)
        except Exception:
            # A damaged cache (a full disk, or macOS clearing part of Caches) must not
            # stop the model from loading: drop it and compile afresh, uncached.
            log.warning("CoreML cache for %s didn't load; compiling it again", path_or_bytes, exc_info=True)
            folder = next((opts.get("ModelCacheDirectory") for name, opts in cached[0] if name == COREML), None)
            if folder:
                shutil.rmtree(folder, ignore_errors=True)
            original(self, path_or_bytes, sess_options, providers, provider_options, **kwargs)

    init._mirage_coreml_cache = True
    ort.InferenceSession.__init__ = init


# Files FaceAnalysis would open only to throw away: the 143 MB 3D-landmark model (the
# engine asks for detection, recognition and 2D landmarks only), and the CoreML rewrites
# the engine saves next to the detector (it loads those itself).
UNUSED_FACE_MODELS = re.compile(r"1k3d68\.onnx|.+_coreml.*\.onnx")


def _skip_unused_face_models() -> None:
    """insightface's FaceAnalysis opens every .onnx in its folder, then drops the ones it
    wasn't asked for. That cost about 2 s on every launch (far more on the first, when
    each is compiled for CoreML). Give it nothing for the files it would drop."""
    from insightface.model_zoo import model_zoo

    original = model_zoo.get_model
    if getattr(original, "_mirage_skip", False):
        return

    def get_model(name, **kwargs):
        if UNUSED_FACE_MODELS.fullmatch(os.path.basename(str(name))):
            return None
        return original(name, **kwargs)

    get_model._mirage_skip = True
    model_zoo.get_model = get_model


def configure_upstream() -> None:
    """Point the upstream engine at CoreML and keep it quiet (no classic UI). Idempotent."""
    global _done
    with _lock:
        if _done:
            return
        import onnxruntime

        _cache_compiled_coreml_models()
        _skip_unused_face_models()
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
