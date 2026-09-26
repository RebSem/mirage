"""Shared fixtures for Mirage tests: no models, camera, network or display.

MIRAGE_HOME is redirected before any test module is imported, so nothing in
this suite can touch the real ~/Library/Application Support/Mirage.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_SESSION_HOME = tempfile.mkdtemp(prefix="mirage-tests-")
os.environ["MIRAGE_HOME"] = _SESSION_HOME
atexit.register(shutil.rmtree, _SESSION_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def mirage_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh, empty MIRAGE_HOME for every test (kept apart from tmp_path)."""
    home = tmp_path_factory.mktemp("mirage-home")
    monkeypatch.setenv("MIRAGE_HOME", str(home))
    return home
