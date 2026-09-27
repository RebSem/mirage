"""Photos & videos mode: open → faces found → plan → swap → save (or batch / video)."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.media.plan import assigned_count, auto_plan, rank_sources, swap_everyone
from mirage.media.types import Plan, RenderOptions, SourceInfo, TargetFace
from mirage.ui.media_view import BatchRow, FaceLabel, MediaView
from mirage.ui.widgets import GlassPanel, IconButton, PrimaryButton, Switch

log = logging.getLogger(__name__)

EMPTY, PHOTO, BATCH, VIDEO = "empty", "photo", "batch", "video"


def _round_pixmap(path: Path, size: int) -> QPixmap | None:
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(clip)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


def _file_thumb(path: Path, size: int = 72) -> QPixmap | None:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original = reader.size()
    if original.isValid() and original.width() > 0:
        scale = size / max(1, min(original.width(), original.height()))
        reader.setScaledSize(QSize(max(1, int(original.width() * scale)), max(1, int(original.height() * scale))))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else None


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "…"
    seconds = int(max(0, seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class MediaPage(QWidget):
    _analyzed = Signal(object)
    _rendered = Signal(object)
    _saved = Signal(object)
    _batchUpdate = Signal(object)
    _batchDone = Signal(object)
    _videoProgress = Signal(object)
    _videoDone = Signal(object)

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.kind = EMPTY
        self.path: Path | None = None
        self.image: np.ndarray | None = None
        self.meta = None
        self.result: np.ndarray | None = None
        self.saved_path: Path | None = None
        self.targets: list[TargetFace] = []
        self.plan: Plan = {}
        self.video_info = None
        self.batch_items: list = []
        self.busy = False
        self._token = 0
        self._cancel = threading.Event()
        self._renderer = None
        self._attrs_checked: set[str] = set()
        self._live_warned = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.GAP)
        self.frame = GlassPanel(theme.RADIUS_STAGE)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(0, 0, 0, 0)
        self.view = MediaView()
        self.view.faceClicked.connect(self._on_face_clicked)
        self.view.backgroundClicked.connect(self.clear_active)
        fl.addWidget(self.view)
        lay.addWidget(self.frame, 1)

        self.bar = GlassPanel(theme.RADIUS_BAR)
        self.bar.setFixedHeight(theme.CONTROL_BAR_HEIGHT)
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(18, 0, 18, 0)
        bl.setSpacing(12)
        self.open_btn = IconButton("plus", tr("media_open"), 36)
        self.open_btn.clicked.connect(self.open_dialog)
        self.everyone_btn = IconButton("people", tr("media_swap_everyone"), 36)
        self.everyone_btn.clicked.connect(self.assign_everyone)
        self.enhance = Switch()
        self.enhance.toggled.connect(self._on_enhance)
        self.enhance_label = QLabel(tr("media_enhance"))
        self.enhance_label.setObjectName("hint")
        self.enhance_label.setFont(theme.font(12))
        self.primary = PrimaryButton()
        self.primary.clicked.connect(self._on_primary)
        self.finder_btn = IconButton("folder", tr("media_show_in_finder"), 36)
        self.finder_btn.clicked.connect(self.reveal)
        self.compare_btn = IconButton("compare", tr("media_compare"), 36)
        self.compare_btn.pressed.connect(lambda: self.compare(True))
        self.compare_btn.released.connect(lambda: self.compare(False))
        bl.addWidget(self.open_btn)
        bl.addWidget(self.everyone_btn)
        bl.addWidget(self.enhance)
        bl.addWidget(self.enhance_label)
        bl.addStretch(1)
        bl.addWidget(self.primary)
        bl.addStretch(1)
        bl.addWidget(self.finder_btn)
        bl.addWidget(self.compare_btn)
        lay.addWidget(self.bar)

        self._analyzed.connect(self._on_analyzed)
        self._rendered.connect(self._on_rendered)
        self._saved.connect(self._on_saved)
        self._batchUpdate.connect(self._on_batch_update)
        self._batchDone.connect(self._on_batch_done)
        self._videoProgress.connect(self._on_video_progress)
        self._videoDone.connect(self._on_video_done)
        self._refresh()

    # ── helpers ──────────────────────────────────────────────────────────

    @property
    def library(self):
        return self.win.library

    @property
    def settings(self):
        return self.win.settings

    def _toast(self, text: str, level: str = "info") -> None:
        self.win.toast(text, level)

    def _renderer_obj(self):
        if self._renderer is None:
            from mirage.media.render import PhotoRenderer

            self._renderer = PhotoRenderer()
        return self._renderer

    def _me_embedding(self) -> np.ndarray | None:
        me = self.settings.me_face_id
        if not me or self.library.get(me) is None:
            return None
        try:
            return self.library.embedding(me)
        except Exception:
            return None

    def _sources(self) -> list[SourceInfo]:
        return [SourceInfo(e.id, e.name, e.gender, e.age) for e in self.library.list()]

    def _fill_attributes(self) -> None:
        """Gender/age for library faces imported before suggestions existed (worker thread)."""
        import cv2

        from mirage.media.analyze import main_attributes

        for entry in self.library.list():
            if entry.gender is not None or entry.id in self._attrs_checked:
                continue
            self._attrs_checked.add(entry.id)
            try:
                data = np.fromfile(str(self.library.image_path(entry.id)), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_COLOR)
                gender, age = main_attributes(image)
                if gender is not None:
                    self.library.set_attributes(entry.id, gender, age)
            except Exception:
                log.exception("could not read attributes of %s", entry.id)

    def _enhance_field(self) -> str:
        return "video_enhance" if self.kind == VIDEO else "photo_enhance"

    # ── opening ──────────────────────────────────────────────────────────

    def open_dialog(self) -> None:
        if self.busy:
            return
        exts = "*.jpg *.jpeg *.png *.webp *.heic *.heif *.tif *.tiff *.bmp *.mp4 *.mov *.m4v *.mkv *.avi *.webm"
        files, _ = QFileDialog.getOpenFileNames(self, tr("menu_open_media"), str(Path.home() / "Pictures"),
                                                f"{tr('file_filter_media')} ({exts})")
        if files:
            self.open_paths([Path(f) for f in files])

    def open_paths(self, paths: list[Path]) -> None:
        from mirage.media import photo_io

        if self.busy:
            self._toast(tr("media_busy"), "warn")
            return
        images, videos = photo_io.collect_media(paths)
        if videos and not images and len(videos) == 1:
            self._open_video(videos[0])
        elif len(images) == 1 and not videos:
            self._open_photo(images[0])
        elif images:
            if videos:
                self._toast(tr("media_videos_one_at_a_time"), "warn")
            self._open_batch(images)
        elif videos:
            self._toast(tr("media_videos_one_at_a_time"), "warn")
            self._open_video(videos[0])
        else:
            self._toast(tr("media_nothing_to_open"), "warn")

    def _start(self, busy_text: str) -> int:
        self._token += 1
        self._cancel = threading.Event()
        self.busy = True
        self.result, self.saved_path = None, None
        self.view.active = None
        self.view.badge = ""
        self.view.show_original = False
        self.view.set_busy(busy_text)
        self._refresh()
        return self._token

    def _open_photo(self, path: Path) -> None:
        from mirage.media import photo_io
        from mirage.media.analyze import analyze_image

        token = self._start(tr("media_analyzing"))
        self.kind, self.path = PHOTO, path

        def work() -> None:
            try:
                image, meta = photo_io.load_image(path)
                targets = analyze_image(image)
                self._fill_attributes()
                self._analyzed.emit((token, PHOTO, image, meta, targets, None))
            except Exception as exc:
                log.exception("opening %s failed", path)
                self._analyzed.emit((token, PHOTO, None, None, [], exc))

        threading.Thread(target=work, name="mirage-analyze", daemon=True).start()

    def _open_video(self, path: Path) -> None:
        from mirage.media import video
        from mirage.media.analyze import analyze_image

        if video.find_ffmpeg() is None:
            self._toast(tr("media_ffmpeg_missing"), "error")
            return
        token = self._start(tr("media_analyzing"))
        self.kind, self.path = VIDEO, path

        def work() -> None:
            try:
                info = video.probe(path)
                best = None
                for _t, frame in video.sample_frames(path, info, 8):
                    faces = analyze_image(frame)
                    score = (max((f.area for f in faces), default=0.0), len(faces))
                    if best is None or score > best[0]:
                        best = (score, frame, faces)
                if best is None:
                    raise ValueError("no frames could be read")
                self._fill_attributes()
                self._analyzed.emit((token, VIDEO, best[1], info, best[2], None))
            except Exception as exc:
                log.exception("opening video %s failed", path)
                self._analyzed.emit((token, VIDEO, None, None, [], exc))

        threading.Thread(target=work, name="mirage-analyze-video", daemon=True).start()

    def _open_batch(self, paths: list[Path]) -> None:
        from mirage.media.batch import BatchItem

        self._token += 1
        self.kind, self.path = BATCH, None
        self.batch_items = [BatchItem(p) for p in paths]
        self.busy = False
        self.view.clear_busy()
        rows = [BatchRow(p.name, "waiting", _file_thumb(p) if i < 200 else None) for i, p in enumerate(paths)]
        self.view.show_batch(tr("media_batch_ready", n=len(paths)), rows)
        self._refresh()

    def _on_analyzed(self, payload) -> None:
        token, kind, image, extra, targets, error = payload
        if token != self._token:
            return
        self.busy = False
        self.view.clear_busy()
        if error is not None or image is None:
            name = self.path.name if self.path else ""
            self._toast(tr("media_failed", name=name, error=error), "error")
            self.kind = EMPTY
            self.view.show_empty()
            self._refresh()
            return
        self.image = image
        if kind == PHOTO:
            self.meta = extra
        else:
            self.video_info = extra
        self.targets = targets
        self.view.show_image(image, original=image)
        self.view.set_original(image)
        if not targets:
            self._toast(tr("media_no_faces"), "warn")
        self.plan = auto_plan(targets, (image.shape[1], image.shape[0]), self.settings.face_id, self._me_embedding())
        if targets and not assigned_count(self.plan):
            self._toast(tr("media_pick_face"), "info")
        self._relabel()
        self._refresh()

    # ── plan editing ─────────────────────────────────────────────────────

    def _relabel(self) -> None:
        labels: dict[int, FaceLabel] = {}
        for t in self.targets:
            sid = self.plan.get(t.index)
            entry = self.library.get(sid) if sid else None
            if entry is not None:
                labels[t.index] = FaceLabel(entry.name, _round_pixmap(self.library.thumb_path(entry.id), 40), True)
            else:
                labels[t.index] = FaceLabel(tr("media_keep"), None, False)
        self.view.set_faces(self.targets, labels)

    def _plan_changed(self) -> None:
        if self.result is not None:  # the rendered picture no longer matches the plan
            self.result, self.saved_path = None, None
            self.view.show_image(self.image, original=self.image)
            self.view.badge = ""
        self._relabel()
        self._refresh()

    def assign(self, index: int, source_id: str | None) -> None:
        if self.busy or index not in self.plan:
            return
        self.plan[index] = source_id
        self._plan_changed()

    def assign_everyone(self) -> None:
        if self.busy or self.kind not in (PHOTO, VIDEO) or not self.targets:
            return
        if not self.settings.face_id:
            self._toast(tr("media_pick_face"), "info")
            return
        self.plan = swap_everyone(self.targets, self.settings.face_id)
        self._plan_changed()

    def clear_active(self) -> None:
        self.view.active = None
        self.view.update()

    def pick_library(self, face_id: str | None) -> None:
        """A gallery click (or 0–9) while this mode is shown."""
        if self.busy or self.kind not in (PHOTO, VIDEO) or not self.targets:
            return
        if self.view.active is not None:
            self.assign(self.view.active, face_id)
            return
        if face_id is None:
            self.plan = {t.index: None for t in self.targets}
        elif assigned_count(self.plan):
            self.plan = {i: (face_id if v else None) for i, v in self.plan.items()}
        else:
            self.plan = auto_plan(self.targets, (self.image.shape[1], self.image.shape[0]), face_id,
                                  self._me_embedding())
        self._plan_changed()

    def _on_face_clicked(self, index: int, pos: QPointF) -> None:
        target = next((t for t in self.targets if t.index == index), None)
        if target is None or self.busy:
            return
        self.view.active = index
        self.view.update()
        menu = QMenu(self)
        desc = tr("media_face_n", n=index)
        if target.gender is not None and target.age is not None:
            desc += " · " + tr("media_face_desc", gender=tr("gender_m" if target.gender == 1 else "gender_f"),
                                age=int(round(target.age)))
        head = menu.addAction(desc)
        head.setEnabled(False)
        keep = menu.addAction(tr("media_keep"))
        keep.setCheckable(True)
        keep.setChecked(not self.plan.get(index))
        keep.triggered.connect(lambda: self.assign(index, None))
        menu.addSeparator()
        for source, _score, suggested in rank_sources(target, self._sources()):
            text = source.name + (f"   ★ {tr('media_suggested')}" if suggested else "")
            act = QAction(text, menu)
            pix = _round_pixmap(self.library.thumb_path(source.id), 32)
            if pix is not None:
                act.setIcon(QIcon(pix))
            act.setCheckable(True)
            act.setChecked(self.plan.get(index) == source.id)
            act.triggered.connect(lambda _c=False, sid=source.id: self.assign(index, sid))
            menu.addAction(act)
        menu.exec(pos.toPoint())
        self.clear_active()

    # ── actions ──────────────────────────────────────────────────────────

    def _on_primary(self) -> None:
        if self.kind == PHOTO:
            if self.busy:
                return
            if self.result is None:
                self.swap_photo()
            elif self.saved_path is None:
                self.save()
            else:
                self.reveal()
        elif self.kind == BATCH:
            if self.busy:
                self._cancel.set()
            elif all(i.status == "waiting" for i in self.batch_items):
                self.run_batch()
            else:
                self.reveal()
        elif self.kind == VIDEO:
            if self.busy:
                self._cancel.set()
            elif self.saved_path is None:
                self.render_video()
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path)))
        else:
            self.open_dialog()

    def _embeddings(self, ids) -> dict[str, np.ndarray]:
        return {sid: self.library.embedding(sid) for sid in set(ids) if sid and self.library.get(sid)}

    def _warn_if_live(self) -> None:
        if self.win.engine.state == "live" and not self._live_warned:
            self._live_warned = True
            self._toast(tr("media_live_slower"), "info")

    def swap_photo(self) -> None:
        if not assigned_count(self.plan):
            self._toast(tr("media_pick_face"), "info")
            return
        self._warn_if_live()
        token = self._token
        self.busy = True
        self.view.set_busy(tr("media_rendering"))
        self._refresh()
        image, targets, plan = self.image, list(self.targets), dict(self.plan)
        options = RenderOptions(enhance=self.settings.photo_enhance)
        embeddings = self._embeddings(plan.values())
        renderer = self._renderer_obj()

        def work() -> None:
            try:
                self._rendered.emit((token, renderer.render(image, targets, plan, embeddings, options), None))
            except Exception as exc:
                log.exception("photo render failed")
                self._rendered.emit((token, None, exc))

        threading.Thread(target=work, name="mirage-render", daemon=True).start()

    def _on_rendered(self, payload) -> None:
        token, result, error = payload
        if token != self._token:
            return
        self.busy = False
        self.view.clear_busy()
        if error is not None:
            self._toast(tr("media_failed", name=self.path.name if self.path else "", error=error), "error")
        else:
            self.result = result
            self.view.show_image(result, original=self.image)
            self.view.badge = tr("media_badge_swapped")
        self._refresh()

    def save(self) -> None:
        if self.result is None or self.path is None or self.busy:
            return
        from mirage.media import photo_io

        token = self._token
        self.busy = True
        self._refresh()
        result, path, meta = self.result, self.path, self.meta

        def work() -> None:
            try:
                self._saved.emit((token, photo_io.save_image(result, path, meta), None))
            except Exception as exc:
                log.exception("saving failed")
                self._saved.emit((token, None, exc))

        threading.Thread(target=work, name="mirage-save", daemon=True).start()

    def _on_saved(self, payload) -> None:
        token, out, error = payload
        if token != self._token:
            return
        self.busy = False
        if error is not None:
            self._toast(tr("media_failed", name=self.path.name if self.path else "", error=error), "error")
        else:
            self.saved_path = out
            self._toast(tr("media_saved", name=Path(out).name))
        self._refresh()

    def reveal(self) -> None:
        target = self.saved_path
        if self.kind == BATCH:
            target = next((i.output for i in self.batch_items if i.output), None)
        if target:
            subprocess.run(["open", "-R", str(target)], check=False)

    def compare(self, on: bool) -> None:
        if self.kind == PHOTO and self.result is not None:
            self.view.show_original = on
            self.view.update()

    # ── batch ────────────────────────────────────────────────────────────

    def run_batch(self) -> None:
        from mirage.media.batch import run_batch

        selected = self.settings.face_id
        if not selected:
            self._toast(tr("media_pick_face"), "info")
            return
        self._warn_if_live()
        token = self._start(tr("media_rendering"))
        self.view.clear_busy()
        self.kind = BATCH
        self.view.show_batch(tr("media_batch_progress", done=0, total=len(self.batch_items)), self.view.rows)
        me = self._me_embedding()
        embeddings = self._embeddings([selected])
        options = RenderOptions(enhance=self.settings.photo_enhance)
        items, cancel = self.batch_items, self._cancel
        renderer = self._renderer_obj()

        def plan_for(targets, size):
            return auto_plan(targets, size, selected, me)

        def work() -> None:
            run_batch(items, plan_for, embeddings, options,
                      on_update=lambda i, item: self._batchUpdate.emit((token, i, item.status, item.swapped)),
                      cancel=cancel, render=renderer.render)
            self._batchDone.emit((token, items))

        threading.Thread(target=work, name="mirage-batch", daemon=True).start()
        self._refresh()

    def _on_batch_update(self, payload) -> None:
        token, i, status, _swapped = payload
        if token != self._token or i >= len(self.view.rows):
            return
        self.view.rows[i].status = status
        done = sum(1 for r in self.view.rows if r.status not in ("waiting", "working"))
        self.view.batch_title = tr("media_batch_progress", done=done, total=len(self.view.rows))
        self.view.update()

    def _on_batch_done(self, payload) -> None:
        token, items = payload
        if token != self._token:
            return
        self.busy = False
        count = {s: sum(1 for i in items if i.status == s) for s in ("saved", "skipped", "no_face", "failed")}
        self.view.batch_title = tr("media_batch_done", saved=count["saved"],
                                   skipped=count["skipped"] + count["no_face"], failed=count["failed"])
        self._toast(self.view.batch_title, "warn" if count["failed"] else "info")
        self.view.update()
        self._refresh()

    # ── video ────────────────────────────────────────────────────────────

    def render_video(self) -> None:
        from mirage.media import video
        from mirage.media.types import VideoIdentity

        if not assigned_count(self.plan):
            self._toast(tr("media_pick_face"), "info")
            return
        self._warn_if_live()
        identities = []
        for t in self.targets:
            sid = self.plan.get(t.index)
            entry = self.library.get(sid) if sid else None
            if entry is not None:
                identities.append(VideoIdentity(t.embedding, self.library.embedding(sid), entry.name))
        token = self._token
        self.busy = True
        self._cancel = threading.Event()
        cancel = self._cancel
        src = self.path
        dst = video.output_path(src)
        options = RenderOptions(enhance=False, video_enhance=self.settings.video_enhance)
        self.view.set_busy(tr("media_rendering_video"), 0.0, "")
        self._refresh()

        def work() -> None:
            try:
                out = video.render_video(src, dst, identities, options,
                                         progress=lambda pr: self._videoProgress.emit((token, pr)), cancel=cancel)
                self._videoDone.emit((token, out, None))
            except Exception as exc:
                if not isinstance(exc, getattr(video, "VideoCancelled", ())):
                    log.exception("video render failed")
                self._videoDone.emit((token, None, exc))

        threading.Thread(target=work, name="mirage-video", daemon=True).start()

    def _on_video_progress(self, payload) -> None:
        token, pr = payload
        if token != self._token or not self.busy:
            return
        total = max(1, pr.total or 1)
        text = tr("media_video_progress", done=pr.done, total=pr.total or "?", fps=pr.fps, eta=_fmt_eta(pr.eta_seconds))
        self.view.set_busy(tr("media_rendering_video"), pr.done / total, text)

    def _on_video_done(self, payload) -> None:
        from mirage.media import video

        token, out, error = payload
        if token != self._token:
            return
        self.busy = False
        self.view.clear_busy()
        if error is not None:
            if isinstance(error, getattr(video, "VideoCancelled", ())):
                self._toast(tr("media_video_cancelled"))
            else:
                self._toast(tr("media_failed", name=self.path.name if self.path else "", error=error), "error")
        else:
            self.saved_path = Path(out)
            self._toast(tr("media_video_done", name=self.saved_path.name))
        self._refresh()

    # ── chrome ───────────────────────────────────────────────────────────

    def _on_enhance(self, on: bool) -> None:
        self.win._set(self._enhance_field(), bool(on))

    def _refresh(self) -> None:
        """Buttons follow the state: one obvious next step."""
        kind, busy = self.kind, self.busy
        has_faces = bool(self.targets) and kind in (PHOTO, VIDEO)
        self.everyone_btn.setVisible(has_faces and not busy)
        self.compare_btn.setVisible(kind == PHOTO and self.result is not None)
        self.finder_btn.setVisible(bool(self.saved_path) or (kind == BATCH and any(i.output for i in self.batch_items)))
        show_enhance = kind in (PHOTO, BATCH, VIDEO)
        self.enhance.setVisible(show_enhance)
        self.enhance_label.setVisible(show_enhance)
        if show_enhance:
            self.enhance.blockSignals(True)
            self.enhance.setChecked(bool(getattr(self.settings, self._enhance_field())))
            self.enhance.blockSignals(False)
            self.enhance_label.setText(tr("media_enhance_video" if kind == VIDEO else "media_enhance"))
        self.open_btn.setEnabled(not busy)
        if kind == EMPTY:
            self.primary.set_mode("start", tr("media_open"), icon="plus")
        elif kind == PHOTO:
            if busy:
                self.primary.set_mode("busy", tr("media_working"))
            elif self.result is None:
                self.primary.set_mode("start", tr("media_swap"), icon="swap")
            elif self.saved_path is None:
                self.primary.set_mode("start", tr("media_save"), icon="save")
            else:
                self.primary.set_mode("start", tr("media_show_in_finder"), icon="folder")
        elif kind == BATCH:
            if busy:
                self.primary.set_mode("stop", tr("media_cancel"))
            elif all(i.status == "waiting" for i in self.batch_items):
                self.primary.set_mode("start", tr("media_process_all", n=len(self.batch_items)), icon="swap")
            else:
                self.primary.set_mode("start", tr("media_show_in_finder"), icon="folder")
        elif kind == VIDEO:
            if busy and self.video_info is None:
                self.primary.set_mode("busy", tr("media_working"))
            elif busy:
                self.primary.set_mode("stop", tr("media_cancel"))
            elif self.saved_path is None:
                self.primary.set_mode("start", tr("media_render_video"), icon="film")
            else:
                self.primary.set_mode("start", tr("media_open_video"), icon="film")

    def leave(self) -> None:
        """Leaving the mode: free GFPGAN's memory unless something is still running."""
        if not self.busy and self._renderer is not None:
            self._renderer.release()
