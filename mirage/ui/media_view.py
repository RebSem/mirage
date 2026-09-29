"""The Photos & videos stage: the picture, its faces and who they become."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.media.types import TargetFace
from mirage.ui.widgets import CHIP_H, chip_width, draw_chip, draw_icon

STATUS_COLORS = {
    "waiting": theme.TEXT_TERTIARY, "working": theme.ACCENT_2, "saved": theme.READY,
    "no_face": theme.WARN, "skipped": theme.TEXT_TERTIARY, "failed": theme.LIVE,
}
PHOTO_RADIUS = 12.0
ROW_H = 64.0


def to_qimage(bgr: np.ndarray) -> tuple[QImage, np.ndarray]:
    bgr = np.ascontiguousarray(bgr)
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format.Format_BGR888), bgr


def face_letter(index: int) -> str:
    """Faces in a photo are lettered (A, B, C…) so they never look like the gallery's 1–9 shortcuts."""
    return chr(64 + index) if 1 <= index <= 26 else str(index)


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
        self.badge = ""                        # chip on the photo's corner, e.g. "Swapped"
        self.rows: list[BatchRow] = []
        self.batch_title = ""
        self.batch_subtitle = ""
        self.batch_progress: float | None = None
        self._scroll = 0
        self._wheel = 0.0
        self._hover: int | None = None
        self._hover_empty = False
        self._chip_hits: list[tuple[QRectF, int]] = []
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

    def show_batch(self, title: str, rows: list[BatchRow], subtitle: str = "", progress: float | None = None) -> None:
        self.mode = "batch"
        self.batch_title, self.rows = title, rows
        self.batch_subtitle, self.batch_progress = subtitle, progress
        self.update()

    def set_drop_active(self, on: bool) -> None:
        self.drop_active = on
        self.update()

    # ── geometry ─────────────────────────────────────────────────────────

    def _area(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def _image_rect(self) -> QRectF:
        img = self._shown()
        area = self._area().adjusted(20, 20, -20, -20)
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
        face = QRectF(r.left() + x1 * s, r.top() + y1 * s, (x2 - x1) * s, (y2 - y1) * s).adjusted(-6, -6, 6, 6)
        return face.intersected(r.adjusted(2, 2, -2, -2))  # outlines never leave the photo

    def _face_at(self, pos: QPointF) -> int | None:
        if self.mode != "image" or self.busy_text:
            return None
        hits = [t for t in self.targets if self._face_rect(t).contains(pos)]
        if hits:
            return min(hits, key=lambda t: t.area).index
        for rect, index in self._chip_hits:      # off every face, a chip still belongs to its face
            if rect.contains(pos):
                return index
        return None

    # ── input ────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        hit = self._face_at(e.position())
        empty = self.mode == "empty" and not self.busy_text
        if hit != self._hover or empty != self._hover_empty:
            self._hover, self._hover_empty = hit, empty
            clickable = hit is not None or empty
            self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self.mode != "batch" or not self.rows:
            return
        if e.phase() != Qt.ScrollPhase.NoScrollPhase and not e.pixelDelta().isNull():
            # trackpad: many small pixel deltas, added up one row at a time
            self._wheel += e.pixelDelta().y()
            steps = int(self._wheel / ROW_H)
            self._wheel -= steps * ROW_H
        else:
            steps = round(e.angleDelta().y() / 120 * 3)   # a wheel notch moves three rows
        if steps:
            self._scroll = max(0, self._scroll - steps)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover, self._hover_empty = None, False
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
        if self.busy_text:
            self._paint_busy(p, area)
        p.setClipping(False)
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

    # photo ----------------------------------------------------------------

    def _paint_image(self, p: QPainter) -> None:
        img = self._shown()
        r = self._image_rect()
        frame = QPainterPath()
        frame.addRoundedRect(r, PHOTO_RADIUS, PHOTO_RADIUS)
        p.save()
        p.setClipPath(frame, Qt.ClipOperation.IntersectClip)
        p.drawImage(r, img)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), PHOTO_RADIUS, PHOTO_RADIUS)

        self._chip_hits = []
        # the state chip labels the photo: above it when there is room, else on its corner
        area = self._area()
        room_above = r.top() - area.top() >= CHIP_H + 20
        corner = QPointF(r.left(), r.top() - CHIP_H - 10) if room_above else QPointF(r.left() + 12, r.top() + 12)
        state = None
        if self.show_original:
            state = (tr("media_original"), None, "light")
        elif self.badge:
            text = self.badge
            if chip_width(text, dot=True, strong=True) > r.width() - 24:
                text = text.split(" · ")[0]      # "Swapped" without the hint when the photo is narrow
            state = (text, theme.ACCENT_2, "dark")
        reserved: list[QRectF] = []
        if state is not None:
            reserved.append(QRectF(corner.x(), corner.y(), chip_width(state[0], dot=state[1] is not None, strong=True), CHIP_H))

        if not (self.show_original or self.busy_text):
            # pass 1: every face's marks and letter; pass 2: every chip, above all marks
            for t in self.targets:
                fr = self._face_rect(t)
                if not fr.isEmpty():
                    reserved.append(self._paint_marks(p, t, fr))
            for t, rect in self._layout_chips(reserved):
                self._draw_face_chip(p, t, rect)
                self._chip_hits.append((rect, t.index))
        if state is not None:
            draw_chip(p, corner.x(), corner.y(), state[0], dot=state[1], strong=True, tone=state[2])

    def _draw_face_chip(self, p: QPainter, t: TargetFace, rect: QRectF) -> None:
        label = self.labels.get(t.index)
        if label is not None and label.assigned:
            draw_chip(p, rect.left(), rect.top(), label.text, avatar=label.avatar, strong=True)
        else:
            draw_chip(p, rect.left(), rect.top(), tr("media_choose_face"), tone="quiet")

    def _paint_marks(self, p: QPainter, t: TargetFace, fr: QRectF) -> QRectF:
        """Outline or corner marks plus the letter; returns the letter's rect (chips keep off it)."""
        label = self.labels.get(t.index)
        assigned = bool(label and label.assigned)
        active, hover = t.index == self.active, t.index == self._hover
        rad = min(14.0, min(fr.width(), fr.height()) * 0.18)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if active:
            glow = QColor(theme.ACCENT_2)
            glow.setAlpha(70)
            p.setPen(QPen(glow, 8))
            p.drawRoundedRect(fr, rad, rad)
        if assigned or active:
            p.setPen(QPen(QColor(0, 0, 0, 70), 4.5))    # a soft halo keeps it readable on skin and white walls
            p.drawRoundedRect(fr, rad, rad)
            grad = QLinearGradient(fr.topLeft(), fr.bottomRight())
            grad.setColorAt(0, theme.ACCENT_2 if active else theme.ACCENT)
            grad.setColorAt(1, theme.ACCENT_2)
            p.setPen(QPen(QBrush(grad), 2.25))
            p.drawRoundedRect(fr, rad, rad)
        else:
            self._brackets(p, fr, QColor(255, 255, 255, 235 if hover else 190))
        # the letter sits on the top-left corner, inside the photo
        inside = self._image_rect().adjusted(4, 4, -4, -4)
        badge = QRectF(0, 0, 22, 22)
        badge.moveCenter(QPointF(max(fr.left(), inside.left() + 11), max(fr.top(), inside.top() + 11)))
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        p.setBrush(theme.ACCENT if assigned else QColor(20, 20, 30, 225))
        p.drawEllipse(badge)
        p.setPen(theme.TEXT)
        p.setFont(theme.font(10.5, theme.QFont.Weight.Bold))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, face_letter(t.index))
        return badge

    @staticmethod
    def _brackets(p: QPainter, r: QRectF, color: QColor) -> None:
        """Four corner marks: a face was found here and is left as it is."""
        arm = max(8.0, min(24.0, min(r.width(), r.height()) * 0.18))
        corners = ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                   (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1))
        for pen in (QPen(QColor(0, 0, 0, 90), 4.0), QPen(color, 2.0)):
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            for cx, cy, dx, dy in corners:
                p.drawPolyline([QPointF(cx, cy + dy * arm), QPointF(cx, cy), QPointF(cx + dx * arm, cy)])

    def _layout_chips(self, reserved: list[QRectF]) -> list[tuple[TargetFace, QRectF]]:
        """Chips centred under their face, inside the photo, never on each other or on a letter;
        other faces are avoided when possible. A chip with nowhere to go is left out (the outline
        still shows the face is being swapped)."""
        bounds = self._image_rect().adjusted(8, 8, -8, -8)
        placed = list(reserved)
        out = []
        faces = sorted(self.targets, key=lambda t: (self._face_rect(t).bottom(), self._face_rect(t).left()))
        rects = {t.index: self._face_rect(t) for t in self.targets}
        for t in faces:
            label = self.labels.get(t.index)
            assigned = bool(label and label.assigned)
            if label is None or not (assigned or t.index in (self._hover, self.active)):
                continue
            fr = rects[t.index]
            if assigned:
                w = chip_width(label.text, avatar=label.avatar is not None, strong=True)
            else:
                w = chip_width(tr("media_choose_face"))
            x = max(bounds.left(), min(fr.center().x() - w / 2, bounds.right() - w))
            others = [r for i, r in rects.items() if i != t.index]
            ys = [fr.bottom() + 8, fr.bottom() - CHIP_H - 8, fr.top() - CHIP_H - 8]
            chosen = None
            for avoid_faces in (True, False):
                for y in ys:
                    rect = QRectF(x, y, w, CHIP_H)
                    if not bounds.contains(rect):
                        continue
                    blockers = placed + (others if avoid_faces else [])
                    if not any(rect.intersects(o.adjusted(-4, -4, 4, 4)) for o in blockers):
                        chosen = rect
                        break
                if chosen is not None:
                    break
            if chosen is None:
                continue
            placed.append(chosen)
            out.append((t, chosen))
        return out

    # empty ----------------------------------------------------------------

    def _paint_empty(self, p: QPainter, area: QRectF) -> None:
        zone = area.adjusted(28, 28, -28, -28)
        pen = QPen(QColor(255, 255, 255, 80 if self._hover_empty else 46), 1.5)
        pen.setDashPattern([4, 4])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(QColor(255, 255, 255, 8) if self._hover_empty else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(zone, 22, 22)
        # same positions as the Live stage's idle state, so switching modes doesn't jump
        c = area.center()
        disc = QRectF(0, 0, 84, 84)
        disc.moveCenter(QPointF(c.x(), c.y() - 58))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(disc)
        draw_icon(p, "photo", disc.adjusted(22, 22, -22, -22), QColor(255, 255, 255, 220))
        self._text(p, area, c.y() + 2, tr("media_empty_title"), 19, theme.TEXT, bold=True)
        self._text(p, area, c.y() + 38, tr("media_empty_subtitle"), 13, theme.TEXT_SECONDARY)
        self._text(p, zone, zone.bottom() - 40, tr("media_empty_hint"), 11.5, theme.TEXT_TERTIARY)

    # busy -----------------------------------------------------------------

    def _paint_busy(self, p: QPainter, area: QRectF) -> None:
        host = area
        if self.mode == "image" and self._shown() is not None:
            host = self._image_rect()
            dim = QPainterPath()
            dim.addRoundedRect(host, PHOTO_RADIUS, PHOTO_RADIUS)
            p.fillPath(dim, QColor(6, 6, 12, 125))
        font = theme.font(13.5, theme.QFont.Weight.DemiBold)
        fm = QFontMetricsF(font)
        has_bar = self.progress is not None
        # sized from the stage, not the photo: a tall portrait must not squeeze the text
        max_w = min(520.0, area.width() - 48)
        chrome = 20 + 22 + 14 + 22            # padding, spinner, gap, padding
        text_w = fm.horizontalAdvance(self.busy_text) + 4
        w = min(max_w, max(text_w + chrome, 380.0 if has_bar else 200.0))
        wrapped = fm.boundingRect(QRectF(0, 0, w - chrome, 1e4), Qt.TextFlag.TextWordWrap, self.busy_text)
        row_h = max(48.0, wrapped.height() + 26)
        h = row_h + (38.0 if has_bar else 0.0)
        panel = QRectF(0, 0, w, h)
        panel.moveCenter(host.center())
        panel.moveLeft(max(area.left() + 12, min(panel.left(), area.right() - 12 - w)))
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.setBrush(QColor(16, 16, 26, 210))
        p.drawRoundedRect(panel, 18, 18)
        ring = QRectF(panel.left() + 20, panel.top() + (row_h - 22) / 2, 22, 22)
        p.setPen(QPen(QColor(255, 255, 255, 40), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, int(-self._spin * 16), 100 * 16)
        p.setFont(font)
        p.setPen(theme.TEXT)
        p.drawText(QRectF(ring.right() + 14, panel.top(), panel.right() - ring.right() - 14 - 22, row_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   self.busy_text)
        if has_bar:
            bar = QRectF(panel.left() + 20, panel.top() + row_h + 2, panel.width() - 40, 5)
            self._progress_bar(p, bar, self.progress or 0.0)
            p.setFont(theme.font(11.5))
            p.setPen(theme.TEXT_SECONDARY)
            line = p.fontMetrics().elidedText(self.progress_text, Qt.TextElideMode.ElideMiddle, int(bar.width()))
            p.drawText(QRectF(bar.left(), bar.bottom() + 6, bar.width(), 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)

    @staticmethod
    def _progress_bar(p: QPainter, bar: QRectF, value: float) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 36))
        p.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        fill = QRectF(bar.left(), bar.top(), max(bar.height(), bar.width() * max(0.0, min(1.0, value))), bar.height())
        grad = QLinearGradient(bar.topLeft(), bar.topRight())
        grad.setColorAt(0, theme.ACCENT)
        grad.setColorAt(1, theme.ACCENT_2)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(fill, bar.height() / 2, bar.height() / 2)

    # batch ----------------------------------------------------------------

    def _paint_batch(self, p: QPainter, area: QRectF) -> None:
        col_w = min(area.width() - 56, 720.0)
        col = QRectF(area.center().x() - col_w / 2, area.top() + 26, col_w, area.height() - 40)
        # header: title and subtitle on the left, count pills on the right
        pills = self._summary_pills()
        pills_w = sum(chip_width(text, dot=True) for text, _c in pills) + 8 * max(0, len(pills) - 1)
        title_w = col.width() - pills_w - 16
        p.setFont(theme.font(17, theme.QFont.Weight.DemiBold))
        p.setPen(theme.TEXT)
        title = p.fontMetrics().elidedText(self.batch_title, Qt.TextElideMode.ElideRight, int(title_w))
        p.drawText(QRectF(col.left(), col.top(), title_w, 26), Qt.AlignmentFlag.AlignVCenter, title)
        if self.batch_subtitle:
            p.setFont(theme.font(12))
            p.setPen(theme.TEXT_SECONDARY)
            sub = p.fontMetrics().elidedText(self.batch_subtitle, Qt.TextElideMode.ElideRight, int(col.width()))
            p.drawText(QRectF(col.left(), col.top() + 27, col.width(), 20), Qt.AlignmentFlag.AlignVCenter, sub)
        x = col.right() - pills_w
        for text, color in pills:
            x = draw_chip(p, x, col.top(), text, dot=color, tone="quiet").right() + 8
        top = col.top() + 60
        if self.batch_progress is not None:
            self._progress_bar(p, QRectF(col.left(), col.top() + 56, col.width(), 4), self.batch_progress)
            top += 10

        rows = self.rows
        visible = max(1, int((area.bottom() - 12 - top) // ROW_H))
        # keep the row being worked on in view; otherwise the wheel scrolls
        working = next((i for i, r in enumerate(rows) if r.status == "working"), None)
        target = working - visible // 2 if working is not None else self._scroll
        first = max(0, min(target, len(rows) - visible))
        self._scroll = first
        for i, row in enumerate(rows[first:first + visible]):
            self._paint_row(p, QRectF(col.left(), top + i * ROW_H, col.width(), ROW_H - 8), row)
        if len(rows) > visible:  # a thin scroll indicator on the right edge of the list
            track = QRectF(col.right() + 8, top, 3, visible * ROW_H - 8)
            thumb_h = max(24.0, track.height() * visible / len(rows))
            y = track.top() + (track.height() - thumb_h) * first / max(1, len(rows) - visible)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 50))
            p.drawRoundedRect(QRectF(track.left(), y, 3, thumb_h), 1.5, 1.5)

    def _summary_pills(self) -> list[tuple[str, QColor]]:
        counts: dict[str, int] = {}
        for r in self.rows:
            key = "no_face" if r.status == "skipped" else r.status
            counts[key] = counts.get(key, 0) + 1
        return [(f"{tr(f'media_status_{s}')} {counts[s]}", STATUS_COLORS[s])
                for s in ("saved", "no_face", "failed") if counts.get(s)]

    def _paint_row(self, p: QPainter, box: QRectF, row: BatchRow) -> None:
        working = row.status == "working"
        p.setPen(QPen(QColor(theme.ACCENT_2.red(), theme.ACCENT_2.green(), theme.ACCENT_2.blue(), 110), 1)
                 if working else Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22 if working else 13))
        p.drawRoundedRect(box, 14, 14)
        thumb = QRectF(box.left() + 8, box.top() + (box.height() - 40) / 2, 40, 40)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 9, 9)
        p.save()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        if row.thumb is not None and not row.thumb.isNull():
            src = QRectF(row.thumb.rect())
            side = min(src.width(), src.height())   # centre crop, never squeezed
            p.drawPixmap(thumb, row.thumb, QRectF(src.center().x() - side / 2, src.center().y() - side / 2, side, side))
        else:
            p.fillRect(thumb, QColor(255, 255, 255, 16))
            draw_icon(p, "photo", thumb.adjusted(11, 11, -11, -11), QColor(255, 255, 255, 90))
        p.restore()
        status = tr(f"media_status_{row.status}")
        pill_w = chip_width(status, dot=True)
        pill = QRectF(box.right() - 10 - pill_w, box.center().y() - CHIP_H / 2, pill_w, CHIP_H)
        draw_chip(p, pill.left(), pill.top(), status, dot=STATUS_COLORS.get(row.status, theme.TEXT_TERTIARY),
                  tone="quiet" if row.status in ("waiting", "skipped") else "dark")
        name_x = thumb.right() + 12
        name_w = pill.left() - 16 - name_x
        p.setFont(theme.font(13, theme.QFont.Weight.Medium))
        p.setPen(theme.TEXT)
        name = p.fontMetrics().elidedText(row.name, Qt.TextElideMode.ElideMiddle, int(name_w))
        if row.detail:
            p.drawText(QRectF(name_x, box.top() + 8, name_w, 20), Qt.AlignmentFlag.AlignVCenter, name)
            p.setFont(theme.font(11))
            p.setPen(theme.TEXT_TERTIARY)
            detail = p.fontMetrics().elidedText(row.detail, Qt.TextElideMode.ElideRight, int(name_w))
            p.drawText(QRectF(name_x, box.top() + 28, name_w, 16), Qt.AlignmentFlag.AlignVCenter, detail)
        else:
            p.drawText(QRectF(name_x, box.top(), name_w, box.height()), Qt.AlignmentFlag.AlignVCenter, name)


def now() -> float:
    return time.monotonic()
