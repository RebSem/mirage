import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from mirage import paths, settings
from mirage.settings import Settings


def test_defaults_match_contract() -> None:
    assert asdict(Settings()) == {
        "camera_uid": None,
        "face_id": None,
        "quality": "balanced",
        "opacity": 1.0,
        "sharpness": 0.0,
        "mouth_mask": False,
        "many_faces": False,
        "color_fix": False,
        "poisson_blend": False,
        "mirror_preview": True,
        "show_fps": False,
        "language": "auto",
        "onboarding_done": False,
        "window_geometry": None,
        "mode": "live",
        "me_face_id": None,
        "photo_enhance": True,
        "video_enhance": False,
    }


def test_mode_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"mode": "MEDIA", "me_face_id": "abc", "video_enhance": "yes"}', encoding="utf-8")
    loaded = settings.load(path)
    assert loaded.mode == "media" and loaded.me_face_id == "abc" and loaded.video_enhance is False
    path.write_text('{"mode": "cinema"}', encoding="utf-8")
    assert settings.load(path).mode == "live"


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert settings.load(tmp_path / "nope.json") == Settings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(
        camera_uid="0x1420000005ac8600",
        face_id="0123456789ab",
        quality="best",
        opacity=0.35,
        sharpness=0.5,
        mouth_mask=True,
        many_faces=True,
        color_fix=True,
        poisson_blend=True,
        mirror_preview=False,
        show_fps=True,
        language="ru",
        onboarding_done=True,
        window_geometry="AdnQywADAAAAAAB4AAAAlg==",
    )
    settings.save(original, path)
    assert settings.load(path) == original
    assert json.loads(path.read_text(encoding="utf-8"))["quality"] == "best"


def test_default_path_is_under_mirage_home(mirage_home: Path) -> None:
    settings.save(Settings(show_fps=True))
    assert paths.settings_path() == mirage_home / "settings.json"
    assert (mirage_home / "settings.json").is_file()
    assert settings.load().show_fps is True


@pytest.mark.parametrize(
    "content",
    ["", "{not json", "[1, 2, 3]", '"just a string"', "null", b"\xff\xfe\x00garbage"],
)
def test_corrupt_file_gives_defaults(
    tmp_path: Path, content: str | bytes, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "settings.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert settings.load(path) == Settings()
    assert caplog.records


def test_bad_types_reset_only_that_field(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "camera_uid": 42,
                "face_id": "",
                "quality": 3,
                "opacity": "high",
                "sharpness": True,
                "mouth_mask": "yes",
                "many_faces": 1,
                "mirror_preview": None,
                "language": ["en"],
                "window_geometry": {"x": 1},
                "show_fps": True,  # valid, must survive
                "unknown_key": "ignored",
            }
        ),
        encoding="utf-8",
    )
    assert settings.load(path) == Settings(show_fps=True)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(-0.5, 0.0), (1.7, 1.0), (0.25, 0.25), (0, 0.0), (1, 1.0)],
)
def test_unit_values_are_clamped(tmp_path: Path, raw: float, expected: float) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"opacity": raw, "sharpness": raw}), encoding="utf-8")
    loaded = settings.load(path)
    assert (loaded.opacity, loaded.sharpness) == (expected, expected)
    assert isinstance(loaded.opacity, float)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_reset_to_default(tmp_path: Path, token: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(f'{{"opacity": {token}, "sharpness": {token}}}', encoding="utf-8")
    loaded = settings.load(path)
    assert (loaded.opacity, loaded.sharpness) == (1.0, 0.0)


@pytest.mark.parametrize(
    ("quality", "language", "want_quality", "want_language"),
    [
        ("fast", "en", "fast", "en"),
        (" BEST ", "RU", "best", "ru"),
        ("ultra", "de", "balanced", "auto"),
        ("", "", "balanced", "auto"),
    ],
)
def test_enums_are_validated(
    tmp_path: Path, quality: str, language: str, want_quality: str, want_language: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"quality": quality, "language": language}), encoding="utf-8")
    loaded = settings.load(path)
    assert (loaded.quality, loaded.language) == (want_quality, want_language)


def test_save_sanitises_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings.save(Settings(opacity=3.0, quality="turbo", sharpness=float("nan")), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["opacity"] == 1.0
    assert data["quality"] == "balanced"
    assert data["sharpness"] == 0.0
    assert set(data) == {f.name for f in fields(Settings)}


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings.save(Settings(language="en"), path)
    settings.save(Settings(language="ru"), path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]
    assert settings.load(path).language == "ru"


def test_failed_replace_keeps_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    settings.save(Settings(language="en"), path)

    def broken_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(settings.os, "replace", broken_replace)
    settings.save(Settings(language="ru"), path)  # must not raise
    monkeypatch.undo()
    assert settings.load(path).language == "en"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions, non-root"
)
def test_read_only_directory_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        with caplog.at_level(logging.WARNING):
            settings.save(Settings(), folder / "settings.json")
        assert "Could not save settings" in caplog.text
        assert not (folder / "settings.json").exists()
    finally:
        folder.chmod(0o700)
