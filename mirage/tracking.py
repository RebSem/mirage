"""Landmark smoothing between detections (pure numpy, unit-tested).

Detections jitter by a few pixels from frame to frame, which makes the
swapped face shimmer. An exponential moving average over the box and the five
keypoints steadies it; a large jump (fast head turn, different person)
resets the filter so the face never lags behind.
"""

from __future__ import annotations

import numpy as np


class FaceSmoother:
    def __init__(self, alpha: float = 0.6, reset_ratio: float = 0.35):
        self.alpha = alpha            # weight of the new detection
        self.reset_ratio = reset_ratio  # jump, as a fraction of face width, that resets
        self._bbox: np.ndarray | None = None
        self._kps: np.ndarray | None = None

    def reset(self) -> None:
        self._bbox = None
        self._kps = None

    def update(self, bbox: np.ndarray, kps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bbox = np.asarray(bbox, dtype=np.float32)[:4]
        kps = np.asarray(kps, dtype=np.float32)
        if self._bbox is None or self._kps is None or self._kps.shape != kps.shape:
            self._bbox, self._kps = bbox.copy(), kps.copy()
            return self._bbox.copy(), self._kps.copy()
        width = max(float(bbox[2] - bbox[0]), 1.0)
        jump = float(np.linalg.norm(_center(bbox) - _center(self._bbox)))
        if jump > self.reset_ratio * width:
            self._bbox, self._kps = bbox.copy(), kps.copy()
        else:
            a = self.alpha
            self._bbox = a * bbox + (1 - a) * self._bbox
            self._kps = a * kps + (1 - a) * self._kps
        return self._bbox.copy(), self._kps.copy()


def _center(bbox: np.ndarray) -> np.ndarray:
    return np.array([(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], dtype=np.float32)
