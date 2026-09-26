import numpy as np
import pytest

from modules import virtualcam_out


@pytest.mark.parametrize("shape", [(480, 640, 3), (360, 640, 3), (720, 1280, 3), (1080, 1920, 3), (641, 479, 3), (100, 100, 3)])
def test_fit_always_returns_output_size(shape):
    frame = np.zeros(shape, dtype=np.uint8)
    out = virtualcam_out._fit(frame)
    assert out.shape == (virtualcam_out.OUT_HEIGHT, virtualcam_out.OUT_WIDTH, 3)


def test_fit_keeps_center():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[200:280, 280:360] = 255  # bright square in the middle
    out = virtualcam_out._fit(frame)
    assert out[360, 640].mean() > 200
