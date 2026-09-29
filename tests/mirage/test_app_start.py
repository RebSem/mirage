from mirage import app


def test_missing_packages_are_reported_instead_of_a_silent_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("MIRAGE_HOME", str(tmp_path))
    shown = []
    monkeypatch.setattr(app, "_missing_packages", lambda: ["PySide6", "onnxruntime"])
    monkeypatch.setattr(app, "_alert_cannot_start", shown.append)
    assert app.main([]) == 1
    assert shown == [["PySide6", "onnxruntime"]]


def test_a_complete_install_has_every_required_package():
    import pytest

    for heavy in ("PySide6", "onnxruntime", "insightface"):  # CI installs only the light set
        pytest.importorskip(heavy)
    assert app._missing_packages() == []
