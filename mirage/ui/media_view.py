"""The Photos & videos stage: the picture, its faces and who they become."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.media.types import TargetFace
from mirage.ui.widgets import draw_icon

STATUS_COLORS = {
    "waiting": theme.TEXT_TERTIARY, "working": theme.ACCENT_2, "saved": theme.READY,
    "no_face": theme.WARN, "skipped": theme.TEXT_TERTIARY, "failed": theme.LIVE,
}


def to_qimage(bgr: np.ndarray) -> tuple[QImage, np.ndarray]:
    bgr = np.ascontiguousarray(bgr)
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format.Format_BGR888), bgr


@dataclass
class FaceLabel:
    text: str
    avatar: QPixmap | None
    assigned: bool


@dataclass
class BatchRow:
    name: str
    status: str
    thumb: QPixmap | None = None
    detail: str = ""


class MediaView(QWidget):
    faceClicked = Signal(int, QPointF)      # target index, global position
    backgroundClicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(560, 340)
        self.mode = "empty"                   # empty | busy | image | batch
        self.busy_text = ""
        self.progress: float | None = None     # 0..1 for a progress bar under the busy text
        self.progress_text = ""
        self.drop_active = False
        self._image: QImage | None = None
        self._image_buf = None
        self._original: QImage | None = None
        self._original_buf = None
        self.show_original = False
        self.targets: list[TargetFace] = []
        self.labels: dict[int, FaceLabel] = {}
        self.active: int | None = None
        self.badge = ""                        # small chip at the top-left, e.g. "Original" / "Swapped"
        self.rows: list[BatchRow] = []
        self.batch_title = ""
        self._scroll = 0
        self._hover: int | None = None
        self._spin = 0.0
        self._spinner = QTimer(self)
        self._spinner.setInterval(16)
        self._spinner.timeout.connect(self._tick)

    # ── state ────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._spin = (self._spin + 6) % 360
        self.update()

    def set_busy(self, text: str, progress: float | None = None, progress_text: str = "") -> None:
        self.busy_text, self.progress, self.progress_text = text, progress, progress_text
        if not self._spinner.isActive():
            self._spinner.start()
        self.update()

    def clear_busy(self) -> None:
        self.busy_text, self.progress, self.progress_text = "", None, ""
        self._spinner.stop()
        self.update()

    def show_empty(self) -> None:
        self.mode = "empty"
        self._image = self._original = None
        self.targets, self.labels, self.rows = [], {}, []
        self.active = None
        self.clear_busy()

    def show_image(self, image: np.ndarray, original: np.ndarray | None = None) -> None:
        self.mode = "image"
        self._image, self._image_buf = to_qimage(image)
        if original is not None:
            self._original, self._original_buf = to_qimage(original)
        elif self._original is None:
            self._original, self._original_buf = self._image, self._image_buf
        self.update()

    def set_original(self, original: np.ndarray) -> None:
        self._original, self._original_buf = to_qimage(original)

    def set_faces(self, targets: list[TargetFace], labels: dict[int, FaceLabel]) -> None:
        self.targets, self.labels = targets, labels
        if self.active is not None and all(t.index != self.active for t in targets):
            self.active = None
        self.update()

    def show_batch(self, title: str, rows: list[BatchRow]) -> None:
        self.mode = "batch"
        self.batch_title, self.rows = title, rows
        self.update()

    def set_drop_active(self, on: bool) -> None:
        self.drop_active = on
        self.update()

    # ── geometry ─────────────────────────────────────────────────────────

    def _area(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def _image_rect(self) -> QRectF:
        img = self._shown()
        area = self._area().adjusted(18, 18, -18, -54)
        if img is None or img.width() == 0:
            return area
        scale = min(area.width() / img.width(), area.height() / img.height())
        w, h = img.width() * scale, img.height() * scale
        return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)

    def _shown(self) -> QImage | None:
        return self._original if (self.show_original and self._original is not None) else self._image

    def _face_rect(self, t: TargetFace) -> QRectF:
        img = self._shown()
        r = self._image_rect()
        if img is None or img.width() == 0:
            return QRectF()
        s = r.width() / img.width()
        x1, y1, x2, y2 = t.bbox
        return QRectF(r.left() + x1 * s, r.top() + y1 * s, (x2 - x1) * s, (y2 - y1) * s).adjusted(-6, -6, 6, 6)

    def _face_at(self, pos: QPointF) -> int | None:
        if self.mode != "image" or self.busy_text:
            return None
        hits = [t for t in self.targets if self._face_rect(t).contains(pos)]
        return min(hits, key=lambda t: t.area).index if hits else None

    # ── input ────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        hit = self._face_at(e.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self.mode == "batch" and self.rows:
            self._scroll = max(0, self._scroll - int(e.angleDelta().y() / 40))
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._face_at(e.position())
        if hit is not None:
            self.faceClicked.emit(hit, QPointF(e.globalPosition()))
        else:
            self.backgroundClicked.emit()

    # ── painting ─────────────────────────────────────────────────────────

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self._area()
        radius = theme.RADIUS_STAGE - 8
        clip = QPainterPath()
        clip.addRoundedRect(area, radius, radius)
        p.setClipPath(clip)
        p.fillRect(area, theme.STAGE_BG)
        if self.mode == "image" and self._shown() is not None:
            self._paint_image(p)
        elif self.mode == "batch":
            self._paint_batch(p, area)
        elif not self.busy_text:
            self._paint_empty(p, area)
        p.setClipping(False)
        if self.busy_text:
            self._paint_busy(p, area)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self.drop_active:
            p.setBrush(QColor(12, 12, 20, 170))
            p.setPen(QPen(theme.ACCENT, 2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(area.adjusted(6, 6, -6, -6), radius - 4, radius - 4)
            self._text(p, area, area.center().y() - 14, tr("media_empty_title"), 17, theme.TEXT, bold=True)

    def _text(self, p: QPainter, r: QRectF, y: float, text: str, size: float, color: QColor,
              bold: bool = False) -> None:
        p.setFont(theme.font(size, theme.QFont.Weight.DemiBold if bold else theme.QFont.Weight.Normal))
        p.setPen(color)
        p.drawText(QRectF(r.left() + 40, y, r.width() - 80, size * 2.4),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)

    def _chip(self, p: QPainter, text: str, x: float, y: float, dot: QColor | None = None,
              avatar: QPixmap | None = None, strong: bool = False) -> QRectF:
        p.setFont(theme.font(11.5, theme.QFont.Weight.DemiBold if strong else theme.QFont.Weight.Medium))
        tw = p.fontMetrics().horizontalAdvance(text)
        h = 26.0
        lead = 24.0 if avatar is not None else (14.0 if dot is not None else 0.0)
        rect = QRectF(x, y, tw + 20 + lead, h)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.setBrush(QColor(12, 12, 20, 185))
        p.drawRoundedRect(rect, h / 2, h / 2)
        tx = rect.left() + 10
        if avatar is not None:
            circle = QRectF(rect.left() + 4, rect.top() + 3, 20, 20)
            clip = QPainterPath()
            clip.addEllipse(circle)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(circle.toRect(), avatar)
            p.restore()
            tx = circle.right() + 6
        elif dot is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(tx + 3, rect.center().y()), 4, 4)
            tx += 12
        p.setPen(theme.TEXT)
        p.drawText(QRectF(tx, rect.top(), tw + 4, h), Qt.AlignmentFlag.AlignVCenter, text)
        return rect

    def _paint_image(self, p: QPainter) -> None:
        img = self._shown()
        r = self._image_rect()
        p.drawImage(r, img)
        if self.badge or self.show_original:
            self._chip(p, tr("media_original") if self.show_original else self.badge,
                       self._area().left() + 16, self._area().top() + 16, strong=True)
        if self.show_original or self.busy_text:
            return
        for t in self.targets:
            fr = self._face_rect(t)
            label = self.labels.get(t.index)
            assigned = bool(label and label.assigned)
            active = t.index == self.active
            hover = t.index == self._hover
            color = theme.ACCENT if assigned else QColor(255, 255, 255, 200 if (hover or active) else 120)
            width = 3.0 if (active or assigned) else (2.0 if hover else 1.4)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if active:
                p.setPen(QPen(QColor(theme.ACCENT_2), 6))
                glow = QColor(theme.ACCENT_2)
                glow.setAlpha(70)
                p.setPen(QPen(glow, 8))
                p.drawRoundedRect(fr, 14, 14)
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine if assigned or active else Qt.PenStyle.DashLine))
            p.drawRoundedRect(fr, 14, 14)
            badge = QRectF(fr.left() - 10, fr.top() - 10, 22, 22)
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.setBrush(theme.ACCENT if assigned else QColor(20, 20, 30, 220))
            p.drawEllipse(badge)
            p.setPen(theme.TEXT)
            p.setFont(theme.font(10.5, theme.QFont.Weight.Bold))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(t.index))
            if label is not None:
                self._chip(p, label.text, fr.left(), fr.bottom() + 6, avatar=label.avatar, strong=assigned)

    def _paint_empty(self, p: QPainter, area: QRectF) -> None:
        zone = area.adjusted(28, 28, -28, -28)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(zone, 22, 22)
        c = zone.center()
        disc = QRectF(0, 0, 84, 84)
        disc.moveCenter(QPointF(c.x(), c.y() - 64))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(disc)
        draw_icon(p, "photo", disc.adjusted(22, 22, -22, -22), QColor(255, 255, 255, 220))
        self._text(p, zone, c.y() - 4, tr("media_empty_title"), 19, theme.TEXT, bold=True)
        self._text(p, zone, c.y() + 32, tr("media_empty_subtitle"), 13, theme.TEXT_SECONDARY)

    def _paint_busy(self, p: QPainter, area: QRectF) -> None:
        panel = QRectF(0, 0, min(460.0, area.width() - 60), 132 if self.progress is not None else 108)
        panel.moveCenter(area.center())
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(14, 14, 22, 215))
        p.drawRoundedRect(panel, 20, 20)
        ring = QRectF(0, 0, 30, 30)
        ring.moveCenter(QPointF(panel.center().x(), panel.top() + 30))
        p.setPen(QPen(QColor(255, 255, 255, 40), 3))
        p.drawEllipse(ring)
        p.setPen(QPen(QColor(255, 255, 255, 230), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, int(-self._spin * 16), 100 * 16)
        self._text(p, panel, panel.top() + 54, self.busy_text, 14, theme.TEXT, bold=True)
        if self.progress is not None:
            bar = QRectF(panel.left() + 28, panel.top() + 88, panel.width() - 56, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(bar, 3, 3)
            fill = QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, self.progress)), bar.height())
            p.setBrush(theme.ACCENT)
            p.drawRoundedRect(fill, 3, 3)
            self._text(p, panel, bar.bottom() + 8, self.progress_text, 11.5, theme.TEXT_SECONDARY)

    def _paint_batch(self, p: QPainter, area: QRectF) -> None:
        self._text(p, area, area.top() + 22, self.batch_title, 16, theme.TEXT, bold=True)
        top = area.top() + 64
        row_h = 54.0
        visible = int((area.height() - 80) // row_h)
        rows = self.rows
        # keep the row being worked on in view; otherwise the wheel scrolls
        working = next((i for i, r in enumerate(rows) if r.status == "working"), None)
        target = working - visible // 2 if working is not None else self._scroll
        first = max(0, min(target, len(rows) - visible))
        self._scroll = first
        for i, row in enumerate(rows[first:first + visible]):
            y = top + i * row_h
            box = QRectF(area.left() + 24, y, area.width() - 48, row_h - 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(box, 12, 12)
            thumb = QRectF(box.left() + 8, box.top() + 5, 36, 36)
            if row.thumb is not None:
                clip = QPainterPath()
                clip.addRoundedRect(thumb, 8, 8)
                p.save()
                p.setClipPath(clip)
                p.drawPixmap(thumb.toRect(), row.thumb)
                p.restore()
            p.setFont(theme.font(12.5, theme.QFont.Weight.Medium))
            p.setPen(theme.TEXT)
            name = p.fontMetrics().elidedText(row.name, Qt.TextElideMode.ElideMiddle, int(box.width() * 0.5))
            p.drawText(QRectF(thumb.right() + 12, box.top(), box.width() * 0.55, box.height()),
                       Qt.AlignmentFlag.AlignVCenter, name)
            status = tr(f"media_status_{row.status}") + (f" · {row.detail}" if row.detail else "")
            p.setFont(theme.font(11.5))
            fm = p.fontMetrics()
            sw = fm.horizontalAdvance(status)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(STATUS_COLORS.get(row.status, theme.TEXT_TERTIARY))
            p.drawEllipse(QPointF(box.right() - sw - 26, box.center().y()), 4, 4)
            p.setPen(theme.TEXT_SECONDARY)
            p.drawText(QRectF(box.right() - sw - 16, box.top(), sw + 4, box.height()), Qt.AlignmentFlag.AlignVCenter, status)


def now() -> float:
    return time.monotonic()
