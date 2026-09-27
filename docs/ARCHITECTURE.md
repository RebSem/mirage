# Mirage architecture

Mirage is a macOS-first frontend for real-time face swapping, built on top of
the [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) engine. The
upstream engine lives in `modules/` and stays close to upstream; everything
Mirage adds lives in the `mirage/` package.

```
run.py              upstream "classic" UI + CLI (still works)
modules/            upstream engine: detection, face swap, enhancers
mirage/             Mirage app (this document)
scripts/            install, app bundle, icon, benchmark
tests/mirage/       unit tests for mirage/ (no models, no camera needed)
docs/               documentation
```

## Runtime picture

```
                                ┌─► detect  (GPU, 320 px, paced) ──► latest face boxes
Camera ─► capture ─► latest ────┤                                          │
          thread     frame      └─► process (Neural Engine) ◄──────────────┘
                                    swap ▸ post-process ▸ enhance (Best)
                                         │
                                         ├─► OBS Virtual Camera (1280x720) ─► Zoom / Meet
                                         └─► UI preview (Qt, ≤ 30 fps)
```

Three plain Python threads (not `QThread`s, so quitting never hits Qt's
"QThread: Destroyed while thread is still running" abort) share the newest
camera frame:

* **capture** (`mirage-capture`) reads the camera, keeps only the newest frame
  and survives short camera gaps; after 5 s without frames it stops the
  session with a toast.
* **detect** (`mirage-detect`) finds the largest face on the newest frame
  with the 320 px detector on the GPU (CoreML `CPUAndGPU`), smooths its box
  and keypoints from one detection to the next (`tracking.FaceSmoother`),
  adds mouth landmarks only when *Keep my mouth* is on, and publishes the
  result. It is paced by the quality preset: Fast starts a detection at most
  every 0.10 s, Balanced every 0.04 s, Best runs them back-to-back. It idles
  while you show your real face. With *Swap everyone in view* it keeps every
  face (unsmoothed) instead of the largest one.
* **process** (`mirage-process`) runs back-to-back on each new frame: swaps
  every face in the latest boxes with the current face *embedding*, applies
  post-processing and, on Best, the GPEN-BFR-256 enhancer, then sends the
  result to the virtual camera and offers it to the preview. It never dies on
  a bad frame: it logs each new kind of error once (with a toast) and sends
  the plain camera frame instead.
* With *Fix blue tint* on, both threads swap the red and blue channels of
  each camera frame before using it.
* Detection and swapping run in parallel, so the GPU and the Neural Engine are
  busy at the same time; in one loop each waited for the other (about 100 ms
  per frame instead of about 65 ms).
* The **virtual camera** output is always 1280x720, so Zoom never sees the
  stream restart when the webcam switches 4:3 ↔ 16:9.
* While live, the process holds an `NSProcessInfo` activity (no App Nap, no
  idle sleep).

## Package map (`mirage/`)

| module | owns |
|---|---|
| `__init__.py` | `__version__`, `APP_NAME = "Mirage"`, `BUNDLE_ID = "io.github.rebsem.mirage"` |
| `__main__.py` | `python -m mirage` entry |
| `app.py` | QApplication setup, single instance, logging, Qt's own strings in Russian, dark appearance, signals, quit cleanup |
| `paths.py` | all filesystem locations (see below) |
| `settings.py` | persisted user settings (JSON) |
| `library.py` | face library: import photos, thumbnails, cached embeddings |
| `upstream.py` | configures the upstream engine once (CoreML, 320 px live detector) |
| `faces_ai.py` | photo → `DetectedFace` with its own 640 px detector; random faces |
| `camera.py` | camera discovery (AVFoundation order, uid → OpenCV index), OBS camera check |
| `engine.py` | `LiveEngine`: capture, detect and process threads, virtual camera |
| `tracking.py` | `FaceSmoother`: steadies the face box and keypoints between detections |
| `power.py` | `AwakeGuard`: keeps the Mac awake while live |
| `demo.py` | a fake "Demo" camera (`python -m mirage --demo face.jpg`) |
| `glass.py` | native Liquid Glass (`NSGlassEffectView`) behind Qt widgets |
| `i18n.py` | UI strings, English + Russian |
| `theme.py` | colours, radii, fonts, motion timings (off with Reduce motion), Qt style sheet |
| `ui/` | main window and widgets |

### `paths.py`

All locations can be redirected with the `MIRAGE_HOME` environment variable
(used by tests). Defaults on macOS:

