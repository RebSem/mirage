"""Mirage — a face swap app for macOS: live on video calls, and in photos and videos.

The face-swap engine underneath is Deep-Live-Cam, vendored in
third_party/deep-live-cam (see its README). Its code imports itself as the
top-level package ``modules``, so that folder goes on sys.path here, before
anything in Mirage imports it.
"""

import sys as _sys
from pathlib import Path as _Path

__version__ = "0.2.0"
APP_NAME = "Mirage"
BUNDLE_ID = "io.github.rebsem.mirage"
REPO_URL = "https://github.com/RebSem/mirage"
UPSTREAM_URL = "https://github.com/hacksider/Deep-Live-Cam"

ENGINE_DIR = _Path(__file__).resolve().parent.parent / "third_party" / "deep-live-cam"
if str(ENGINE_DIR) not in _sys.path:
    _sys.path.insert(0, str(ENGINE_DIR))
