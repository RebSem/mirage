"""Matting and compositing helpers for virtual backgrounds and hair (numpy + OpenCV only).

Everything here is pure image math, so it is unit-tested without models or a
camera. The person mask itself comes from ``mirage.matte`` (Apple Vision);
this module turns it into a clean, steady matte and puts the person in front
of a new background without the old background's colour around the edges.
"""

from __future__ import annotations

import cv2
import numpy as np

FILL_SCALE = 4            # the "what is behind you" estimate is made at 1/4 size
BLUR_SIGMA = 10.0         # background blur, in pixels of the 1/4-size image
TEMPORAL_KEEP = 0.45      # share of the previous matte kept where the matte barely changed
TEMPORAL_CHANGE = 0.18    # a change bigger than this is real movement: no smoothing there


def guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float, subsample: int = 1) -> np.ndarray:
    """He et al.'s (fast) guided filter with a grey guide; float32 in, float32 out.

    Snaps a soft, low-resolution mask to the edges of the camera picture:
    hair strands and shoulders get crisp, flat areas stay smooth.
    """
    h, w = src.shape[:2]
    guide = guide.astype(np.float32, copy=False)
    src = src.astype(np.float32, copy=False)
    if subsample > 1:
        size = (max(1, w // subsample), max(1, h // subsample))
        g = cv2.resize(guide, size, interpolation=cv2.INTER_AREA)
        p = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
        r = max(1, radius // subsample)
    else:
        g, p, r = guide, src, radius
    k = (2 * r + 1, 2 * r + 1)

    def box(x: np.ndarray) -> np.ndarray:
        return cv2.boxFilter(x, -1, k, borderType=cv2.BORDER_REFLECT)

    mean_g, mean_p = box(g), box(p)
    var_g = box(g * g) - mean_g * mean_g
    cov = box(g * p) - mean_g * mean_p
    a = cov / (var_g + eps)
    b = mean_p - a * mean_g
    mean_a, mean_b = box(a), box(b)
    if subsample > 1:
        mean_a = cv2.resize(mean_a, (w, h), interpolation=cv2.INTER_LINEAR)
        mean_b = cv2.resize(mean_b, (w, h), interpolation=cv2.INTER_LINEAR)
    return mean_a * guide + mean_b


def fill_holes(image: np.ndarray, weight: np.ndarray, levels: int = 8) -> np.ndarray:
    """Push-pull fill: where ``weight`` is ~0, guess the colour from the surroundings.

    ``image`` is H×W×C (any dtype), ``weight`` H×W in 0..1 (1 = trust this pixel).
    Returns float32. Used to estimate the wall behind the person (for the
    background blur and for clean edges) and to extend hair colours outwards.
    """
    img = image.astype(np.float32)
    if img.ndim == 2:
        img = img[..., None]
    w = np.clip(weight.astype(np.float32), 0.0, 1.0)
    pyramid = []
    cur_i, cur_w = img * w[..., None], w
    for _ in range(levels):
        if min(cur_w.shape[:2]) < 4:
            break
        pyramid.append((cur_i, cur_w))
        cur_i = cv2.pyrDown(cur_i)
        cur_w = cv2.pyrDown(cur_w)
        if cur_i.ndim == 2:
            cur_i = cur_i[..., None]
    total = float(cur_w.sum())
    if total < 1e-6:  # nothing to trust at all: the mean of what there is (or black)
        mean = (img * w[..., None]).sum(axis=(0, 1)) / max(float(w.sum()), 1e-6)
        est = np.broadcast_to(mean, cur_i.shape).astype(np.float32)
    else:
        est = cur_i / np.maximum(cur_w, 1e-6)[..., None]
        empty = cur_w < 1e-4
        if empty.any():
            est[empty] = cur_i.sum(axis=(0, 1)) / total
    for ci, cw in reversed(pyramid):
        up = cv2.pyrUp(est, dstsize=(cw.shape[1], cw.shape[0]))
        if up.ndim == 2:
            up = up[..., None]
        local = ci / np.maximum(cw, 1e-6)[..., None]
        trust = np.clip(cw * 4.0, 0.0, 1.0)[..., None]
        est = local * trust + up * (1.0 - trust)
    return est if image.ndim == 3 else est[..., 0]


def clean_mask(raw: np.ndarray) -> np.ndarray:
    """Vision's raw person mask (uint8) → float32 0..1 without its faint noise.

    In dark or busy parts of a room Vision leaves weak, blotchy values (up to
    a third of "person") and the odd stray blob; through those the real room
    would shimmer behind the background. Weak values go to zero and pieces much
    smaller than the people in view are dropped.
    """
    m = raw.astype(np.float32) * (1.0 / 255.0)
    m = np.clip((m - 0.25) * 2.0, 0.0, 1.0)
    m = m * m * (3.0 - 2.0 * m)
    solid = (m > 0.5).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    if count > 2:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = areas >= max(float(areas.max()) * 0.15, solid.size * 0.004)
        lut = np.zeros(count, np.uint8)
        lut[1:][keep] = 1
        kept = cv2.dilate(lut[labels], np.ones((9, 9), np.uint8))  # keep their soft edges too
        m *= kept
    return m


def refine_matte(raw: np.ndarray, frame: np.ndarray, previous: np.ndarray | None = None,
                 radius: int = 8, eps: float = 2e-3) -> np.ndarray:
    """Vision's person mask (uint8, any size) → a clean, steady float32 matte at frame size."""
    h, w = frame.shape[:2]
    mask = clean_mask(raw)
    if mask.shape[:2] != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) * (1.0 / 255.0)
    alpha = guided_filter(grey, mask, radius, eps, subsample=2)
    # Firm up the inside and the outside, keep a soft edge in between.
    alpha = np.clip((alpha - 0.12) * (1.0 / 0.76), 0.0, 1.0)
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
    if previous is not None and previous.shape == alpha.shape:
        # Calm the shimmer of a still person; real movement passes straight through.
        still = np.abs(alpha - previous) < TEMPORAL_CHANGE
        alpha = np.where(still, alpha * (1.0 - TEMPORAL_KEEP) + previous * TEMPORAL_KEEP, alpha)
    return alpha.astype(np.float32, copy=False)


def behind_person(frame: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """A soft guess of the room behind the person (float32, frame size), from the
    pixels around them. Good enough to fill small holes and to clean edges."""
    h, w = frame.shape[:2]
    size = (max(8, w // FILL_SCALE), max(8, h // FILL_SCALE))
    small = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    a = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
    # Trust only clearly-background pixels; the edge of the person is not the wall.
    trust = np.clip(1.0 - a * 1.6, 0.0, 1.0)
    trust = cv2.erode(trust, np.ones((3, 3), np.uint8))
    filled = fill_holes(small, trust)
    filled = cv2.GaussianBlur(filled, (0, 0), 1.2)
    return cv2.resize(filled, (w, h), interpolation=cv2.INTER_LINEAR)


def blurred_background(behind: np.ndarray, sigma: float = BLUR_SIGMA) -> np.ndarray:
    """Strong, smooth blur of the room with the person already taken out (no halo)."""
    h, w = behind.shape[:2]
    size = (max(8, w // FILL_SCALE), max(8, h // FILL_SCALE))
    small = cv2.resize(behind, size, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def cover(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Scale and centre-crop ``image`` to fill width×height (like CSS background-size: cover)."""
    h, w = image.shape[:2]
    scale = max(width / w, height / h)
    nw, nh = max(width, round(w * scale)), max(height, round(h * scale))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (nw, nh), interpolation=interp)
    x, y = (nw - width) // 2, (nh - height) // 2
    return np.ascontiguousarray(resized[y:y + height, x:x + width])


def composite(fg: np.ndarray, alpha: np.ndarray, background: np.ndarray,
              behind: np.ndarray | None = None) -> np.ndarray:
    """Put ``fg`` (uint8 BGR) over ``background`` (uint8 BGR) with ``alpha`` (float32 0..1).

    With ``behind`` (the old room, see :func:`behind_person`) the soft edge is
    decontaminated first: the old wall's colour is taken out of the hair and
    shoulders, so a green wall doesn't leave a green rim on a beach. Only
    where the person is fairly opaque: in the faint outer edge the guess of
    the wall is too rough, and unmixing there would draw the old room back in.
    """
    if behind is not None:
        band = (alpha > 0.15) & (alpha < 0.985)   # only the edge needs it: cheap
        if band.any():
            a = alpha[band][:, None]
            f = fg[band].astype(np.float32)
            t = np.clip((a - 0.15) * (1.0 / 0.45), 0.0, 1.0)
            edge = (1.0 - a) / np.maximum(a, 0.3) * (t * t * (3.0 - 2.0 * t))
            fg = fg.copy()
            fg[band] = np.clip(f + edge * (f - behind[band]), 0.0, 255.0).astype(np.uint8)
    if background.dtype != np.uint8:
        background = np.clip(background, 0, 255).astype(np.uint8)
    return cv2.blendLinear(fg, background, alpha, 1.0 - alpha)


def blend(base: np.ndarray, layer: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """``base`` (uint8) with ``layer`` laid over it through ``alpha`` (float32 0..1); uint8 out."""
    if layer.dtype != np.uint8:
        layer = np.clip(layer, 0, 255).astype(np.uint8)
    alpha = np.ascontiguousarray(alpha, dtype=np.float32)
    return cv2.blendLinear(np.ascontiguousarray(base), np.ascontiguousarray(layer), 1.0 - alpha, alpha)
