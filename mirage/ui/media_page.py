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


def _gfpgan_present() -> bool:
    from mirage.paths import models_dir

    return (models_dir() / "gfpgan-1024.onnx").exists()


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
    _thumbs = Signal(object)
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
        self._enhance_warned = False
        self._job: threading.Thread | None = None
        self._release_when_idle = False
        # The face to wear in this mode. Separate from Live's, so editing
        # photos never changes (or turns off) the face in a running call.
        self.selected_id: str | None = window.settings.face_id

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
        self._thumbs.connect(self._on_thumbs)
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

    def _run(self, target, name: str) -> None:
        self._job = threading.Thread(target=target, name=name, daemon=True)
        self._job.start()

    def _selected_is_me(self) -> bool:
        return bool(self.selected_id) and self.selected_id == self.settings.me_face_id

    def _auto_plan(self, targets, size) -> Plan:
        return auto_plan(targets, size, self.selected_id, self._me_embedding(), self._selected_is_me())

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

        self.kind, self.path, self.video_info, self.targets, self.plan = PHOTO, path, None, [], {}
        token = self._start(tr("media_analyzing"))

        def work() -> None:
            try:
                image, meta = photo_io.load_image(path)
                targets = analyze_image(image)
                self._fill_attributes()
                self._analyzed.emit((token, PHOTO, image, meta, targets, None))
            except Exception as exc:
                log.exception("opening %s failed", path)
                self._analyzed.emit((token, PHOTO, None, None, [], exc))

        self._run(work, "mirage-analyze")

    def _open_video(self, path: Path) -> None:
        from mirage.media import video
        from mirage.media.analyze import analyze_image

        if video.find_ffmpeg() is None:
            self._toast(tr("media_ffmpeg_missing"), "error")
            return
        self.kind, self.path, self.video_info, self.targets, self.plan = VIDEO, path, None, [], {}
        token = self._start(tr("media_analyzing"))

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

        self._run(work, "mirage-analyze-video")

    def _open_batch(self, paths: list[Path]) -> None:
        from mirage.media.batch import BatchItem

        self._token += 1
        self.kind, self.path = BATCH, None
        self.batch_items = [BatchItem(p) for p in paths]
        self.busy = False
        self.view.clear_busy()
        rows = [BatchRow(p.name, "waiting") for p in paths]
        self.view.show_batch(tr("media_batch_ready", n=len(paths)), rows)
        self._refresh()
        token = self._token

        def load_thumbs() -> None:
            from PySide6.QtGui import QImage

            thumbs = {}
            for i, p in enumerate(paths[:300]):
                reader = QImageReader(str(p))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid() and size.width() > 0:
                    scale = 72 / max(1, min(size.width(), size.height()))
                    reader.setScaledSize(QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
                image: QImage = reader.read()
                if not image.isNull():
                    thumbs[i] = image
            self._thumbs.emit((token, thumbs))

        threading.Thread(target=load_thumbs, name="mirage-thumbs", daemon=True).start()

    def _on_thumbs(self, payload) -> None:
        token, thumbs = payload
        if token != self._token or self.kind != BATCH:
            return
        for i, image in thumbs.items():
            if i < len(self.view.rows):
                self.view.rows[i].thumb = QPixmap.fromImage(image)
        self.view.update()

    def _on_analyzed(self, payload) -> None:
        token, kind, image, extra, targets, error = payload
        if token != self._token:
            return
        self._job_finished()
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
        self.plan = self._auto_plan(targets, (image.shape[1], image.shape[0]))
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
        self._invalidate_output()
        self._relabel()
        self._refresh()

    def _invalidate_output(self) -> None:
        """The rendered photo / saved video no longer matches what the user asked for."""
        if self.result is not None:
            self.result = None
            self.view.show_image(self.image, original=self.image)
            self.view.badge = ""
        if self.kind in (PHOTO, VIDEO):
            self.saved_path = None

    def assign(self, index: int, source_id: str | None) -> None:
        if self.busy or index not in self.plan:
            return
        self.plan[index] = source_id
        self._plan_changed()

    def assign_everyone(self) -> None:
        if self.busy or self.kind not in (PHOTO, VIDEO) or not self.targets:
            return
        if not self.selected_id:
            self._toast(tr("media_pick_face"), "info")
            return
        self.plan = swap_everyone(self.targets, self.selected_id)
        self._plan_changed()

    def clear_active(self) -> None:
        self.view.active = None
        self.view.update()

    def pick_library(self, face_id: str | None) -> bool:
        """A gallery click (or 0–9) while this mode is shown. Returns True if it
        went to the face highlighted in the photo (the selection didn't change)."""
        if self.view.active is not None and self.kind in (PHOTO, VIDEO) and not self.busy:
            self.assign(self.view.active, face_id)
            return True
        self.selected_id = face_id
        if self.busy or self.kind not in (PHOTO, VIDEO) or not self.targets:
            return False
        if face_id is None:
            self.plan = {t.index: None for t in self.targets}
        elif assigned_count(self.plan):
            self.plan = {i: (face_id if v else None) for i, v in self.plan.items()}
        else:
            self.plan = self._auto_plan(self.targets, (self.image.shape[1], self.image.shape[0]))
        self._plan_changed()
        return False

    def on_face_removed(self, face_id: str) -> None:
        """A library face was deleted: drop it from the plan and the selection."""
        if self.selected_id == face_id:
            self.selected_id = None
        if any(v == face_id for v in self.plan.values()):
            self.plan = {i: (None if v == face_id else v) for i, v in self.plan.items()}
            if not self.busy:
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
        chosen = menu.exec(pos.toPoint())
        if chosen is not None:
            self.clear_active()
        # Dismissed without a choice: the face stays highlighted, so a gallery
        # click or 1–9 assigns to it (Esc or a click elsewhere clears it).

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
            elif any(i.status == "waiting" for i in self.batch_items):
                self.run_batch()
            elif any(i.output for i in self.batch_items):
                self.reveal()
            else:
                self.open_dialog()
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
        try:
            embeddings = self._embeddings(self.plan.values())
        except Exception as exc:
            log.exception("could not load face embeddings")
            self._toast(tr("media_failed", name=self.path.name if self.path else "", error=exc), "error")
            return
        self._warn_if_live()
        token = self._token
        self.busy = True
        enhance = self.settings.photo_enhance
        self.view.set_busy(tr("media_downloading_enhancer") if enhance and not _gfpgan_present()
                           else tr("media_rendering"))
        self._refresh()
        image, targets, plan = self.image, list(self.targets), dict(self.plan)
        options = RenderOptions(enhance=enhance)
        renderer = self._renderer_obj()

        def work() -> None:
            try:
                self._rendered.emit((token, renderer.render(image, targets, plan, embeddings, options), None))
            except Exception as exc:
                log.exception("photo render failed")
                self._rendered.emit((token, None, exc))

        self._run(work, "mirage-render")

    def _on_rendered(self, payload) -> None:
        token, result, error = payload
        if token != self._token:
            return
        self._job_finished()
        self.view.clear_busy()
        if self._renderer is not None and self._renderer.enhance_failed and not self._enhance_warned:
            self._enhance_warned = True
            self._toast(tr("media_enhance_failed"), "warn")
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
        if self.saved_path is not None:  # ⌘S again: don't write -mirage-2, -mirage-3…
            self._toast(tr("media_saved", name=Path(self.saved_path).name))
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

        self._run(work, "mirage-save")

    def _on_saved(self, payload) -> None:
        token, out, error = payload
        if token != self._token:
            return
        self._job_finished()
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

        selected = self.selected_id
        if not selected:
            self._toast(tr("media_pick_face"), "info")
            return
        self._warn_if_live()
        # Continue where a cancelled run stopped: only the files still waiting.
        pending = [(i, item) for i, item in enumerate(self.batch_items) if item.status == "waiting"]
        rows = self.view.rows
        self._token += 1
        token = self._token
        self._cancel = threading.Event()
        self.busy = True
        self.view.show_batch(tr("media_batch_progress", done=len(self.batch_items) - len(pending),
                                total=len(self.batch_items)), rows)
        me, selected_is_me = self._me_embedding(), self._selected_is_me()
        embeddings = self._embeddings([selected])
        options = RenderOptions(enhance=self.settings.photo_enhance)
        cancel = self._cancel
        renderer = self._renderer_obj()
        index_of = [i for i, _item in pending]

        def plan_for(targets, size):
            return auto_plan(targets, size, selected, me, selected_is_me)

        def work() -> None:
            run_batch([item for _i, item in pending], plan_for, embeddings, options,
                      on_update=lambda j, item: self._batchUpdate.emit(
                          (token, index_of[j], item.status, item.error)),
                      cancel=cancel, render=renderer.render)
            self._batchDone.emit((token, self.batch_items))

        self._run(work, "mirage-batch")
        self._refresh()

    def _on_batch_update(self, payload) -> None:
        token, i, status, error = payload
        if token != self._token or i >= len(self.view.rows):
            return
        self.view.rows[i].status = status
        self.view.rows[i].detail = str(error)[:80] if error else ""
        done = sum(1 for r in self.view.rows if r.status not in ("waiting", "working"))
        self.view.batch_title = tr("media_batch_progress", done=done, total=len(self.view.rows))
        self.view.update()

    def _on_batch_done(self, payload) -> None:
        token, items = payload
        if token != self._token:
            return
        self._job_finished()
        count = {s: sum(1 for i in items if i.status == s) for s in ("saved", "skipped", "no_face", "failed", "waiting")}
        if count["waiting"]:
            self.view.batch_title = tr("media_batch_stopped", saved=count["saved"], left=count["waiting"])
        else:
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
        if self._renderer is not None:
            self._renderer.release()  # video doesn't use GFPGAN: give its ~1.5 GB back first
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

        self._run(work, "mirage-video")

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
        self._job_finished()
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
        self._invalidate_output()  # the result on screen was made with the other setting
        self._refresh()

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
            waiting = sum(1 for i in self.batch_items if i.status == "waiting")
            if busy:
                self.primary.set_mode("stop", tr("media_cancel"))
            elif waiting == len(self.batch_items):
                self.primary.set_mode("start", tr("media_process_all", n=waiting), icon="swap")
            elif waiting:
                self.primary.set_mode("start", tr("media_continue", n=waiting), icon="swap")
            elif any(i.output for i in self.batch_items):
                self.primary.set_mode("start", tr("media_show_in_finder"), icon="folder")
            else:
                self.primary.set_mode("start", tr("media_open"), icon="plus")
        elif kind == VIDEO:
            if busy and self.video_info is None:
                self.primary.set_mode("busy", tr("media_working"))
            elif busy:
                self.primary.set_mode("stop", tr("media_cancel"))
            elif self.saved_path is None:
                self.primary.set_mode("start", tr("media_render_video"), icon="film")
            else:
                self.primary.set_mode("start", tr("media_open_video"), icon="film")

    def _job_finished(self) -> None:
        self.busy = False
        if self._release_when_idle and not self.isVisible() and self._renderer is not None:
            self._release_when_idle = False
            self._renderer.release()

    def leave(self) -> None:
        """Leaving the mode: free GFPGAN's memory now, or as soon as the running job ends."""
        if self._renderer is None:
            return
        if self.busy:
            self._release_when_idle = True
        else:
            self._renderer.release()

    def shutdown(self, timeout: float = 8.0) -> None:
        """App is quitting: cancel a running job (a video removes its partial file) and wait."""
        self._cancel.set()
        job = self._job
        if job is not None and job.is_alive():
            job.join(timeout)
