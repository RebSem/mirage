"""Live pipeline: camera → face swap → OBS Virtual Camera + preview.

Three plain Python threads do the work (Python threads avoid Qt's
"QThread destroyed while running" abort on quit):

* capture: reads the camera, keeps only the newest frame, survives short gaps
* detect: finds and smooths the face on the GPU, paced by the quality preset
* process: swap (Neural Engine) → post-process → virtual camera, and hands
  the newest result to the UI

The UI talks to the engine only through methods and Qt signals, all of which
are safe to call from the UI thread.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from mirage.camera import CameraInfo
from mirage.power import AwakeGuard
from mirage.settings import Settings
from mirage.tracking import FaceSmoother
from mirage.upstream import configure_upstream

log = logging.getLogger(__name__)

IDLE, LOADING, STARTING, LIVE, STOPPING = "idle", "loading", "starting", "live", "stopping"

CAPTURE_GRACE_SECONDS = 5.0
PREVIEW_MAX_FPS = 30
MOUTH_MASK_SIZE = 40.0  # upstream slider scale 0..100

ENHANCER_MODULE = "modules.processors.frame.face_enhancer_gpen256"


@dataclass(frozen=True)
class Quality:
    detect_interval: float         # seconds between detections (the detector runs in its own thread)
    enhancer: bool


QUALITY = {
    "fast": Quality(detect_interval=0.10, enhancer=False),
    "balanced": Quality(detect_interval=0.04, enhancer=False),
    "best": Quality(detect_interval=0.0, enhancer=True),
}

def models_present() -> bool:
    from mirage.paths import models_dir

    return any(models_dir().glob("inswapper_128*.onnx"))


class _Source:
    """What the swapper needs from a source face: its identity embedding.

    Avoids importing insightface on the UI thread just to wrap an array.
    """

    __slots__ = ("normed_embedding",)

    def __init__(self, embedding: np.ndarray):
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)
        self.normed_embedding = emb / max(float(np.linalg.norm(emb)), 1e-6)


class LiveEngine(QObject):
    stateChanged = Signal(str)
    modelsState = Signal(str)            # loading | ready | failed
    qualityFallback = Signal(str)        # the engine had to drop to this quality preset
    previewReady = Signal()              # pull the frame with take_preview()
    statsChanged = Signal(dict)          # {"fps": float, "face_found": bool, "vcam": bool}
    notice = Signal(str, str, dict)      # level, i18n key, format args

    def __init__(self) -> None:
        super().__init__()
        self._state = IDLE
        self._state_lock = threading.Lock()
        self._models_ready = threading.Event()
        self._models_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._cap = None
        self._latest: np.ndarray | None = None
        self._latest_id = 0
        self._frame_cond = threading.Condition()
        self._targets: tuple = (None, [])     # (frame shape, faces) from the detector thread
        self._preview: np.ndarray | None = None
        self._preview_lock = threading.Lock()
        self._preview_pending = False
        self._source = None                   # insightface Face or None (= real face)
        self._settings = Settings()
        self._quality = QUALITY["balanced"]
        self._color_fix = False
        self._enhancer_state = "off"          # off | loading | ready | failed
        self._awake = AwakeGuard()

    # ── state ────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    @property
    def models_ready(self) -> bool:
        return self._models_ready.is_set()

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            if self._state == state:
                return
            self._state = state
        log.info("engine state → %s", state)
        self.stateChanged.emit(state)

    # ── models ───────────────────────────────────────────────────────────

    def prepare(self) -> None:
        """Warm the models up in the background so Start is quick."""
        if self._models_ready.is_set():
            return
        threading.Thread(target=self._load_models_safe, name="mirage-models", daemon=True).start()

    def _load_models_safe(self) -> bool:
        try:
            self._load_models()
            self.modelsState.emit("ready")
            return True
        except Exception as exc:
            log.exception("model loading failed")
            self.modelsState.emit("failed")
            key = "toast_models_missing" if not models_present() else "toast_models_failed"
            self.notice.emit("error", key, {"error": str(exc)})
            return False

    def _load_models(self) -> None:
        with self._models_lock:
            if self._models_ready.is_set():
                return
            t0 = time.monotonic()
            self.modelsState.emit("loading")
            configure_upstream()
            from modules.face_analyser import get_face_analyser
            from modules.processors.frame import face_swapper

            get_face_analyser()
            face_swapper.FACE_SWAPPER_LOAD_FAILED = False
            if face_swapper.get_face_swapper() is None:
                raise RuntimeError("face swapper model could not be loaded")
            self._models_ready.set()
            log.info("models ready in %.1fs", time.monotonic() - t0)

    # ── configuration (UI thread) ────────────────────────────────────────

    def set_face(self, embedding: np.ndarray | None) -> None:
        """Swap to this identity (None = show the real face). Instant."""
        self._source = None if embedding is None else _Source(embedding)

    def apply(self, settings: Settings) -> None:
        import modules.globals as G

        self._settings = settings
        G.opacity = float(settings.opacity)
        G.sharpness = float(settings.sharpness)
        G.mouth_mask = bool(settings.mouth_mask)
        G.mouth_mask_size = MOUTH_MASK_SIZE if settings.mouth_mask else 0.0
        G.show_mouth_mask_box = False
        G.many_faces = bool(settings.many_faces)
        G.poisson_blend = bool(settings.poisson_blend)
        G.color_correction = False  # handled here, per frame
        self._color_fix = bool(settings.color_fix)
        quality = QUALITY.get(settings.quality, QUALITY["balanced"])
        chose_best_now = quality.enhancer and not self._quality.enhancer
        if chose_best_now and self._enhancer_state == "failed":
            self._enhancer_state = "off"  # an explicit new choice of Best retries once
        self._quality = quality
        if quality.enhancer and self._enhancer_state == "off" and self._models_ready.is_set():
            self._load_enhancer_async()

    def _load_enhancer_async(self) -> None:
        if self._enhancer_state in ("loading", "ready"):
            return
        self._enhancer_state = "loading"
        self.notice.emit("info", "toast_enhancer_loading", {})

        def work() -> None:
            try:
                import importlib

                module = importlib.import_module(ENHANCER_MODULE)
                module.get_enhancer()  # downloads (first time), loads and warms up
                self._enhancer_state = "ready" if module.ENHANCER is not None else "failed"
            except Exception:
                log.exception("enhancer failed to load")
                self._enhancer_state = "failed"
            if self._enhancer_state == "failed":
                self._quality = QUALITY["balanced"]  # what the toast promises
                self.qualityFallback.emit("balanced")
                self.notice.emit("warn", "toast_enhancer_failed", {})

        threading.Thread(target=work, name="mirage-enhancer", daemon=True).start()

    # ── start / stop ─────────────────────────────────────────────────────

    def start(self, camera: CameraInfo) -> None:
        if self._state not in (IDLE,):
            return
        self._stop.clear()
        self._set_state(STARTING if self._models_ready.is_set() else LOADING)
        threading.Thread(target=self._start_worker, args=(camera,), name="mirage-start", daemon=True).start()

    def _start_worker(self, camera: CameraInfo) -> None:
        try:
            self._start(camera)
        except Exception:
            log.exception("starting live failed")
            self.notice.emit("error", "toast_camera_failed", {})
            if self._cap is None:
                self._set_state(IDLE)

    def _camera_allowed(self) -> bool:
        """Ask macOS for camera access up front and wait for the answer.

        OpenCV would fire the permission prompt and fail immediately, so the
        first Start on a fresh install looked broken.
        """
        if sys.platform != "darwin":
            return True
        import AVFoundation as AVF

        status = AVF.AVCaptureDevice.authorizationStatusForMediaType_(AVF.AVMediaTypeVideo)
        if status == AVF.AVAuthorizationStatusAuthorized:
            return True
        if status != AVF.AVAuthorizationStatusNotDetermined:
            return False  # denied or restricted: only System Settings can change it
        answered, result = threading.Event(), {}

        def handler(granted: bool) -> None:
            result["granted"] = bool(granted)
            answered.set()

        AVF.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVF.AVMediaTypeVideo, handler)
        while not answered.wait(0.2):
            if self._stop.is_set():
                return False
        return result.get("granted", False)

    def _start(self, camera: CameraInfo) -> None:
        if not self._models_ready.is_set() and not self._load_models_safe():
            self._set_state(IDLE)
            return
        if self._quality.enhancer:
            self._load_enhancer_async()
        if self._stop.is_set():
            self._set_state(IDLE)
            return
        self._set_state(STARTING)

        if camera.uid and camera.uid.startswith("demo:"):
            from mirage.demo import DemoCapturer

            cap = DemoCapturer(camera.uid[len("demo:"):])
        else:
            if not self._camera_allowed():
                if not self._stop.is_set():
                    self.notice.emit("error", "toast_camera_denied", {})
                self._set_state(IDLE)
                return
            from modules.video_capture import VideoCapturer

            cap = VideoCapturer(camera.index)
        if not cap.start(640, 480, 30):
            self.notice.emit("error", "toast_camera_failed", {})
            self._set_state(IDLE)
            return
        if self._stop.is_set():
            cap.release()
            self._set_state(IDLE)
            return
        self._cap = cap
        with self._frame_cond:
            self._latest, self._latest_id = None, 0
        self._targets = (None, [])
        self._threads = [
            threading.Thread(target=self._capture_loop, name="mirage-capture", daemon=True),
            threading.Thread(target=self._detect_loop, name="mirage-detect", daemon=True),
            threading.Thread(target=self._process_loop, name="mirage-process", daemon=True),
        ]
        for t in self._threads:
            t.start()
        self._awake.hold("Mirage is live")
        self._set_state(LIVE)

    def stop(self) -> None:
        """Stop without blocking the UI; state goes stopping → idle."""
        if self._state in (IDLE, STOPPING):
            return
        self._set_state(STOPPING)
        self._stop.set()
        threading.Thread(target=self._teardown, name="mirage-stop", daemon=True).start()

    def shutdown(self, timeout: float = 6.0) -> None:
        """Blocking stop for app quit."""
        self._stop.set()
        self._teardown(timeout)

    def _teardown(self, timeout: float = 6.0) -> None:
        with self._frame_cond:
            self._frame_cond.notify_all()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))
        alive = [t.name for t in self._threads if t.is_alive()]
        if alive:
            log.warning("threads still running after stop: %s", alive)
        cap, self._cap = self._cap, None
        capture_alive = any(t.name == "mirage-capture" for t in self._threads if t.is_alive())
        if cap is not None and not capture_alive:
            cap.release()  # never release under a blocked read()
        self._threads = []
        from modules import virtualcam_out

        virtualcam_out.close()
        self._awake.release()
        with self._preview_lock:
            self._preview = None
        self._set_state(IDLE)

    # ── preview hand-off (UI thread) ─────────────────────────────────────

    def take_preview(self) -> np.ndarray | None:
        with self._preview_lock:
            frame, self._preview = self._preview, None
            self._preview_pending = False
        return frame

    def _offer_preview(self, frame: np.ndarray) -> None:
        with self._preview_lock:
            self._preview = frame
            if self._preview_pending:
                return  # UI hasn't taken the last one yet; it'll get this newer one
            self._preview_pending = True
        self.previewReady.emit()

    # ── threads ──────────────────────────────────────────────────────────
    #
    # capture → latest frame → detector (GPU, paced)  → latest face boxes ─┐
    #                        → processor (Neural Engine, back-to-back) ◄───┘
    # Running detection and swapping in parallel keeps both accelerators busy;
    # in one loop each waited for the other (~100 ms/frame vs ~65 ms).

    def _capture_loop(self) -> None:
        failing_since = None
        while not self._stop.is_set():
            try:
                ok, frame = self._cap.read()
            except Exception as exc:
                log.warning("camera read error: %s", exc)
                ok, frame = False, None
            if not ok or frame is None:
                now = time.monotonic()
                failing_since = failing_since or now
                if now - failing_since >= CAPTURE_GRACE_SECONDS:
                    self.notice.emit("error", "toast_camera_lost", {})
                    if not self._stop.is_set():
                        self.stop()
                    return
                time.sleep(0.05)
                continue
            failing_since = None
            with self._frame_cond:
                self._latest = frame
                self._latest_id += 1
                self._frame_cond.notify_all()

    def _wait_frame(self, seen: int) -> tuple[int, np.ndarray | None]:
        """Newest frame newer than ``seen`` (or None after a short wait)."""
        with self._frame_cond:
            if self._latest_id == seen:
                self._frame_cond.wait(0.1)
            if self._latest_id == seen or self._latest is None:
                return seen, None
            return self._latest_id, self._latest

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(frame[:, :, ::-1]) if self._color_fix else frame

    def _detect_loop(self) -> None:
        from insightface.app.common import Face

        from modules.face_analyser import detect_many_faces_fast, detect_one_face_fast, ensure_landmarks

        smoother = FaceSmoother()
        seen, last_shape = 0, None
        logged: set[str] = set()
        while not self._stop.is_set():
            if self._source is None:          # showing the real face: nothing to track
                self._targets = (None, [])
                smoother.reset()
                self._stop.wait(0.1)
                continue
            seen, frame = self._wait_frame(seen)
            if frame is None:
                continue
            t0 = time.monotonic()
            try:
                frame = self._prepare(frame)
                if frame.shape != last_shape:
                    last_shape = frame.shape
                    smoother.reset()
                if self._settings.many_faces:
                    faces = detect_many_faces_fast(frame) or []
                else:
                    found = detect_one_face_fast(frame)
                    if found is None:
                        smoother.reset()
                        faces = []
                    else:
                        bbox, kps = smoother.update(found.bbox, found.kps)
                        faces = [Face(bbox=bbox, kps=kps, det_score=found.det_score)]
                if faces and self._settings.mouth_mask:
                    ensure_landmarks(frame, faces)
                self._targets = (frame.shape, faces)
            except Exception as exc:
                kind = f"{type(exc).__name__}: {exc}"[:160]
                if kind not in logged:
                    logged.add(kind)
                    log.error("face detection failed:\n%s", traceback.format_exc())
                self._targets = (None, [])
            wait = self._quality.detect_interval - (time.monotonic() - t0)
            if wait > 0:
                self._stop.wait(wait)

    def _process_loop(self) -> None:
        from modules import virtualcam_out
        from modules.processors.frame.face_swapper import apply_post_processing, swap_face

        seen = 0
        logged: set[str] = set()
        fps_count, fps_t0 = 0, time.monotonic()
        last_preview = 0.0

        while not self._stop.is_set():
            seen, frame = self._wait_frame(seen)
            if frame is None:
                continue
            frame = self._prepare(frame)
            out = frame
            source = self._source
            shape, faces = self._targets
            face_found = source is None or bool(faces)
            try:
                if source is not None and faces and shape == frame.shape:
                    out = frame.copy()
                    boxes = []
                    for face in faces:
                        out = swap_face(source, face, out)
                        boxes.append(np.asarray(face.bbox).astype(int))
                    out = apply_post_processing(out, boxes)
                    if self._quality.enhancer and self._enhancer_state == "ready":
                        import importlib

                        enhancer = importlib.import_module(ENHANCER_MODULE)
                        out = enhancer.process_frame(None, out, detected_faces=faces)
            except Exception as exc:
                kind = f"{type(exc).__name__}: {exc}"[:160]
                if kind not in logged:
                    logged.add(kind)
                    log.error("frame processing failed:\n%s", traceback.format_exc())
                    self.notice.emit("warn", "toast_frame_error", {})
                out = frame

            if not self._stop.is_set():
                virtualcam_out.send(out)
            now = time.monotonic()
            if now - last_preview >= 1.0 / PREVIEW_MAX_FPS:
                last_preview = now
                self._offer_preview(out)

            fps_count += 1
            if now - fps_t0 >= 0.5:
                fps = fps_count / (now - fps_t0)
                fps_count, fps_t0 = 0, now
                self.statsChanged.emit({"fps": fps, "face_found": face_found, "vcam": virtualcam_out.is_streaming()})
