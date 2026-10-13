"""Their hairstyle: the hair from a face's photo, worn live over your own.

How it works (see docs/ARCHITECTURE.md, "Hairstyle"):

* Every head is brought into one *canonical* 512×512 square by a similarity
  transform of its five face points (eyes, nose, mouth corners), with room for
  long and big hair around the face.
* Once per library face, a face-parsing model (BiSeNet, 19 classes) splits
  that square of the photo into hair, skin and the rest. The result is a
  *template*: the hair with a soft, clean edge, and the whole head with a
  smooth skin colour. Templates are cached in ``cache_dir()/hair``.
* Live, the template is placed on your face points every frame. A few times a
  second the same model finds *your* hair in the camera picture (on the CPU,
  so the Neural Engine stays with the face swap). Where your hair sticks out
  beyond the new head it is replaced by what is behind you; where the new
  head has skin (a forehead, a shorter cut) it gets that skin, matched to your
  lighting; then the new hair is laid on top.

The heavy part (onnxruntime) is imported lazily; the geometry and the template
maths are plain numpy + OpenCV and are unit-tested without the model.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from mirage import compose, paths

log = logging.getLogger(__name__)

PARSER_FILE = "face_parsing_resnet18.onnx"
PARSER_URL = "https://github.com/yakhyo/face-parsing/releases/download/v0.0.1/resnet18.onnx"
PARSER_SIZE = 53205364
PARSER_SHA256 = "0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f"
PARSER_THREADS = 2          # leave the other cores to the live pipeline
TEMPLATE_VERSION = 1        # bump when the template recipe changes (old caches are rebuilt)
WIDTH_FIT = (0.85, 1.2)     # how far the hairstyle may widen or narrow to fit your face

CANON = 512
# InsightFace's 5-point ArcFace template (112×112), scaled and moved so the
# face sits a little below the middle and the whole head (big hair, hair to
# the shoulders) fits around it.
_ARCFACE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                     [41.5493, 92.3655], [70.7299, 92.2041]], np.float32)
CANON_KPS = ((_ARCFACE - (56.0, 71.7)) * 2.2 + (256.0, 270.0)).astype(np.float32)

# CelebAMask-HQ labels of the face-parsing model
BACKGROUND, SKIN, NECK, CLOTH, HAIR, HAT = 0, 1, 14, 16, 17, 18
HAIR_CLASSES = (HAIR, HAT)       # a hat travels with the hairstyle rather than leaving a hole
HEAD_CLASSES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, HAIR, HAT)
SKIN_CLASSES = (SKIN, 7, 8, 10)  # skin, ears, nose: the colour a bare forehead or scalp gets
FACE_CLASSES = tuple(range(1, 14))  # the face itself, ears included: your hair over it stays

# Where skin colour is measured: both cheeks, between the eye and the mouth corner.
_CHEEKS = np.array([(CANON_KPS[0] + CANON_KPS[3]) / 2, (CANON_KPS[1] + CANON_KPS[4]) / 2], np.float32)
_CHEEK_RADIUS = 9.0
# Above the eyebrows your hair may become bare skin (a forehead, a scalp); below
# them it never does: temples, ears and cheeks can't be painted convincingly.
_BROW_Y = float(CANON_KPS[:2, 1].mean()) - 10.0   # just above the eyes: bangs over the brows go too
_FOREHEAD = np.repeat(np.clip((_BROW_Y - np.arange(CANON, dtype=np.float32)) / 18.0, 0.0, 1.0)[:, None],
                      CANON, axis=1)
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


# ── geometry ─────────────────────────────────────────────────────────────

def similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity (rotation, uniform scale, shift) mapping ``src`` points
    onto ``dst`` points (Umeyama); a 2×3 matrix for ``cv2.warpAffine``."""
    src = np.asarray(src, np.float64).reshape(-1, 2)
    dst = np.asarray(dst, np.float64).reshape(-1, 2)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    sign = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[1, 1] = -1
    rot = u @ sign @ vt
    var = (s ** 2).sum() / len(src)
    scale = float(np.trace(np.diag(sig) @ sign) / max(var, 1e-12))
    m = np.zeros((2, 3), np.float64)
    m[:, :2] = scale * rot
    m[:, 2] = mu_d - scale * rot @ mu_s
    return m.astype(np.float32)