| function | default |
|---|---|
| `app_support_dir()` | `~/Library/Application Support/Mirage` |
| `faces_dir()` | `<app_support>/faces` |
| `settings_path()` | `<app_support>/settings.json` |
| `logs_dir()` | `~/Library/Logs/Mirage` (or `<MIRAGE_HOME>/logs`) |
| `repo_root()` | the checkout (parent of `mirage/`) |
| `models_dir()` | `<repo_root>/models` |

Each function creates the directory it returns; `settings_path()` creates
the folder that holds the file, and `repo_root()` creates nothing.

### `settings.py`

```python
@dataclass
class Settings:
    camera_uid: str | None = None
    face_id: str | None = None          # None = show my real face ("Original")
    quality: str = "balanced"           # "fast" | "balanced" | "best"
    opacity: float = 1.0                # 0..1, face blend
    sharpness: float = 0.0              # 0..1
    mouth_mask: bool = False            # keep my own mouth
    many_faces: bool = False
    color_fix: bool = False
    poisson_blend: bool = False
    mirror_preview: bool = True         # preview only; virtual cam is never mirrored
    show_fps: bool = False
    language: str = "auto"              # "auto" | "en" | "ru"
    onboarding_done: bool = False
    window_geometry: str | None = None  # base64 of QWidget.saveGeometry()

def load(path: Path | None = None) -> Settings    # missing/corrupt file → defaults
def save(settings: Settings, path: Path | None = None) -> None   # atomic write
```

Unknown keys are ignored; a value of the wrong type falls back to its
default, and `opacity` and `sharpness` are clamped to 0..1.

### `library.py`

```python
class DetectedFace(NamedTuple):
    embedding: np.ndarray                     # float32, shape (512,)
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2 in the given image

Embedder = Callable[[np.ndarray], DetectedFace | None]   # BGR uint8 image in

class NoFaceError(ValueError): ...
class UnreadableImageError(ValueError): ...

@dataclass
class FaceEntry:
    id: str          # 12 hex chars
    name: str
    created: float   # unix time
    image: str       # file name inside the library dir
    thumb: str
    embedding: str

class FaceLibrary:
    def __init__(self, root: Path, embedder: Embedder): ...
    def list(self) -> list[FaceEntry]                   # user order
    def get(self, face_id: str) -> FaceEntry | None
    def add_file(self, path: Path, name: str | None = None) -> FaceEntry
    def add_image(self, image: np.ndarray, name: str) -> FaceEntry
    def remove(self, face_id: str) -> None
    def rename(self, face_id: str, name: str) -> None
    def move(self, face_id: str, index: int) -> None
    def embedding(self, face_id: str) -> np.ndarray     # cached in memory
    def image_path(self, face_id: str) -> Path
    def thumb_path(self, face_id: str) -> Path
```

* Storage: `<root>/index.json` (`{"version": 1, "faces": [...]}`) plus
  `<id>.jpg` (longest side ≤ 1024), `<id>_thumb.jpg` (256×256 square crop
  centred on the face box enlarged 1.8×, padded if needed) and `<id>.npy`.
* Writes are atomic (temp file + `os.replace`). Entries whose files went
  missing are dropped on load. Thread-safe with a lock.
* If `index.json` is missing or damaged, the library is rebuilt from the
  `<id>.jpg` / `<id>_thumb.jpg` / `<id>.npy` files on load (names reset to
  "Face", ordered by file time). A damaged index is kept as
  `index.corrupt-<time>.json` and never overwritten.
* Photos are detected on a copy capped at 2048 px; HEIC and other formats
  OpenCV can't read go through macOS `sips`.
* Default name for `add_file` is the file stem, prettified.

Switching faces is instant because the engine only needs the cached
512-float embedding, not a new detection.

### `upstream.py`

`configure_upstream()` sets `modules.globals` for Mirage exactly once
(idempotent, under a lock): headless, CoreML + CPU execution providers, only
the face swapper as a frame processor, the classic UI's enhancers and face
mapping off, and `det_size = 320` (`LIVE_DET_SIZE`). It must run before the
upstream face analyser is first created, because insightface fixes the
detector size and providers at that point and the analyser is cached. The
engine's model loading and `faces_ai.embed` both call it first. Faces on a
webcam are big, so 320 px is enough: about 9 ms per detection on M1 instead
of about 26 ms at 640.

### `faces_ai.py`

`embed(image) -> DetectedFace | None` uses its own 640x640 detector on the
CPU (`det_10g.onnx` from `buffalo_l`), not the live one: photos can have
small faces, and an import can afford about 100 ms. It takes the largest
face, retries with a dark border (30 %, 60 %) for close-ups, gets the
embedding from the upstream recognition model and maps the box back to the
original image coordinates. `fetch_random_face()` downloads a generated face
from thispersondoesnotexist.com.

### `camera.py`

