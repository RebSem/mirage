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
Camera ──► CaptureThread ──► ProcessingThread ──┬─► OBS Virtual Camera (1280x720) ─► Zoom / Meet / OBS
            (AVFoundation)    detect ▸ swap ▸     │
                              enhance ▸ blend     └─► UI preview (Qt, ≤30 fps)
```

* **CaptureThread** reads frames and survives short camera gaps (5 s).
* **ProcessingThread** runs detection every few frames, smooths the face
  landmarks between detections, swaps with the current face *embedding*, and
  never dies on a bad frame.
* The **virtual camera** output is always 1280x720, so Zoom never sees the
  stream restart when the webcam switches 4:3 ↔ 16:9.
* While live, the process holds an `NSProcessInfo` activity (no App Nap, no
  idle sleep).

## Package map (`mirage/`)

| module | owns |
|---|---|
| `__init__.py` | `__version__`, `APP_NAME = "Mirage"`, `BUNDLE_ID = "io.github.rebsem.mirage"` |
| `__main__.py` | `python -m mirage` entry |
| `app.py` | QApplication setup, single instance, logging, signals, lifecycle |
| `paths.py` | all filesystem locations (see below) |
| `settings.py` | persisted user settings (JSON) |
| `library.py` | face library: import photos, thumbnails, cached embeddings |
| `faces_ai.py` | glue to the upstream detector: photo → `DetectedFace` |
| `camera.py` | camera discovery (AVFoundation order, uid → OpenCV index) |
| `engine.py` | `LiveEngine`: capture + processing threads, virtual camera |
| `glass.py` | native Liquid Glass (`NSGlassEffectView`) behind Qt widgets |
| `i18n.py` | UI strings, English + Russian |
| `theme.py` | colours, radii, fonts, Qt style sheet |
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

Every function creates the directory it returns (except `repo_root`).

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

Unknown keys are ignored; out-of-range values are clamped/reset to defaults.

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
* Default name for `add_file` is the file stem, prettified.

Switching faces is instant because the engine only needs the cached
512-float embedding, not a new detection.

### `faces_ai.py`

`embed(image) -> DetectedFace | None` wraps
`modules.face_analyser` (largest face, padded retry for close-ups) and maps
the box back to original image coordinates.

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
def resolve_index(uid: str) -> int | None
```

### `engine.py`

`LiveEngine(QObject)` — signals: `frameReady(object)` (BGR ndarray for the
preview), `statsChanged(dict)` (`fps`, `face_found`), `stateChanged(str)`
(`idle` / `loading` / `live` / `stopping`), `message(str, str)` (level, text).
Methods: `prepare()` (load models in background), `start(camera: CameraInfo)`,
`stop()`, `set_face(embedding | None)`, `apply(settings)`.

Swap runs on the Neural Engine (`MLComputeUnits=CPUAndNeuralEngine`,
~63 ms/frame on M1 vs ~85 ms with `ALL`); detection runs on the GPU in
parallel.

### `glass.py`

`GlassWindow` makes a Qt top-level window transparent with a full-size
content view and a behind-window blur, then keeps one `NSGlassEffectView`
per registered widget exactly behind that widget (tracking move/resize/show).
An *ambient* layer (a heavily blurred, tiny copy of the live video) sits
under the glass so the glass refracts the colours of your own video. On
anything other than macOS 26+ it degrades to a translucent Qt fill.

Native view order inside the window frame (bottom → top):
`NSVisualEffectView` (behind-window blur) → ambient layer →
`NSGlassEffectView`s → Qt's `QNSView` (all widgets, transparent background).

## Design rules

* One window. Stage (video) left, glass sidebar right, glass control bar
  under the stage. One primary action: **Start / Stop**.
* Faces are big round thumbnails; click or press `1`–`9` to switch, `0` for
  the real face. Drag photos in to add them.
* Every state has words: *Loading models…*, *Live · 14 fps*, *No face in
  view*, *Virtual camera: ready*.
* No modal error dialogs during live; use glass toasts.

## Tests

`tests/mirage/` must run without models, camera, network or a display:
settings round-trip, library with a fake embedder, `order_devices`, the
virtual-camera frame fit, i18n key parity, landmark smoothing.
