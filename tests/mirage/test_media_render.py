import numpy as np

from mirage.media.render import _blend_face, _face_alpha


def test_face_alpha_is_a_soft_ellipse():
    a = _face_alpha(256)
    assert a[140, 128] > 0.99          # inside the face
    assert a[5, 5] < 0.01              # corner (hair/background) untouched
    assert 0.0 < a[140, 128 + 110] < 1.0 or a[140, 128 + 110] < 0.5


def test_blend_touches_only_the_face_region():
    frame = np.full((400, 600, 3), 50, np.uint8)
    face = np.full((256, 256, 3), 200, np.uint8)
    # identity-like transform: aligned square maps to x 200..328, y 100..228 (scale 0.5)
    matrix = np.array([[2.0, 0, -400.0], [0, 2.0, -200.0]])
    out = _blend_face(frame.copy(), face, matrix)
    assert out[164, 264].mean() > 180                     # centre of the face got the new pixels
    assert (out[:90] == 50).all() and (out[:, :190] == 50).all()   # outside the region: exactly as before
    assert out[102, 202].mean() < 60                      # square corner: outside the ellipse
