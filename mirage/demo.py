"""A fake camera for demos, screenshots and testing without a webcam.

``python -m mirage --demo face.jpg`` adds a "Demo" camera that shows that
photo drifting gently over a soft background at 30 fps.
"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

WIDTH, HEIGHT, FPS = 640, 480, 30.0


class DemoCapturer:
    """Same surface as modules.video_capture.VideoCapturer (start/read/release)."""

    def __init__(self, image_path: str):
        self.image_path = image_path
        self.actual_width, self.actual_height, self.actual_fps = WIDTH, HEIGHT, FPS
        self._face: np.ndarray | None = None
        self._background: np.ndarray | None = None
        self._t0 = 0.0
        self._next = 0.0

    def start(self, width: int = WIDTH, height: int = HEIGHT, fps: float = FPS) -> bool:
        data = np.fromfile(self.image_path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        if image is None:
            return False
        side = int(HEIGHT * 0.62)
        self._face = cv2.resize(image, (side, side), interpolation=cv2.INTER_AREA)
        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
        glow = np.exp(-(((xx - WIDTH * 0.7) / 260) ** 2 + ((yy - HEIGHT * 0.2) / 200) ** 2))[..., None]
        base = np.array([48, 40, 36], np.float32) + glow * np.array([70, 90, 120], np.float32)
        self._background = np.clip(base, 0, 255).astype(np.uint8)
        self._t0 = self._next = time.monotonic()
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._face is None or self._background is None:
            return False, None
        now = time.monotonic()
        if self._next > now:
            time.sleep(self._next - now)
        self._next = max(self._next + 1 / FPS, time.monotonic())
        t = time.monotonic() - self._t0
        frame = self._background.copy()
        scale = 1.0 + 0.03 * math.sin(t * 0.9)
        side = int(self._face.shape[0] * scale)
        face = cv2.resize(self._face, (side, side))
        cx = WIDTH / 2 + 34 * math.sin(t * 0.6)
        cy = HEIGHT / 2 + 12 * math.sin(t * 0.9 + 1.0)
        x, y = int(cx - side / 2), int(cy - side / 2)
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + side, WIDTH), min(y + side, HEIGHT)
        frame[y0:y1, x0:x1] = face[y0 - y:y1 - y, x0 - x:x1 - x]
        return True, frame

    def release(self) -> None:
        self._face = None