```python
@dataclass(frozen=True)
class CameraInfo:
    index: int        # what cv2.VideoCapture(index) opens
    name: str
    uid: str | None
    builtin: bool

def order_devices(devices: list[tuple[str, str, bool]]) -> list[CameraInfo]
    # pure: (name, uid, builtin) in any order → OpenCV indices by uniqueID
    # order, OBS Virtual Camera removed, built-in first
def list_cameras() -> list[CameraInfo]
def virtual_camera_installed() -> bool   # OBS Virtual Camera shows up as a device
def resolve(uid: str | None, fallback: CameraInfo | None = None) -> CameraInfo | None
```

### `engine.py`

`LiveEngine(QObject)`. Signals are emitted from worker threads; Qt queues
them to the UI thread.

| signal | meaning |
|---|---|
| `stateChanged(str)` | `idle` → `loading` (models not ready yet) → `starting` → `live` → `stopping` → `idle` |
| `modelsState(str)` | `loading` / `ready` / `failed` |
| `qualityFallback(str)` | Best's enhancer failed to load; the engine dropped to this preset (`balanced`) and the UI moves the Quality control to match |
| `previewReady()` | a new preview frame is waiting; the UI pulls it with `take_preview()` (at most one pending, the newest wins) |
| `statsChanged(dict)` | `{"fps": float, "face_found": bool, "vcam": bool}`, about twice a second |
| `notice(level, i18n_key, args)` | a toast: `info` / `warn` / `error`, a key in `mirage/i18n.py`, format args |

Methods (call them from the UI thread; only `shutdown()` blocks):

* `prepare()`: load the models in the background at launch, so Start is quick.
* `start(camera: CameraInfo)`: only from `idle`. A worker thread loads the
  models (or waits for the warm-up to finish), asks macOS for camera access
  (and waits for the answer), opens the camera and starts the three threads.
* `stop()`: `stopping`, then `idle` once the threads are down.
* `shutdown()`: blocking stop for quitting; joins the threads for up to 6 s
  and never releases the camera under a blocked read.
* `set_face(embedding | None)`: switch identity instantly; `None` shows the
  real face.
* `apply(settings)`: blend, sharpness, mouth mask, many faces, colour fix,
  smooth edges and quality. Choosing Best loads the enhancer in the background
  (downloading GPEN-BFR-256 the first time); choosing Best again after a
  failure retries once.
* `take_preview()`: the newest preview frame, or `None`.

The swap model runs on the Neural Engine (`MLComputeUnits=CPUAndNeuralEngine`,
about 63 ms per frame on M1 vs about 82 ms with `ALL`; `make bench` compares
the compute units on your Mac). Detection runs on the GPU in parallel.

### `app.py`: quitting

`cleanup()` in `app.main()` saves the settings and calls `engine.shutdown()`,
exactly once, whichever way Mirage ends: the window's `closeEvent` (through
the `closing` signal), `aboutToQuit`, or `SIGINT` / `SIGTERM`. The
`closeEvent` hook is the one that matters on macOS: `⌘Q` ends in
`[NSApp terminate:]`, which exits the process without returning from
`exec()` or emitting `aboutToQuit`, but Qt closes the windows first.

### `glass.py`

`GlassWindow` makes a Qt top-level window transparent with a full-size
content view and a behind-window blur, then keeps one `NSGlassEffectView`
per registered widget exactly behind that widget (tracking move/resize/show).
An *ambient* layer (a heavily blurred, tiny copy of the live video) sits
under the glass so the glass refracts the colours of your own video. On
anything older than macOS 26, with Reduce transparency on, or if setting up
the native views fails, `native` is `False`: the window paints a plain opaque
dark background and the panels paint a subtle translucent fill.

Native view order inside the window frame (bottom → top):
`NSVisualEffectView` (behind-window blur) → ambient layer →
`NSGlassEffectView`s → Qt's `QNSView` (all widgets, transparent background).

## Design rules

* One window. Stage (video) left, glass sidebar right, glass control bar
  under the stage. One primary action: **Start / Stop**.
* Faces are big round thumbnails; click or press `1`–`9` to switch, `0` for
  the real face. Drag photos in to add them.
* Every state has words: *Loading models…*, *Starting camera…*,
  *Live · 14 fps*, *Stopping…*, *Models didn't load*, *Looking for your
  face…*, *Nothing is reaching OBS Virtual Camera*.
* No modal error dialogs during live; use glass toasts. The only dialogs are
  the ones the user asks for (rename, confirm a removal).

## Tests

`tests/mirage/` must run without models, camera, network or a display:
settings round-trip, library with a fake embedder, `order_devices`, the
virtual-camera frame fit, i18n key parity, landmark smoothing.
