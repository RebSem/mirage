"""Matting and compositing maths for virtual backgrounds (mirage/compose.py)."""

import numpy as np

from mirage import compose


def _person(h: int = 240, w: int = 320) -> np.ndarray:
    """A head-and-shoulders blob: 1 inside, 0 outside (float32)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    head = ((xx - w / 2) / (w * 0.14)) ** 2 + ((yy - h * 0.4) / (h * 0.2)) ** 2 < 1
    body = (np.abs(xx - w / 2) < w * 0.3) & (yy > h * 0.65)
    return (head | body).astype(np.float32)


def test_guided_filter_keeps_flat_input_flat() -> None:
    guide = np.random.default_rng(0).random((60, 80)).astype(np.float32)
    flat = np.full((60, 80), 0.7, np.float32)
    out = compose.guided_filter(guide, flat, 4, 1e-3, subsample=2)
    assert out.shape == flat.shape and out.dtype == np.float32
    assert np.allclose(out, 0.7, atol=1e-3)


def test_fill_holes_fills_from_the_surroundings() -> None:
    image = np.zeros((64, 96, 3), np.uint8)
    image[:] = (20, 40, 200)
    image[20:44, 30:66] = 0                      # a hole of black
    weight = np.ones((64, 96), np.float32)
    weight[20:44, 30:66] = 0
    filled = compose.fill_holes(image, weight)
    assert filled.shape == (64, 96, 3) and filled.dtype == np.float32
    assert np.allclose(filled[32, 48], (20, 40, 200), atol=2)


def test_fill_holes_with_nothing_to_trust_does_not_produce_nan() -> None:
    filled = compose.fill_holes(np.full((20, 30, 3), 9, np.uint8), np.zeros((20, 30), np.float32))
    assert np.isfinite(filled).all()


def test_clean_mask_drops_faint_noise_and_stray_blobs() -> None:
    raw = np.zeros((96, 128), np.uint8)
    raw[20:90, 40:90] = 255                     # the person
    raw[5:9, 5:9] = 255                         # a stray speck
    raw[60:90, 0:30] = 70                       # faint blotches in a dark corner
    m = compose.clean_mask(raw)
    assert m[50, 60] == 1.0
    assert m[7, 7] == 0.0 and m[75, 15] == 0.0


def test_clean_mask_keeps_two_people() -> None:
    raw = np.zeros((96, 128), np.uint8)
    raw[20:90, 10:50] = 255
    raw[25:90, 75:115] = 255
    m = compose.clean_mask(raw)
    assert m[50, 30] == 1.0 and m[50, 95] == 1.0


def test_refine_matte_is_frame_sized_and_in_range() -> None:
    frame = np.zeros((240, 320, 3), np.uint8)
    person = _person()
    frame[person > 0] = (200, 180, 160)
    raw = (person * 255).astype(np.uint8)[::2, ::2]   # Vision's mask is smaller than the frame
    alpha = compose.refine_matte(raw, frame)
    assert alpha.shape == (240, 320) and alpha.dtype == np.float32
    assert 0.0 <= alpha.min() and alpha.max() <= 1.0
    assert alpha[100, 160] > 0.95 and alpha[20, 20] < 0.05
    steady = compose.refine_matte(raw, frame, previous=alpha)
    assert np.abs(steady - alpha).max() < 0.05


def test_composite_puts_person_over_background() -> None:
    fg = np.full((10, 10, 3), 200, np.uint8)
    bg = np.full((10, 10, 3), 10, np.uint8)
    alpha = np.zeros((10, 10), np.float32)
    alpha[:, 5:] = 1.0
    out = compose.composite(fg, alpha, bg)
    assert (out[:, :5] == 10).all() and (out[:, 5:] == 200).all()


def test_composite_takes_the_old_wall_out_of_the_edge() -> None:
    wall, person, beach = np.array((0, 200, 0), np.float32), np.array((0, 0, 200), np.float32), (200, 200, 0)
    a = 0.6
    edge_pixel = (person * a + wall * (1 - a)).astype(np.uint8)
    fg = np.tile(edge_pixel, (4, 4, 1))
    alpha = np.full((4, 4), a, np.float32)
    background = np.tile(np.array(beach, np.uint8), (4, 4, 1))
    plain = compose.composite(fg, alpha, background)
    clean = compose.composite(fg, alpha, background, behind=np.tile(wall, (4, 4, 1)))
    assert clean[0, 0, 1] < plain[0, 0, 1] - 20          # less of the green wall
    assert np.abs(clean[0, 0].astype(int) - (person * a + np.array(beach) * (1 - a))).max() <= 3


def test_cover_fills_exactly_and_keeps_the_middle() -> None:
    image = np.zeros((100, 400, 3), np.uint8)
    image[:, 190:210] = 255                      # a stripe in the middle
    out = compose.cover(image, 64, 48)
    assert out.shape == (48, 64, 3)
    assert out[24, 32].max() > 200 and out[24, 2].max() == 0


def test_behind_person_and_blur_are_frame_sized() -> None:
    frame = np.full((120, 160, 3), 90, np.uint8)
    alpha = _person(120, 160)
    behind = compose.behind_person(frame, alpha)
    assert behind.shape == (120, 160, 3)
    assert np.allclose(behind[60, 80], 90, atol=3)       # the wall behind the person is guessed
    assert compose.blurred_background(behind).shape == (120, 160, 3)


def test_blend() -> None:
    base = np.zeros((4, 4, 3), np.uint8)
    layer = np.full((4, 4, 3), 100.0, np.float32)
    alpha = np.full((4, 4), 0.5, np.float32)
    assert (compose.blend(base, layer, alpha) == 50).all()
