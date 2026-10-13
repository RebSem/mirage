"""What goes around the face: the virtual background and the hairstyle, per frame.

The live engine owns one ``Scene``. The UI thread changes it (``set_background``,
``set_hair``), the hair thread feeds it your own head map, and the process
thread calls :meth:`Scene.render` with the camera frame, the swapped frame and
the person matte. Every setter swaps whole objects, so the process thread
always sees either the old setting or the new one, never half of each.
"""

from __future__ import annotations

import threading

import cv2
import numpy as np

from mirage import compose, hair

NONE, BLUR, IMAGE = "none", "blur", "image"
SKIN_MATCH = 0.85        # without a map of your skin: how far the photo's skin moves to your colour
HAIR_GAIN_RANGE = (0.72, 1.22)


def _firm(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) * (1.0 / (hi - lo)), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class Scene:
    def __init__(self) -> None:
        self._background: tuple[str, np.ndarray | None] = (NONE, None)
        self._fitted: tuple[tuple[int, int], np.ndarray] | None = None   # background cut to frame size
        self._hair: hair.HairTemplate | None = None
        self._user_head: tuple[np.ndarray, float | None] | None = None   # canonical map, face width
        self._gain = 1.0
        self._lock = threading.Lock()

    # ── settings (any thread) ────────────────────────────────────────────

    def set_background(self, kind: str, image: np.ndarray | None = None) -> None:
        if kind == IMAGE and image is None:
            kind = NONE
        with self._lock:
            self._background = (kind if kind in (NONE, BLUR, IMAGE) else NONE, image)
            self._fitted = None

    @property
    def background_kind(self) -> str:
        return self._background[0]

    def set_hair(self, template: hair.HairTemplate | None) -> None:
        self._hair = template
        self._user_head = None   # the next face's own hair must be found again
        self._gain = 1.0

    @property
    def hair_template(self) -> hair.HairTemplate | None:
        return self._hair

    def set_user_head(self, canonical: np.ndarray | None, face_width: float | None = None) -> None:
        """Your own hair and skin (canonical, from the hair thread) and your face width there."""
        self._user_head = None if canonical is None else (canonical, face_width)

    @property
    def needs_matte(self) -> bool:
        return self._background[0] != NONE or self._hair is not None

    # ── per frame (process thread) ───────────────────────────────────────

    def _fitted_background(self, shape: tuple[int, ...]) -> np.ndarray | None:
        kind, image = self._background
        if kind != IMAGE or image is None:
            return None
        size = (shape[1], shape[0])
        with self._lock:
            fitted = self._fitted
            if fitted is None or fitted[0] != size:
                fitted = (size, compose.cover(image, *size))
                self._fitted = fitted
        return fitted[1]

    def render(self, frame: np.ndarray, out: np.ndarray, alpha: np.ndarray | None,
               kps: np.ndarray | None) -> np.ndarray:
        """``frame``: the camera picture, ``out``: after the face swap (both uint8 BGR),
        ``alpha``: the person matte (float32, frame size) or None, ``kps``: the five
        points of the swapped face, or None."""
        kind = self._background[0]
        template = self._hair
        if alpha is None or (kind == NONE and template is None):
            return out
        alpha = alpha.copy()
        out = out.copy()
        behind = compose.behind_person(frame, alpha)

        placed = None
        if template is not None and kps is not None:
            head, width = self._user_head or (None, None)
            placed = hair.place(template, kps, frame.shape, head, width)
        if placed is not None and placed.user_hair is not None:
            self._take_off_own_hair(out, alpha, behind, placed, template, kind)

        if kind == BLUR:
            out = compose.composite(out, alpha, compose.blurred_background(behind), behind)
        elif kind == IMAGE:
            background = self._fitted_background(frame.shape)
            if background is not None:
                out = compose.composite(out, alpha, background, behind)

        if placed is not None and placed.hair_alpha.max() > 0.02:
            x0, y0, x1, y1 = placed.roi
            # Match the hair's brightness to the room's light, gently and steadily.
            live = float(hair.live_skin(out, placed).mean())
            ref = float(template.skin_ref.mean())
            target = float(np.clip(np.sqrt((live + 8.0) / (ref + 8.0)), *HAIR_GAIN_RANGE))
            self._gain += (target - self._gain) * 0.15
            layer = placed.hair if abs(self._gain - 1.0) < 0.01 else cv2.convertScaleAbs(placed.hair, alpha=self._gain)
            out[y0:y1, x0:x1] = compose.blend(out[y0:y1, x0:x1], layer, placed.hair_alpha)
        return out

    def _take_off_own_hair(self, out: np.ndarray, alpha: np.ndarray, behind: np.ndarray,
                           placed: hair.Placed, template: hair.HairTemplate, kind: str) -> None:
        """Your hair, where the new hairstyle doesn't cover it (in place, inside the ROI):

        * above your eyebrows, inside the new head: bare skin (a forehead, a
          shorter cut), painted from your own skin;
        * above your eyebrows, beyond the new head: the background;
        * below your eyebrows: the background, except over your face and ears,
          where it stays (temples and cheeks can't be painted convincingly).
        """
        x0, y0, x1, y1 = placed.roi
        roi = out[y0:y1, x0:x1]
        person = np.clip(alpha[y0:y1, x0:x1] * 3.0, 0.0, 1.0)  # a hint of you is enough: hair is soft
        loose = placed.user_hair * person * (1.0 - placed.hair_alpha)
        top = placed.forehead
        remove = _firm(loose * (top * (1.0 - placed.head_alpha) + (1.0 - top) * (1.0 - placed.user_face)), 0.15, 0.55)
        reskin = _firm(loose * top * placed.head_alpha, 0.15, 0.55)
        if reskin.max() > 0.02:
            out[y0:y1, x0:x1] = roi = compose.blend(roi, self._skin(roi, placed, template), reskin)
        if kind == NONE:   # no virtual background: show the room that is behind your hair
            out[y0:y1, x0:x1] = compose.blend(roi, behind[y0:y1, x0:x1], remove)
        alpha[y0:y1, x0:x1] *= 1.0 - remove

    def _skin(self, roi: np.ndarray, placed: hair.Placed, template: hair.HairTemplate) -> np.ndarray:
        """Skin for the places your hair used to cover: your own visible skin, spread
        smoothly over them (so colour and light match), or the photo's skin
        moved to your colour when yours can't be seen."""
        bare = placed.user_skin
        if bare is not None and float(bare.sum()) > 200.0:
            h, w = roi.shape[:2]
            size = (max(8, w // 4), max(8, h // 4))
            small = cv2.resize(roi, size, interpolation=cv2.INTER_AREA)
            weight = cv2.resize(bare, size, interpolation=cv2.INTER_AREA)
            filled = compose.fill_holes(small, _firm(weight, 0.3, 0.8))
            filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_LINEAR)
            # A smooth fill looks like plastic next to real skin: give it the grain
            # your own skin has in this picture.
            grey = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            detail = grey - cv2.GaussianBlur(grey, (0, 0), 1.5)
            sure = bare > 0.7
            if int(sure.sum()) > 50:
                grain = float(detail[sure].std())
                filled += (_grain(h, w) * min(grain, 6.0))[..., None]
            return filled
        delta = hair.live_skin(roi, _shifted(placed)) - template.skin_ref
        return placed.skin.astype(np.float32) + delta * SKIN_MATCH


_GRAIN: np.ndarray | None = None


def _grain(h: int, w: int) -> np.ndarray:
    """Fixed fine noise with unit spread (fixed, so it doesn't crawl from frame to frame)."""
    global _GRAIN
    if _GRAIN is None or _GRAIN.shape[0] < h or _GRAIN.shape[1] < w:
        rng = np.random.default_rng(7)
        noise = cv2.GaussianBlur(rng.standard_normal((max(h, 720), max(w, 1280))).astype(np.float32), (0, 0), 0.7)
        _GRAIN = noise / max(float(noise.std()), 1e-6)
    return _GRAIN[:h, :w]


def _shifted(placed: hair.Placed) -> hair.Placed:
    """``placed`` with its cheek points relative to its own ROI."""
    from dataclasses import replace

    return replace(placed, cheeks=placed.cheeks - np.array(placed.roi[:2], np.float32))
