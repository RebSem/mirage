"""Native glass must never be attempted outside Qt's Cocoa platform (it crashes there)."""

import os
import subprocess
import sys

import pytest


def test_no_native_glass_offscreen() -> None:
    pytest.importorskip("PySide6")
    # A child process: a QGuiApplication can only be created once per process.
    code = (
        "import mirage\n"
        "from PySide6.QtGui import QGuiApplication\n"
        "app = QGuiApplication([])\n"
        "from mirage.glass import glass_supported\n"
        "print(glass_supported())\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60,
                         cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"
