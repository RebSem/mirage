"""The hairstyle maths (mirage/hair.py) with a fake face parser: no model needed."""

import numpy as np
import pytest

from mirage import hair

C = hair.CANON


def _fake_probs() -> np.ndarray:
    """Parser output for a canonical head: hair on top and down the sides, a face oval."""
    probs = np.zeros((19, C, C), np.float32)
    yy, xx = np.mgrid[0:C, 0:C].astype(np.float32)
    face = ((xx - 256) / 95) ** 2 + ((yy - 285) / 125) ** 2 < 1
    hair_region = (((xx - 256) / 150) ** 2 + ((yy - 240) / 190) ** 2 < 1) & ~face & (yy < 420)
    probs[hair.SKIN][face] = 1.0
    probs[hair.HAIR][hair_region] = 1.0
    probs[hair.BACKGROUND][~face & ~hair_region] = 1.0
    return probs


def _photo_and_kps() -> tuple[np.ndarray, np.ndarray]:
    """A 600×600 'photo' whose face points are the canonical ones moved and scaled."""
    kps = hair.CANON_KPS * 1.1 + np.array([20.0, 30.0], np.float32)
    photo = np.full((600, 600, 3), 128, np.uint8)
    return photo, kps.astype(np.float32)


def test_similarity_recovers_a_known_transform() -> None:
    angle, scale, shift = np.deg2rad(12), 0.8, np.array([30.0, -12.0])
    rot = scale * np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    dst = hair.CANON_KPS @ rot.T + shift
    m = hair.similarity(hair.CANON_KPS, dst)
    assert np.allclose(m[:, :2], rot, atol=1e-4) and np.allclose(m[:, 2], shift, atol=1e-3)


def test_to_canonical_puts_the_nose_where_it_belongs() -> None:
    photo, kps = _photo_and_kps()
    x, y = (int(round(v)) for v in kps[2])
    photo[y - 3:y + 4, x - 3:x + 4] = 255
    canon, valid = hair.to_canonical(photo, kps)
    assert canon.shape == (C, C, 3) and valid.shape == (C, C)
    nx, ny = (int(round(v)) for v in hair.CANON_KPS[2])
    assert canon[ny, nx].min() > 200
    assert valid[ny, nx] == pytest.approx(1.0)


def test_build_template_cuts_out_the_hair() -> None:
    photo, kps = _photo_and_kps()
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    assert template.hair.shape == (C, C, 4) and template.head.shape == (C, C, 4)
    hair_a, head_a = template.hair[..., 3], template.head[..., 3]
    assert hair_a[120, 256] > 200          # the top of the head is hair
    assert hair_a[285, 256] < 20           # the face is not
    assert hair_a[20, 20] < 20             # nor the wall
    assert head_a[285, 256] > 200 and head_a[120, 256] > 200
    assert template.has_hair
    assert template.face_width == pytest.approx(190, abs=12)
    assert template.skin_ref.shape == (3,)


def test_template_round_trip_and_forget(mirage_home) -> None:
    photo, kps = _photo_and_kps()
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    path = hair.template_path("abcdef012345")
    hair.save_template(template, path)
    loaded = hair.load_template(path)
    assert loaded is not None
    assert np.array_equal(loaded.hair, template.hair) and np.array_equal(loaded.head, template.head)
    assert loaded.face_width == pytest.approx(template.face_width)
    hair.forget("abcdef012345")
    assert not path.exists() and hair.load_template(path) is None


def test_a_damaged_template_is_ignored(mirage_home) -> None:
    path = hair.template_path("0123456789ab")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a template")
    assert hair.load_template(path) is None


def test_user_head_map_layers() -> None:
    head = hair.user_head_map(_fake_probs())
    assert head.shape == (C, C, 4) and head.dtype == np.float32
    assert head[120, 256, 0] > 0.9                      # hair
    assert head[300, 256, 1] > 0.9                      # bare skin
    assert head[300, 256, 2] > 0.9                      # face
    assert head[50, 256, 3] == 1.0 and head[400, 256, 3] == 0.0   # forehead band


def test_width_fit_is_clamped() -> None:
    photo, kps = _photo_and_kps()
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    assert hair.width_fit(template, None) == 1.0
    assert hair.width_fit(template, template.face_width) == pytest.approx(1.0)
    assert hair.width_fit(template, template.face_width * 3) == hair.WIDTH_FIT[1]
    assert hair.width_fit(template, template.face_width / 3) == hair.WIDTH_FIT[0]


def test_place_puts_the_hair_on_the_face_in_the_frame() -> None:
    photo, kps = _photo_and_kps()
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    frame_kps = (hair.CANON_KPS * 0.5 + np.array([200.0, 100.0], np.float32)).astype(np.float32)
    placed = hair.place(template, frame_kps, (480, 640, 3), hair.user_head_map(_fake_probs()), 190.0)
    assert placed is not None
    x0, y0, x1, y1 = placed.roi
    assert 0 <= x0 < x1 <= 640 and 0 <= y0 < y1 <= 480
    assert placed.hair.shape[:2] == placed.hair_alpha.shape == (y1 - y0, x1 - x0)
    top = (int(120 * 0.5 + 100) - y0, int(256 * 0.5 + 200) - x0)   # canonical (256, 120) in the frame
    assert placed.hair_alpha[top] > 0.8
    assert placed.user_hair is not None and placed.user_hair[top] > 0.8
    assert placed.cheeks.shape == (2, 2)


def test_place_off_frame_is_none() -> None:
    photo, kps = _photo_and_kps()
    template = hair.build_template(photo, kps, parse_fn=lambda _canon: _fake_probs())
    far = (hair.CANON_KPS + np.array([5000.0, 5000.0], np.float32)).astype(np.float32)
    assert hair.place(template, far, (480, 640, 3)) is None
