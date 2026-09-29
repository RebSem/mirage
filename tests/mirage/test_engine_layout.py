"""The Deep-Live-Cam engine in third_party/: where it lives and how Mirage finds it (no models needed)."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "third_party" / "deep-live-cam"


def test_engine_models_folder_is_a_link_to_the_repo_models_folder():
    link = ENGINE / "models"
    assert link.is_symlink() and os.readlink(link) == "../../models"


def test_upstream_commit_is_recorded():
    commit = (ENGINE / "UPSTREAM_COMMIT").read_text().strip()
    assert len(commit) == 40 and int(commit, 16) >= 0


def test_importing_mirage_puts_the_engine_on_sys_path():
    """What `python -m mirage`, Mirage.app and the installer rely on (pytest's own pythonpath would hide a break)."""
    code = "import mirage, modules.globals as g; print(g.__file__)"
    out = subprocess.run([sys.executable, "-c", code], cwd="/", env={**os.environ, "PYTHONPATH": str(REPO)},
                         capture_output=True, text=True, check=True).stdout.strip()
    assert Path(out).resolve().is_relative_to(ENGINE.resolve())
