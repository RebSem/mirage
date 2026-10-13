"""Background and hairstyle on a frame (mirage/scene.py), with synthetic pictures."""

import numpy as np

from mirage import hair
from mirage.scene import BLUR, IMAGE, NONE, Scene
from tests.mirage.test_hair import _fake_probs

H, W = 240, 320


def _frame_and_alpha() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)          # a busy room
    alpha = np.zeros((H, W), np.float32)
    alpha[60:, 110:210] = 1.0                                        # a person in the middle
    frame[60:, 110:210] = (90, 120, 200)
    return frame, alpha


def test_nothing_to_do_returns_the_frame_untouched() -> None:
    frame, alpha = _frame_and_alpha()
    scene = Scene()
    assert not scene.needs_matte
    assert scene.render(frame, frame, alpha, None) is frame
    scene.set_background(IMAGE, None)                 # an image background without a picture is none
    assert scene.background_kind == NONE


def test_image_background_replaces_the_room_only() -> None:
    frame, alpha = _frame_and_alpha()
    scene = Scene()
    scene.set_background(IMAGE, np.full((720, 1280, 3), (10, 200, 30), np.uint8))
    assert scene.needs_matte
    out = scene.render(frame, frame, alpha, None)
    assert out.shape == frame.shape and out.dtype == np.uint8
    assert (out[10, 10] == (10, 200, 30)).all()                      # the room is gone
    assert (out[150, 160] == (90, 120, 200)).all()                   # the person stays
    assert frame[10, 10].tolist() != [10, 200, 30]                   # the input is not modified


def test_blur_background_smooths_the_room() -> None:
    frame, alpha = _frame_and_alpha()
    scene = Scene()
    scene.set_background(BLUR)
    out = scene.render(frame, frame, alpha, None)
    assert out[:50, :100].std() < frame[:50, :100].std() / 4
    assert (out[150, 160] == (90, 120, 200)).all()


def test_no_matte_means_no_change() -> None:
    frame, _alpha = _frame_and_alpha()
    scene = Scene()
    scene.set_background(BLUR)
    assert scene.render(frame, frame, None, None) is frame


def _template() -> hair.HairTemplate:
    photo = np.full((600, 600, 3), 128, np.uint8)
    kps = (hair.CANON_KPS * 1.1 + np.array([20.0, 30.0], np.float32)).astype(np.float32)
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    template.hair[..., :3] = (20, 20, 220)            # unmistakably red hair
    return template


def test_hair_goes_on_the_head() -> None:
    frame = np.full((480, 640, 3), 200, np.uint8)
    alpha = np.zeros((480, 640), np.float32)
    kps = (hair.CANON_KPS * 0.6 + np.array([170.0, 60.0], np.float32)).astype(np.float32)
    scene = Scene()
    scene.set_hair(_template())
    assert scene.needs_matte
    out = scene.render(frame, frame, alpha, kps)
    top = (int(120 * 0.6 + 60), int(256 * 0.6 + 170))
    b, g, r = out[top].tolist()
    assert b < 40 and g < 40 and r > 180               # red hair (its brightness follows the room's light)
    assert (out[5, 5] == 200).all()                   # far from the head nothing changes


def test_your_own_hair_beyond_the_new_head_becomes_background() -> None:
    frame = np.full((480, 640, 3), 200, np.uint8)
    kps = (hair.CANON_KPS * 0.6 + np.array([170.0, 60.0], np.float32)).astype(np.float32)
    # your hair: a wide mane, far wider than the new head; you are all person
    probs = _fake_probs()
    yy, xx = np.mgrid[0:hair.CANON, 0:hair.CANON]
    mane = (np.abs(xx - 256) < 250) & (yy > 330) & (yy < 470) & (probs[hair.SKIN] < 0.5)
    probs[hair.HAIR][mane] = 1.0
    probs[hair.BACKGROUND][mane] = 0.0
    alpha = np.ones((480, 640), np.float32)
    frame[:, :] = (0, 0, 0)                           # your (black) hair everywhere
    scene = Scene()
    template = _template()
    template.hair[..., 3][350:] = 0                   # the new hairstyle is short
    template.head[..., 3][350:] = 0
    scene.set_hair(template)
    scene.set_background(IMAGE, np.full((720, 1280, 3), (0, 255, 0), np.uint8))
    scene.set_user_head(hair.user_head_map(probs), 190.0)
    out = scene.render(frame, frame, alpha, kps)
    side = (int(420 * 0.6 + 60), int(40 * 0.6 + 170))     # canonical (40, 420): mane, beyond the new head
    assert out[side].tolist() == [0, 255, 0]


def test_set_hair_forgets_the_last_faces_own_hair() -> None:
    scene = Scene()
    scene.set_user_head(np.zeros((hair.CANON, hair.CANON, 4), np.float32), 180.0)
    scene.set_hair(None)
    assert scene._user_head is None
