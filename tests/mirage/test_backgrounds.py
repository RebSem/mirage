"""Built-in backgrounds, background choices and the library of your own pictures."""

import json

import cv2
import numpy as np
import pytest

from mirage import backgrounds
from mirage.library import UnreadableImageError


@pytest.mark.parametrize("name", backgrounds.PRESET_NAMES)
def test_presets_paint_at_any_size(name: str) -> None:
    image = backgrounds.render_preset(name, 320, 180)
    assert image.shape == (180, 320, 3) and image.dtype == np.uint8
    assert image.std() > 1.0                                  # not a flat colour
    assert np.array_equal(image, backgrounds.render_preset(name, 320, 180))   # the same every time


def test_unknown_preset() -> None:
    with pytest.raises(KeyError):
        backgrounds.render_preset("disco")


def test_parse_and_validate_choices() -> None:
    assert backgrounds.parse("none") == ("none", "")
    assert backgrounds.parse("blur") == ("blur", "")
    assert backgrounds.parse("preset:aurora") == ("preset", "aurora")
    assert backgrounds.parse("image:0123456789ab") == ("image", "0123456789ab")
    for odd in (None, "", "preset:", "sepia", 5):
        assert backgrounds.parse(odd) == ("none", "")
    assert backgrounds.is_valid("preset:studio") and backgrounds.is_valid("image:0123456789ab")
    for bad in ("preset:disco", "image:../../x", "image:ABC", "image:0123456789abc", "sepia"):
        assert not backgrounds.is_valid(bad)


def _picture(w: int = 300, h: int = 200) -> np.ndarray:
    image = np.zeros((h, w, 3), np.uint8)
    image[:, : w // 2] = (30, 160, 220)
    return image


def test_library_add_list_load_remove(tmp_path) -> None:
    lib = backgrounds.BackgroundLibrary(tmp_path / "bg")
    entry = lib.add_image(_picture(), "Beach")
    assert len(entry.id) == 12 and lib.get(entry.id) == entry
    assert [e.name for e in lib.list()] == ["Beach"]
    loaded = lib.load(entry.id)
    assert loaded is not None and loaded.shape == (200, 300, 3)
    again = backgrounds.BackgroundLibrary(tmp_path / "bg")      # survives a restart
    assert [e.id for e in again.list()] == [entry.id]
    again.remove(entry.id)
    assert again.list() == [] and not again.path(entry.id).exists()
    assert backgrounds.BackgroundLibrary(tmp_path / "bg").list() == []


def test_library_shrinks_huge_pictures(tmp_path) -> None:
    lib = backgrounds.BackgroundLibrary(tmp_path / "bg")
    entry = lib.add_image(_picture(4000, 1000), "Wide")
    assert max(lib.load(entry.id).shape[:2]) == backgrounds.MAX_SIDE


def test_library_add_file_and_unreadable(tmp_path) -> None:
    good = tmp_path / "my_office-2.png"
    cv2.imwrite(str(good), _picture())
    lib = backgrounds.BackgroundLibrary(tmp_path / "bg")
    assert lib.add_file(good).name == "my office 2"
    bad = tmp_path / "notes.png"
    bad.write_text("not a picture")
    with pytest.raises(UnreadableImageError):
        lib.add_file(bad)


def test_library_survives_a_damaged_index(tmp_path) -> None:
    lib = backgrounds.BackgroundLibrary(tmp_path / "bg")
    entry = lib.add_image(_picture(), "Kept")
    (tmp_path / "bg" / "index.json").write_text("{ broken", encoding="utf-8")
    rebuilt = backgrounds.BackgroundLibrary(tmp_path / "bg")
    assert [e.id for e in rebuilt.list()] == [entry.id]        # the picture comes back


def test_library_drops_entries_whose_picture_is_gone(tmp_path) -> None:
    root = tmp_path / "bg"
    root.mkdir()
    (root / "index.json").write_text(json.dumps(
        {"version": 1, "backgrounds": [{"id": "0123456789ab", "name": "Gone", "created": 1.0}]}), encoding="utf-8")
    assert backgrounds.BackgroundLibrary(root).list() == []


def test_load_choice(tmp_path) -> None:
    lib = backgrounds.BackgroundLibrary(tmp_path / "bg")
    entry = lib.add_image(_picture(), "Mine")
    assert backgrounds.load_choice("preset:lagoon", lib, (64, 36)).shape == (36, 64, 3)
    assert backgrounds.load_choice("image:" + entry.id, lib).shape == (200, 300, 3)
    assert backgrounds.load_choice("image:0123456789ab", lib) is None
    assert backgrounds.load_choice("blur", lib) is None and backgrounds.load_choice("none", lib) is None
