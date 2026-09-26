import numpy as np

from mirage.tracking import FaceSmoother


def _face(x, y, w=100):
    bbox = np.array([x, y, x + w, y + w], dtype=np.float32)
    kps = np.array([[x + 30, y + 40], [x + 70, y + 40], [x + 50, y + 60], [x + 35, y + 80], [x + 65, y + 80]], dtype=np.float32)
    return bbox, kps


def test_first_update_passes_through():
    s = FaceSmoother()
    bbox, kps = _face(10, 20)
    out_b, out_k = s.update(bbox, kps)
    assert np.allclose(out_b, bbox) and np.allclose(out_k, kps)


def test_small_jitter_is_damped():
    s = FaceSmoother(alpha=0.5)
    s.update(*_face(100, 100))
    out_b, _ = s.update(*_face(104, 100))
    assert 100 < out_b[0] < 104


def test_big_jump_resets():
    s = FaceSmoother(alpha=0.5, reset_ratio=0.35)
    s.update(*_face(100, 100))
    out_b, _ = s.update(*_face(300, 100))
    assert out_b[0] == 300


def test_reset_forgets_history():
    s = FaceSmoother(alpha=0.5)
    s.update(*_face(100, 100))
    s.reset()
    out_b, _ = s.update(*_face(110, 100))
    assert out_b[0] == 110
