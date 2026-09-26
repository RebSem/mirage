"""Mirage's single window: stage + control bar on the left, glass sidebar on the right."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMenuBar,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import mirage
from mirage import camera as cameras
from mirage import engine as eng
from mirage import paths, theme
from mirage.glass import GlassWindow
from mirage.i18n import tr
from mirage.library import FaceLibrary, NoFaceError, UnreadableImageError
from mirage.settings import Settings
from mirage.ui.faces import ADD, ME, RANDOM, FaceGrid
from mirage.ui.look import LookPanel
from mirage.ui.stage import Stage
from mirage.ui.toast import ToastHost
from mirage.ui.widgets import GlassPanel, IconButton, PrimaryButton, StatusPill

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".tif", ".tiff"}
AMBIENT_EVERY_S = 0.35


class _CameraCombo(QComboBox):
    """Re-reads the camera list whenever the dropdown opens."""

    aboutToShow = Signal()

    def showPopup(self) -> None:  # noqa: N802
        self.aboutToShow.emit()
        super().showPopup()


class _TopBar(QWidget):
    """Title row that also drags the window (the title bar is transparent)."""

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()


class MainWindow(QWidget):
    closing = Signal()              # the app is about to quit (see app.cleanup)
    importDone = Signal(object)     # list of (kind, payload)
    randomDone = Signal(object)     # (entry | None, error | None)

    def __init__(self, engine: eng.LiveEngine, library: FaceLibrary, settings: Settings, save_settings,
                 demo_photo: str | None = None):
        super().__init__()
        self._demo = (
            cameras.CameraInfo(index=-1, name="Demo", uid=f"demo:{Path(demo_photo).resolve()}", builtin=False)
            if demo_photo else None
        )
        self.engine = engine
        self.library = library
        self.settings = settings
        self._save_settings = save_settings
        self._busy_imports = 0
        self._random_count = 0
        self._last_ambient = 0.0
        self._cameras: list[cameras.CameraInfo] = []
        self._models_state = "loading"
        self._vcam_installed = cameras.virtual_camera_installed()
        self._live_since: float | None = None
        self._vcam_warned = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(lambda: self._save_settings(self.settings))

        self.setObjectName("root")
        self.setWindowTitle(mirage.APP_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Draw under the (transparent) title bar, like native macOS 26 apps.
        self.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
        self.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
        # We place the top bar next to the traffic lights ourselves.
        self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.setMinimumSize(*theme.WINDOW_MIN)
        self.resize(*theme.WINDOW_DEFAULT)
        self.setAcceptDrops(True)
        self.setStyleSheet(theme.STYLE)
        self.glass = GlassWindow(self)

        self._build()
        self._build_menu()
        self._build_shortcuts()
        self._wire_engine()
        self.importDone.connect(self._on_import_done)
        self.randomDone.connect(self._on_random_done)

        self._refresh_cameras()
        self._reload_faces()
        self._select_face(settings.face_id, announce=False)
        self.engine.apply(settings)
        self._on_state(self.engine.state)
        self._refresh_vcam_hint()

        if settings.window_geometry:
            try:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
            except Exception:
                pass

    # ── layout ───────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.MARGIN, 0, theme.MARGIN, theme.MARGIN)
        root.setSpacing(6)

        top = _TopBar()
        top.setFixedHeight(theme.TITLEBAR_HEIGHT)  # vertically centred on the traffic lights
        tl = QHBoxLayout(top)
        tl.setContentsMargins(theme.TRAFFIC_LIGHTS_SPACE, 0, 4, 0)
        tl.setSpacing(12)
        title = QLabel(mirage.APP_NAME)
        title.setFont(theme.font(15, theme.QFont.Weight.Bold))
        self.status = StatusPill()
        self.status.setFont(theme.font(12, theme.QFont.Weight.Medium))
        self.vcam_label = QLabel()
        self.vcam_label.setObjectName("hint")
        self.vcam_label.setFont(theme.font(12))
        help_btn = IconButton("help", tr("vcam_help"), 26)
        help_btn.clicked.connect(self._open_vcam_help)
        tl.addWidget(title)
        tl.addWidget(self.status)
        tl.addStretch(1)
        tl.addWidget(self.vcam_label)
        tl.addWidget(help_btn)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(theme.GAP)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(theme.GAP)
        body.addLayout(left, 1)

        self.stage_frame = GlassPanel(theme.RADIUS_STAGE)
        sf = QVBoxLayout(self.stage_frame)
        sf.setContentsMargins(0, 0, 0, 0)
        self.stage = Stage()
        self.stage.mirror = self.settings.mirror_preview
        self.stage.show_fps = self.settings.show_fps
        sf.addWidget(self.stage)
        left.addWidget(self.stage_frame, 1)

        self.bar = GlassPanel(theme.RADIUS_BAR)
        self.bar.setFixedHeight(theme.CONTROL_BAR_HEIGHT)
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(18, 0, 18, 0)
        bl.setSpacing(12)
        cam_icon = IconButton("camera", tr("camera"), 30)
        cam_icon.setEnabled(False)
        self.camera_combo = _CameraCombo()
        self.camera_combo.setMinimumWidth(190)
        self.camera_combo.setMaximumWidth(260)
        self.camera_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.camera_combo.aboutToShow.connect(self._refresh_cameras)
        self.camera_combo.activated.connect(self._on_camera_picked)
        self.primary = PrimaryButton()
        self.primary.clicked.connect(self.toggle_live)
        self.mirror_btn = IconButton("mirror", tr("mirror_preview"), 36)
        self.mirror_btn.setCheckable(True)
        self.mirror_btn.setChecked(self.settings.mirror_preview)
        self.mirror_btn.toggled.connect(lambda on: self._set("mirror_preview", on))
        bl.addWidget(cam_icon)
        bl.addWidget(self.camera_combo)
        bl.addStretch(1)
        bl.addWidget(self.primary)
        bl.addStretch(1)
        right_spacer = QWidget()
        right_spacer.setFixedWidth(cam_icon.width() + self.camera_combo.minimumWidth() - self.mirror_btn.width())
        bl.addWidget(right_spacer)
        bl.addWidget(self.mirror_btn)
        left.addWidget(self.bar)

        self.sidebar = GlassPanel(theme.RADIUS_PANEL)
        self.sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(18, 18, 18, 16)
        sl.setSpacing(10)
        faces_title = QLabel(tr("faces"))
        faces_title.setObjectName("sectionTitle")
        faces_title.setFont(theme.font(15, theme.QFont.Weight.Bold))
        sl.addWidget(faces_title)

        self.grid = FaceGrid()
        self.grid.picked.connect(self._on_tile)
        self.grid.menuRequested.connect(self._face_menu)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.grid)
        scroll.viewport().setAutoFillBackground(False)
        sl.addWidget(scroll, 1)

        self.empty_hint = QLabel(tr("empty_library"))
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setFont(theme.font(11.5))
        sl.addWidget(self.empty_hint)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {theme.rgba(theme.HAIRLINE)};")
        sl.addWidget(divider)

        look_title = QLabel(tr("look"))
        look_title.setObjectName("sectionTitle")
        look_title.setFont(theme.font(15, theme.QFont.Weight.Bold))
        sl.addWidget(look_title)
        self.look = LookPanel(self.settings)
        self.look.changed.connect(self._set)
        sl.addWidget(self.look)
        body.addWidget(self.sidebar)

        for panel in (self.stage_frame, self.bar, self.sidebar):
            panel.native_glass = self.glass.native
            self.glass.add(panel, panel.radius)

        self.toasts = ToastHost(self, self.stage)

    def _build_menu(self) -> None:
        bar = QMenuBar(self)  # becomes the native macOS menu bar
        file_menu = bar.addMenu(tr("menu_file"))
        self._action(file_menu, tr("menu_add_photos"), "Ctrl+O", self.add_photos)
        self._action(file_menu, tr("menu_random_face"), "Ctrl+R", self.random_face)
        live_menu = bar.addMenu(tr("menu_live"))
        self._action(live_menu, tr("menu_start_stop"), None, self.toggle_live)
        self._action(live_menu, tr("menu_mirror"), "Ctrl+Shift+M", lambda: self.mirror_btn.toggle())
        faces_menu = bar.addMenu(tr("menu_faces"))
        self._action(faces_menu, tr("menu_me"), None, lambda: self._select_face(None))
        help_menu = bar.addMenu(tr("menu_help"))
        self._action(help_menu, tr("menu_readme"), None, lambda: self._open_doc("README.md"))
        self._action(help_menu, tr("menu_troubleshooting"), None, lambda: self._open_doc("docs/TROUBLESHOOTING.md"))
        self._action(help_menu, tr("menu_responsible"), None, lambda: self._open_doc("docs/RESPONSIBLE_USE.md"))
        self._action(help_menu, tr("menu_logs"), None,
                     lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir()))))
        self._action(help_menu, tr("menu_report"), None,
                     lambda: QDesktopServices.openUrl(QUrl(mirage.REPO_URL + "/issues/new/choose")))
        about = self._action(help_menu, tr("menu_about"), None, self._about)
        about.setMenuRole(QAction.MenuRole.AboutRole)

    def _action(self, menu: QMenu, text: str, shortcut: str | None, slot) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_shortcuts(self) -> None:
        # Keyboard actions are instant — no animation (they're used constantly).
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_live)
        QShortcut(QKeySequence(Qt.Key.Key_0), self, lambda: self._select_face(None))
        for n in range(1, 10):
            QShortcut(QKeySequence(str(n)), self, lambda n=n: self._select_by_number(n))

    # ── engine wiring ────────────────────────────────────────────────────

    def _wire_engine(self) -> None:
        self.engine.stateChanged.connect(self._on_state)
        self.engine.modelsState.connect(self._on_models_state)
        self.engine.qualityFallback.connect(self._on_quality_fallback)
        self.engine.previewReady.connect(self._on_preview)
        self.engine.statsChanged.connect(self._on_stats)
        self.engine.notice.connect(lambda level, key, args: self.toast(tr(key, **args), level))

    def _on_models_state(self, state: str) -> None:
        self._models_state = state
        self._on_state(self.engine.state)

    def _on_quality_fallback(self, quality: str) -> None:
        self.look.quality.set_value(quality)
        self.look.quality_hint.setText(tr(f"quality_hint_{quality}"))
        self._set("quality", quality)

    def _on_state(self, state: str) -> None:
        if state == eng.LIVE:
            self.primary.set_mode("stop", tr("stop"))
            self.stage.set_mode("live")
            self.status.set_status(tr("status_live"), theme.LIVE, pulse=True)
            self._live_since, self._vcam_warned = time.monotonic(), False
        elif state == eng.LOADING:
            self.primary.set_mode("busy", tr("status_loading"))
            self.stage.set_mode("loading")
            self.status.set_status(tr("status_loading"), theme.WARN, pulse=True)
        elif state == eng.STARTING:
            self.primary.set_mode("busy", tr("status_starting"))
            self.stage.set_mode("starting")
            self.status.set_status(tr("status_starting"), theme.WARN, pulse=True)
        elif state == eng.STOPPING:
            self.primary.set_mode("busy", tr("status_stopping"))
            self.stage.set_mode("idle")
            self.status.set_status(tr("status_stopping"), theme.TEXT_TERTIARY)
        else:
            self.primary.set_mode("start", tr("start"))
            self.stage.set_mode("idle")
            if self._models_state == "failed":
                self.status.set_status(tr("status_models_failed"), theme.LIVE)
            elif self.engine.models_ready:
                self.status.set_status(tr("status_ready"), theme.READY)
            else:  # Start still works; it just waits for the warm-up to finish
                self.status.set_status(tr("status_warming"), theme.WARN, pulse=True)
            self.glass.set_ambient(None)
        if state != eng.LIVE:
            self._live_since = None
        self.camera_combo.setEnabled(state == eng.IDLE)
        self._vcam_installed = cameras.virtual_camera_installed()
        self._refresh_vcam_hint()

    def _on_preview(self) -> None:
        frame = self.engine.take_preview()
        if frame is None:
            return
        self.stage.set_frame(frame)
        now = time.monotonic()
        if now - self._last_ambient >= AMBIENT_EVERY_S:
            self._last_ambient = now
            self.glass.set_ambient(frame, fade=AMBIENT_EVERY_S * 1.4)

    def _on_stats(self, stats: dict) -> None:
        fps = float(stats.get("fps", 0.0))
        self.stage.fps = fps
        self.stage.set_face_found(bool(stats.get("face_found")))
        if self.engine.state == eng.LIVE:
            self.status.set_status(f"{tr('status_live')} · {tr('status_fps', fps=fps)}", theme.LIVE, pulse=True)
        self._refresh_vcam_hint(streaming=bool(stats.get("vcam")))

    def _refresh_vcam_hint(self, streaming: bool = False) -> None:
        live_for = time.monotonic() - self._live_since if self._live_since is not None else 0.0
        if streaming:
            self.vcam_label.setText(tr("vcam_streaming"))
        elif self._live_since is not None and live_for > 3.0:
            # Live, but nothing reaches the virtual camera (OBS extension missing/blocked).
            self.vcam_label.setText(tr("vcam_not_receiving"))
            if not self._vcam_warned:
                self._vcam_warned = True
                self.toast(tr("toast_vcam_unavailable"), "warn")
        elif self._vcam_installed:
            self.vcam_label.setText(tr("vcam_ready"))
        else:
            self.vcam_label.setText(tr("vcam_missing"))

    def _open_vcam_help(self) -> None:
        anchor = "#zoom-shows-the-obs-logo-or-a-black-picture" if self._vcam_installed else "#obs-virtual-camera-is-missing"
        self._open_doc("docs/TROUBLESHOOTING.md" + anchor)

    # ── live ─────────────────────────────────────────────────────────────

    def toggle_live(self) -> None:
        state = self.engine.state
        if state == eng.LIVE:
            self.engine.stop()
            return
        if state != eng.IDLE:
            return
        cam = self._current_camera()
        if cam is None:
            self.toast(tr("no_camera"), "error")
            return
        self.engine.start(cam)

    def _current_camera(self) -> cameras.CameraInfo | None:
        self._refresh_cameras()
        idx = self.camera_combo.currentIndex()
        return self._cameras[idx] if 0 <= idx < len(self._cameras) else None

    def _refresh_cameras(self) -> None:
        cams = ([self._demo] if self._demo else []) + cameras.list_cameras()
        self._cameras = cams
        wanted = self.settings.camera_uid
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        if not cams:
            self.camera_combo.addItem(tr("no_camera"))
        else:
            self.camera_combo.addItems([c.name for c in cams])
            uids = [c.uid for c in cams]
            self.camera_combo.setCurrentIndex(uids.index(wanted) if wanted in uids else 0)
        self.camera_combo.blockSignals(False)

    def _on_camera_picked(self, idx: int) -> None:
        if 0 <= idx < len(self._cameras):
            self._set("camera_uid", self._cameras[idx].uid)

    # ── faces ────────────────────────────────────────────────────────────

    def _reload_faces(self) -> None:
        faces = []
        for entry in self.library.list():
            pix = QPixmap(str(self.library.thumb_path(entry.id)))
            faces.append((entry.id, entry.name, pix))
        self.grid.rebuild(faces, self.settings.face_id, self._busy_imports)
        self.empty_hint.setVisible(not faces)

    def _on_tile(self, face_id: str) -> None:
        if face_id == ADD:
            self.add_photos()
        elif face_id == RANDOM:
            self.random_face()
        elif face_id == ME:
            self._select_face(None)
        else:
            self._select_face(face_id)

    def _select_by_number(self, n: int) -> None:
        entries = self.library.list()
        if 1 <= n <= len(entries):
            self._select_face(entries[n - 1].id)

    def _select_face(self, face_id: str | None, announce: bool = True) -> None:
        embedding = None
        name = ""
        if face_id is not None:
            entry = self.library.get(face_id)
            if entry is None:
                face_id = None
            else:
                try:
                    embedding = self.library.embedding(face_id)
                    name = entry.name
                except Exception:
                    log.exception("could not load the embedding of %s", face_id)
                    self.toast(tr("toast_face_unreadable", name=entry.name), "warn")
                    face_id, embedding = None, None
        self.engine.set_face(embedding)
        self.stage.face_name = name
        self.grid.set_selected(face_id)
        if face_id != self.settings.face_id:
            self._set("face_id", face_id)
        self.stage.update()

    def _face_menu(self, face_id: str, pos: QPointF) -> None:
        entry = self.library.get(face_id)
        if entry is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("rename"), lambda: self._rename(face_id))
        menu.addAction(tr("show_in_finder"), lambda: self._reveal(face_id))
        menu.addSeparator()
        menu.addAction(tr("remove"), lambda: self._remove(face_id))
        menu.exec(pos.toPoint())

    def _rename(self, face_id: str) -> None:
        entry = self.library.get(face_id)
        if entry is None:
            return
        name, ok = QInputDialog.getText(self, tr("rename_title"), tr("rename_title"), text=entry.name)
        if ok and name.strip():
            self.library.rename(face_id, name.strip())
            self._reload_faces()
            stored = self.library.get(face_id)
            if stored is not None and self.settings.face_id == face_id:
                self.stage.face_name = stored.name
                self.stage.update()

    def _reveal(self, face_id: str) -> None:
        import subprocess

        subprocess.run(["open", "-R", str(self.library.image_path(face_id))], check=False)

    def _remove(self, face_id: str) -> None:
        entry = self.library.get(face_id)
        if entry is None:
            return
        text = tr("remove_confirm_text", name=entry.name)
        if self.settings.face_id == face_id and self.engine.state == eng.LIVE:
            text += "\n\n" + tr("remove_confirm_live")
        box = QMessageBox(QMessageBox.Icon.Question, tr("remove_confirm_title"), text, parent=self)
        remove_btn = box.addButton(tr("remove"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not remove_btn:
            return
        self.library.remove(face_id)
        if self.settings.face_id == face_id:
            self._select_face(None)
        self._reload_faces()
        self.toast(tr("toast_removed", name=entry.name))

    def add_photos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("file_dialog_title"), str(Path.home() / "Pictures"),
            tr("file_filter_images") + " (*.jpg *.jpeg *.png *.webp *.bmp *.heic *.tif *.tiff)",
        )
        if files:
            self._import([Path(f) for f in files])

    def _import(self, files: list[Path]) -> None:
        self._busy_imports += len(files)
        self._reload_faces()

        def work() -> None:
            results = []
            for path in files:
                try:
                    results.append(("ok", self.library.add_file(path)))
                except NoFaceError:
                    results.append(("no_face", path.name))
                except (UnreadableImageError, OSError):
                    results.append(("unreadable", path.name))
                except Exception:
                    log.exception("import failed for %s", path)
                    results.append(("failed", path.name))
            self.importDone.emit(results)

        threading.Thread(target=work, name="mirage-import", daemon=True).start()

    def _on_import_done(self, results: list) -> None:
        self._busy_imports = max(0, self._busy_imports - len(results))
        self._reload_faces()
        added = [payload for kind, payload in results if kind == "ok"]
        for kind, payload in results:
            if kind == "no_face":
                self.toast(tr("toast_no_face_photo", name=payload), "warn")
            elif kind == "unreadable":
                self.toast(tr("toast_unreadable", name=payload), "warn")
            elif kind == "failed":
                self.toast(tr("toast_import_failed", name=payload), "error")
        if len(added) == 1:
            self.toast(tr("toast_added", name=added[0].name))
            self._select_face(added[0].id)
        elif len(added) > 1:
            self.toast(tr("toast_added_many", n=len(added)))
            self._select_face(added[-1].id)

    def random_face(self) -> None:
        self._busy_imports += 1
        self._reload_faces()
        self._random_count += 1
        name = tr("random_name", n=self._random_count)

        def work() -> None:
            from mirage.faces_ai import fetch_random_face

            try:
                image = fetch_random_face()
            except Exception as exc:  # network, or the site changed
                log.warning("random face download failed: %s", exc)
                self.randomDone.emit((None, "network"))
                return
            try:
                self.randomDone.emit((self.library.add_image(image, name), None))
            except Exception:
                log.exception("random face import failed")
                self.randomDone.emit((None, "import"))

        threading.Thread(target=work, name="mirage-random", daemon=True).start()

    def _on_random_done(self, result) -> None:
        entry, error = result
        self._busy_imports = max(0, self._busy_imports - 1)
        self._reload_faces()
        if entry is None:
            self.toast(tr("toast_random_failed") if error == "network"
                       else tr("toast_import_failed", name=tr("random_face")), "warn")
        else:
            self._select_face(entry.id)

    # ── drag & drop ──────────────────────────────────────────────────────

    def _dropped_images(self, event) -> list[Path]:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return [Path(u.toLocalFile()) for u in urls
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._dropped_images(event):
            event.acceptProposedAction()
            self.stage.set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.stage.set_drop_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.stage.set_drop_active(False)
        files = self._dropped_images(event)
        if files:
            event.acceptProposedAction()
            self._import(files)

    # ── settings ─────────────────────────────────────────────────────────

    def _set(self, field: str, value) -> None:
        self.settings = replace(self.settings, **{field: value})
        if field in ("quality", "opacity", "sharpness", "mouth_mask", "many_faces", "color_fix", "poisson_blend"):
            self.engine.apply(self.settings)
        if field == "mirror_preview":
            self.stage.mirror = bool(value)
            self.stage.update()
        if field == "show_fps":
            self.stage.show_fps = bool(value)
            self.stage.update()
        self._save_timer.start()

    def save_state(self) -> Settings:
        geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings = replace(self.settings, window_geometry=geometry)
        return self.settings

    # ── misc ─────────────────────────────────────────────────────────────

    def toast(self, text: str, level: str = "info") -> None:
        self.toasts.show_toast(text, level)

    def _open_doc(self, rel: str) -> None:
        QDesktopServices.openUrl(QUrl(f"{mirage.REPO_URL}/blob/main/{rel}"))

    def _about(self) -> None:
        QMessageBox.about(self, tr("menu_about"), tr("about_text", version=mirage.__version__))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._install_glass)

    def _install_glass(self) -> None:
        self.glass.install()
        for panel in (self.stage_frame, self.bar, self.sidebar):
            panel.native_glass = self.glass.native  # falls back to painted glass if install failed
            panel.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.glass.native:  # no native glass: an opaque dark window, not a see-through one
            from PySide6.QtGui import QPainter

            p = QPainter(self)
            p.fillRect(self.rect(), theme.FALLBACK_WINDOW)
        super().paintEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closing.emit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.sync_geometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(*theme.WINDOW_DEFAULT)
