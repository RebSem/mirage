"""Mirage entry point: one instance, clean start, clean quit."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading

import mirage
from mirage import paths

log = logging.getLogger("mirage")


def _setup_logging(debug: bool) -> None:
    handler = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / "mirage.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(handler)
    root.addHandler(console)

    def excepthook(exc_type, exc, tb):
        log.critical("unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = excepthook
    threading.excepthook = lambda args: log.error(
        "unhandled exception in thread %s", args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _brand_process() -> None:
    """Show "Mirage" in the menu bar and Dock even though python is the binary."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
            if info is not None:
                info["CFBundleName"] = mirage.APP_NAME
    except Exception:
        pass


def _set_dock_icon() -> None:
    icon = paths.repo_root() / "assets" / "icon" / "mirage-1024.png"
    if sys.platform != "darwin" or not icon.exists():
        return
    try:
        import AppKit

        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon))
        if image is not None:
            AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass


def _dark_appearance() -> None:
    """Mirage is always dark: dialogs and menus match the glass window."""
    if sys.platform != "darwin":
        return
    try:
        import AppKit

        AppKit.NSApplication.sharedApplication().setAppearance_(
            AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
        )
    except Exception:
        pass


REQUIRED_PACKAGES = ("PySide6", "numpy", "cv2", "onnxruntime", "insightface", "PIL", "AppKit", "AVFoundation")


def _missing_packages() -> list[str]:
    import importlib.util

    return [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]


def _alert_cannot_start(missing: list[str]) -> None:
    """Mirage.app has no terminal: say what's wrong in a native alert (no Qt needed)."""
    import subprocess

    message = (f"Some parts of Mirage aren't installed ({', '.join(missing)}). "
               f"Run make install in {paths.repo_root()}, then open Mirage again.")
    script = ['/usr/bin/osascript', '-e', 'on run argv',
              '-e', 'display alert "Mirage can\'t start" message (item 1 of argv) as critical', '-e', 'end run', message]
    subprocess.run(script, check=False, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mirage", description="Mirage — real-time face swap for macOS")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--version", action="version", version=f"Mirage {mirage.__version__}")
    parser.add_argument("--demo", metavar="PHOTO", help="add a fake 'Demo' camera that shows this photo moving")
    args = parser.parse_args(argv)

    _setup_logging(args.debug)
    missing = _missing_packages()
    if missing:  # e.g. a venv from an older install: fail visibly instead of silently
        log.critical("missing packages: %s", ", ".join(missing))
        _alert_cannot_start(missing)
        return 1
    _brand_process()
    os.chdir(paths.repo_root())  # a stable working directory (the engine's own files are found via __file__)

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(mirage.APP_NAME)
    app.setApplicationDisplayName(mirage.APP_NAME)
    app.setApplicationVersion(mirage.__version__)
    app.setOrganizationDomain("rebsem.github.io")
    icon_path = paths.repo_root() / "assets" / "icon" / "mirage-1024.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    _set_dock_icon()

    # One Mirage at a time: a second launch just brings the first window forward.
    socket = QLocalSocket()
    socket.connectToServer(mirage.BUNDLE_ID)
    if socket.waitForConnected(300):
        socket.write(b"activate")
        socket.waitForBytesWritten(300)
        log.info("Mirage is already running; activated the existing window")
        return 0
    QLocalServer.removeServer(mirage.BUNDLE_ID)  # stale socket from a crash
    server = QLocalServer()
    server.listen(mirage.BUNDLE_ID)

    from PySide6.QtCore import QLibraryInfo, QTranslator

    from mirage import faces_ai, i18n, settings as settings_mod
    from mirage.engine import LiveEngine
    from mirage.library import FaceLibrary
    from mirage.ui.main_window import MainWindow

    settings = settings_mod.load()
    if i18n.set_language(settings.language) == "ru":
        # Qt's own strings: dialog buttons, the app menu, file dialogs
        qt_ru = QTranslator(app)
        if qt_ru.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(qt_ru)
    _dark_appearance()
    engine = LiveEngine()
    library = FaceLibrary(paths.faces_dir(), faces_ai.embed)
    window = MainWindow(engine, library, settings, settings_mod.save, demo_photo=args.demo)

    def activate() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readAll()
            conn.disconnectFromServer()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(activate)

    done = threading.Event()

    def cleanup() -> None:
        """Save settings and release camera/threads. Runs once, whichever way we quit.

        On macOS, Cmd+Q ends in [NSApp terminate:], which exits the process
        without returning from exec() or emitting aboutToQuit, so this is
        also called from the window's closeEvent (Qt closes windows first).
        """
        if done.is_set():
            return
        done.set()
        log.info("quitting")
        try:
            settings_mod.save(window.save_state())
        except Exception:
            log.exception("could not save settings")
        window.media.shutdown()  # cancel a running render; a video deletes its partial file
        engine.shutdown()
        server.close()
        # Everything that matters is saved and stopped. Leave now: a background thread
        # can be inside a native call (a model compiling for the Neural Engine) that
        # holds Python's lock for seconds, and Qt's own teardown would wait for it,
        # so Mirage would look like it doesn't close.
        log.info("bye")
        logging.shutdown()
        os._exit(0)

    window.closing.connect(cleanup)
    app.aboutToQuit.connect(cleanup)

    def on_signal(*_args) -> None:
        cleanup()
        app.quit()

    # Ctrl+C / kill. The timer lets Python notice signals while Qt's event
    # loop sits in native code.
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    heartbeat = QTimer()
    heartbeat.start(250)
    heartbeat.timeout.connect(lambda: None)

    window.show()
    window.raise_()
    engine.prepare()  # warm the models while the user picks a face
    log.info("Mirage %s started", mirage.__version__)
    return app.exec()
