"""Keep the Mac awake (and out of App Nap) while Mirage is live."""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


class AwakeGuard:
    def __init__(self) -> None:
        self._token = None

    def hold(self, reason: str) -> None:
        if self._token is not None or sys.platform != "darwin":
            return
        try:
            from Foundation import NSActivityLatencyCritical, NSActivityUserInitiated, NSProcessInfo

            self._token = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
                NSActivityUserInitiated | NSActivityLatencyCritical, reason
            )
        except Exception as exc:
            log.warning("could not hold an activity assertion: %s", exc)

    def release(self) -> None:
        if self._token is None:
            return
        try:
            from Foundation import NSProcessInfo

            NSProcessInfo.processInfo().endActivity_(self._token)
        except Exception:
            pass
        self._token = None
