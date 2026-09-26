"""Every filesystem location Mirage uses, in one place.

Set MIRAGE_HOME to redirect all per-user data (tests do this).
"""

import os
import sys
from pathlib import Path


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _home_override() -> Path | None:
    value = os.environ.get("MIRAGE_HOME")
    return Path(value).expanduser() if value else None


def app_support_dir() -> Path:
    override = _home_override()
    if override is not None:
        return _ensure(override)
    if sys.platform == "darwin":
        return _ensure(Path.home() / "Library" / "Application Support" / "Mirage")
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return _ensure(Path(base) / "mirage")


def faces_dir() -> Path:
    return _ensure(app_support_dir() / "faces")


def settings_path() -> Path:
    return app_support_dir() / "settings.json"


def logs_dir() -> Path:
    override = _home_override()
    if override is not None:
        return _ensure(override / "logs")
    if sys.platform == "darwin":
        return _ensure(Path.home() / "Library" / "Logs" / "Mirage")
    return _ensure(app_support_dir() / "logs")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return _ensure(repo_root() / "models")