def to_canonical(image: np.ndarray, kps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The canonical square of the head around ``kps``, and where the picture really is (0..1)."""
    m = similarity(kps, CANON_KPS)
    # Repeat the edge rather than paint black: a head cut off by the top of the
    # picture otherwise reads to the parser as a hat on a black wall.
    canon = cv2.warpAffine(image, m, (CANON, CANON), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpAffine(np.ones(image.shape[:2], np.float32), m, (CANON, CANON),
                           flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return canon, valid


# ── the face-parsing model ───────────────────────────────────────────────

def parser_path() -> Path:
    return paths.models_dir() / PARSER_FILE


def parser_present() -> bool:
    path = parser_path()
    return path.is_file() and path.stat().st_size == PARSER_SIZE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_DOWNLOAD_LOCK = threading.Lock()


def ensure_parser() -> Path | None:
    """The face-parsing model, downloaded (53 MB, once) and checked; None if that failed."""
    path = parser_path()
    with _DOWNLOAD_LOCK:
        if parser_present():
            return path
        import mirage  # noqa: F401  (puts the engine, and its downloader, on sys.path)
        from modules.model_downloader import _download  # resumable, TLS-verified, size-checked

        if not _download(PARSER_FILE, PARSER_URL, str(path), PARSER_SIZE):
            return None
        if _sha256(path) != PARSER_SHA256:  # weights we execute: never trust a mirror blindly
            log.error("%s does not match its checksum; deleted", path.name)
            path.unlink(missing_ok=True)
            return None
        return path


_SESSION = None
_SESSION_LOCK = threading.Lock()


def _session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            import onnxruntime as ort

            path = ensure_parser()
            if path is None:
                raise RuntimeError("the face-parsing model could not be downloaded")
            options = ort.SessionOptions()
            options.intra_op_num_threads = PARSER_THREADS
            options.inter_op_num_threads = 1
            # CPU on purpose: the Neural Engine runs the swap, the GPU the detector,
            # and CoreML's GPU path rejects one of this model's layers.
            _SESSION = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    return _SESSION


def parse(canon: np.ndarray) -> np.ndarray:
    """Class probabilities (19×512×512 float32) for a canonical BGR square."""
    x = cv2.cvtColor(canon, cv2.COLOR_BGR2RGB).astype(np.float32) * (1.0 / 255.0)
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
    logits = _session().run(["output"], {"input": np.ascontiguousarray(x)})[0][0]
    logits -= logits.max(axis=0, keepdims=True)
    np.exp(logits, out=logits)
    logits /= logits.sum(axis=0, keepdims=True)
    return logits


def hair_probability(probs: np.ndarray) -> np.ndarray:
    return probs[list(HAIR_CLASSES)].sum(axis=0).astype(np.float32)


def user_head_map(probs: np.ndarray) -> np.ndarray:
    """Your own head, canonical, CANON×CANON×4 float32: [hair, bare skin, face, forehead].

    The hair is a little generous at the edge (whatever is left of it would
    show as a grey or blond fringe); the bare skin is what a forehead is
    painted from, so it is strict; the face (ears included) is where your
    hair is left alone below the eyebrows.
    """
    hair = _smoothstep(hair_probability(probs), 0.15, 0.45)
    hair = cv2.dilate(hair, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    hair = cv2.GaussianBlur(hair, (0, 0), 2.5)
    skin = _smoothstep(probs[SKIN], 0.5, 0.8)
    skin = cv2.erode(skin, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    face = _smoothstep(probs[list(FACE_CLASSES)].sum(axis=0), 0.3, 0.6)
    face = cv2.GaussianBlur(cv2.dilate(face, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))), (0, 0), 1.5)
    return np.dstack([hair, skin * (1.0 - hair), face, _FOREHEAD]).astype(np.float32)


def face_width(probs: np.ndarray) -> float | None:
    """Width of the face (skin) at the height of the nose, in canonical pixels.

    Five points fix the eyes and the mouth, not how wide a face is; comparing
    this between the photo and you lets a hairstyle hug a wider or narrower face.
    """
    y = int(CANON_KPS[2, 1])
    rows = probs[SKIN, y - 12:y + 13] > 0.5
    widths = []
    for row in rows:
        cols = np.flatnonzero(row)
        if cols.size > 20:
            widths.append(float(cols[-1] - cols[0]))
    return float(np.median(widths)) if len(widths) >= 5 else None


def _smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ── templates ────────────────────────────────────────────────────────────

@dataclass
class HairTemplate:
    """A face's hairstyle in canonical space (all CANON×CANON)."""

    hair: np.ndarray        # uint8 BGRA: hair colour (extended past the edge) + soft hair alpha
    head: np.ndarray        # uint8 BGRA: smooth skin colour + alpha of the whole head (hair included)
    skin_ref: np.ndarray    # float32 BGR: the skin colour at the cheeks, to match the live picture
    face_width: float | None = None   # see face_width()

    @property
    def has_hair(self) -> bool:
        return bool((self.hair[..., 3] > 64).sum() > 400)


def _cheek_mean(image: np.ndarray, points: np.ndarray, radius: float) -> np.ndarray:
    h, w = image.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for x, y in points:
        cv2.circle(mask, (round(float(x)), round(float(y))), max(1, round(radius)), 255, -1)
    if not mask.any():
        return np.zeros(3, np.float32)
    return np.asarray(cv2.mean(image, mask=mask)[:3], np.float32)


def build_template(image: np.ndarray, kps: np.ndarray,
                   parse_fn: Callable[[np.ndarray], np.ndarray] = parse) -> HairTemplate:
    """Cut the hairstyle out of a photo (BGR) whose main face has these five points."""
    canon, valid = to_canonical(image, kps)
    probs = parse_fn(canon)
    # Fade out where the photo ends, so hair cut off by its frame doesn't end in a hard line.
    valid = cv2.erode(valid, np.ones((9, 9), np.uint8))
    valid = cv2.GaussianBlur(valid, (0, 0), 8.0)

    grey = cv2.cvtColor(canon, cv2.COLOR_BGR2GRAY).astype(np.float32) * (1.0 / 255.0)
    hair_p = hair_probability(probs)
    # Solid hair with a soft edge that follows the strands (the guided filter);
    # the parser's own probabilities are too timid inside dark hair.
    hair_a = _smoothstep(compose.guided_filter(grey, hair_p, 3, 5e-4), 0.25, 0.65) * valid
    head_p = probs[list(HEAD_CLASSES)].sum(axis=0)
    head_a = _smoothstep(compose.guided_filter(grey, head_p, 3, 5e-4), 0.2, 0.7) * valid

    # Hair colour without what was behind it (the wall, or the forehead between
    # strands): estimate that from everything that isn't hair, take it out of the
    # edge, and carry the hair colour a little past the edge so warping never
    # pulls in black.
    behind = compose.fill_holes(canon, np.clip(1.0 - hair_p * 2.0, 0.0, 1.0))
    a = hair_a[..., None]
    fg = np.clip(canon + (1.0 - a) / np.maximum(a, 0.3) * (canon - behind), 0, 255)
    solid = _smoothstep(hair_a, 0.5, 0.9)
    hair_rgb = compose.fill_holes(fg, solid)
    hair_rgb = np.where(solid[..., None] > 0.5, fg, hair_rgb)

    # One smooth skin colour for the whole head (a bare forehead, the scalp under
    # the old hair); smooth on purpose, so no eyes or eyebrows come along.
    skin_w = np.clip(probs[list(SKIN_CLASSES)].sum(axis=0) * 1.5 - 0.5, 0.0, 1.0) * valid
    skin_rgb = compose.fill_holes(canon, skin_w)

    hair = np.dstack([np.clip(hair_rgb, 0, 255), hair_a * 255.0]).astype(np.uint8)
    head = np.dstack([np.clip(skin_rgb, 0, 255), head_a * 255.0]).astype(np.uint8)
    return HairTemplate(hair=hair, head=head, skin_ref=_cheek_mean(head[..., :3], _CHEEKS, _CHEEK_RADIUS),
                        face_width=face_width(probs))


def template_path(face_id: str) -> Path:
    return paths.cache_dir() / "hair" / f"{face_id}-v{TEMPLATE_VERSION}.npz"


def save_template(template: HairTemplate, path: Path) -> None:
    import io

    from mirage.settings import write_atomic

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    width = np.float32(template.face_width if template.face_width is not None else np.nan)
    np.savez_compressed(buf, hair=template.hair, head=template.head, face_width=width)
    write_atomic(path, buf.getvalue())


def load_template(path: Path) -> HairTemplate | None:
    """A cached template, or None if it is missing or damaged (it is then rebuilt)."""
    try:
        with np.load(path, allow_pickle=False) as data:
            hair, head = data["hair"], data["head"]
            width = float(data["face_width"])
    except (OSError, KeyError, ValueError):
        return None
    shape = (CANON, CANON, 4)
    if hair.shape != shape or head.shape != shape or hair.dtype != np.uint8 or head.dtype != np.uint8:
        return None
    return HairTemplate(hair=hair, head=head, skin_ref=_cheek_mean(head[..., :3], _CHEEKS, _CHEEK_RADIUS),
                        face_width=width if np.isfinite(width) and width > 0 else None)


def forget(face_id: str) -> None:
    """Drop the cached template of a removed face."""
    for path in (paths.cache_dir() / "hair").glob(f"{face_id}-v*.npz"):
        path.unlink(missing_ok=True)


# ── wearing it live ──────────────────────────────────────────────────────

@dataclass
class Placed:
    """A template placed on a face in a frame: everything cropped to ``roi``."""

    roi: tuple[int, int, int, int]  # x0, y0, x1, y1 in the frame
    hair: np.ndarray                # uint8 BGR
    hair_alpha: np.ndarray          # float32 0..1
    skin: np.ndarray                # uint8 BGR (still the photo's skin colour)
    head_alpha: np.ndarray          # float32 0..1
    user_hair: np.ndarray | None    # float32 0..1, your own hair (None until it is first found)
    user_skin: np.ndarray | None    # float32 0..1, your bare skin (forehead, cheeks)
    user_face: np.ndarray | None    # float32 0..1, your face and ears
    forehead: np.ndarray | None     # float32 0..1, above your eyebrows
    cheeks: np.ndarray              # the two cheek points in the frame
    cheek_radius: float


def width_fit(template: HairTemplate, user_width: float | None) -> float:
    """Horizontal stretch that makes the hairstyle hug your face rather than the photo's."""
    if not template.face_width or not user_width:
        return 1.0
    return float(np.clip(user_width / template.face_width, *WIDTH_FIT))


def place(template: HairTemplate, kps: np.ndarray, frame_shape: tuple[int, ...],
          user_head: np.ndarray | None = None, user_width: float | None = None) -> Placed | None:
    """Warp the template onto the face at ``kps``; ``user_head`` (your own hair and skin,
    canonical, see :func:`user_head_map`) comes along unstretched."""
    h, w = frame_shape[:2]
    m_user = similarity(CANON_KPS, kps)
    stretch = width_fit(template, user_width)
    m = m_user.copy()   # stretch canonical x around the face's centre line, then place
    m[:, 0] *= stretch
    m[:, 2] += m_user[:, 0] * CANON_KPS[2, 0] * (1.0 - stretch)
    square = np.array([[0, 0, 1], [CANON, 0, 1], [0, CANON, 1], [CANON, CANON, 1]], np.float32)
    corners = np.vstack([square @ m.T, square @ m_user.T])
    x0, y0 = (int(max(0, np.floor(v))) for v in corners.min(axis=0))
    x1, y1 = int(min(w, np.ceil(corners[:, 0].max()))), int(min(h, np.ceil(corners[:, 1].max())))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    shifted = m.copy()
    shifted[:, 2] -= (x0, y0)
    size = (x1 - x0, y1 - y0)

    def warp(layer: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        return cv2.warpAffine(layer, matrix, size, flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    hair = warp(template.hair, shifted)
    head = warp(template.head, shifted)
    mine = skin = face = forehead = None
    if user_head is not None:
        unstretched = m_user.copy()
        unstretched[:, 2] -= (x0, y0)
        layers = warp(user_head, unstretched)   # linear interpolation keeps it in 0..1
        mine, skin, face, forehead = (layers[..., i] for i in range(4))
    scale = float(np.sqrt(abs(np.linalg.det(m_user[:, :2]))))
    cheeks = (np.c_[_CHEEKS, np.ones(2, np.float32)] @ m_user.T).astype(np.float32)
    return Placed(roi=(x0, y0, x1, y1), hair=np.ascontiguousarray(hair[..., :3]),
                  hair_alpha=hair[..., 3].astype(np.float32) * (1.0 / 255.0),
                  skin=np.ascontiguousarray(head[..., :3]),
                  head_alpha=head[..., 3].astype(np.float32) * (1.0 / 255.0), user_hair=mine,
                  user_skin=skin, user_face=face, forehead=forehead,
                  cheeks=cheeks, cheek_radius=_CHEEK_RADIUS * scale)


def live_skin(frame: np.ndarray, placed: Placed) -> np.ndarray:
    """The skin colour at your cheeks right now (BGR float32)."""
    return _cheek_mean(frame, placed.cheeks, placed.cheek_radius)
