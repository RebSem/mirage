"""The stage: live video with a few quiet overlays, or a friendly idle state."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.ui.widgets import CHIP_H, chip_width, draw_chip, draw_icon

NO_FACE_GRACE_S = 1.0  # don't flash "looking for your face" on a single missed detection


class Stage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setMinimumSize(560, 340)
        self.mode = "idle"            # idle | loading | starting | live
        self.drop_active = False
        self.mirror = True
        self.show_fps = False
        self.fps = 0.0
        self.face_name = ""
        self._frame: np.ndarray | None = None
        self._image: QImage | None = None
        self._face_missing_since: float | None = None
        self._spin = 0.0
        self._spinner = QTimer(self)
        self._spinner.setInterval(16)
        self._spinner.timeout.connect(self._tick)

    # ── state ────────────────────────────────────────────────────────────

    def set_drop_active(self, on: bool) -> None:
        self.drop_active = on
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode in ("loading", "starting"):
            self._spinner.start()
        else:
            self._spinner.stop()
        if mode != "live":
            self._frame, self._image = None, None
            self._face_missing_since = None
        self.update()

    def set_frame(self, bgr: np.ndarray) -> None:
        bgr = np.ascontiguousarray(bgr)
        h, w = bgr.shape[:2]
        self._frame = bgr  # keep the buffer alive while QImage points at it
        self._image = QImage(bgr.data, w, h, bgr.strides[0], QImage.Format.Format_BGR888)
        self.update()

    def set_face_found(self, found: bool) -> None:
        if found:
            self._face_missing_since = None
        elif self._face_missing_since is None:
            self._face_missing_since = time.monotonic()

    def _tick(self) -> None:
        self._spin = (self._spin + 6.0) % 360
        self.update()

    # ── painting ─────────────────────────────────────────────────────────

    def _video_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self._video_rect()
        radius = theme.RADIUS_STAGE - 8
        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        p.setClipPath(clip)
        p.fillRect(r, theme.STAGE_BG)

        if self.mode == "live" and self._image is not None:
            self._paint_video(p, r)
            p.setClipping(False)
            self._paint_overlays(p, r)
        elif self.mode in ("loading", "starting"):
            p.setClipping(False)
            self._paint_loading(p, r)
        else:
            p.setClipping(False)
            self._paint_idle(p, r)

        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self.drop_active:
            self._paint_drop(p, r, radius)

    def _paint_video(self, p: QPainter, r: QRectF) -> None:
        img = self._image
        # aspect-fill: crop the video to the stage, keep its centre
        scale = max(r.width() / img.width(), r.height() / img.height())
        w, h = img.width() * scale, img.height() * scale
        target = QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)
        p.save()
        if self.mirror:
            p.translate(r.center().x() * 2, 0)
            p.scale(-1, 1)
        p.drawImage(target, img)
        p.restore()

    def _chip(self, p: QPainter, text: str, anchor: QPointF, align: str, dot: QColor | None = None,
              bold: bool = False) -> None:
        w = chip_width(text, dot=dot is not None, strong=bold)
        x = anchor.x() if align == "left" else (anchor.x() - w if align == "right" else anchor.x() - w / 2)
        draw_chip(p, x, anchor.y(), text, dot=dot, strong=bold)

    def _paint_overlays(self, p: QPainter, r: QRectF) -> None:
        m = 16
        self._chip(p, tr("live_badge"), QPointF(r.left() + m, r.top() + m), "left", dot=theme.LIVE, bold=True)
        if self.show_fps:
            self._chip(p, tr("status_fps", fps=self.fps), QPointF(r.right() - m, r.top() + m), "right")
        if self.face_name:
            self._chip(p, self.face_name, QPointF(r.left() + m, r.bottom() - m - CHIP_H), "left")
        missing = self._face_missing_since
        if missing is not None and time.monotonic() - missing > NO_FACE_GRACE_S:
            self._chip(p, tr("no_face_in_view"), QPointF(r.center().x(), r.bottom() - m - CHIP_H), "center")

    def _centered_text(self, p: QPainter, r: QRectF, y: float, text: str, size: float,
                       color: QColor, weight=theme.QFont.Weight.Normal, single_line: bool = False) -> None:
        p.setFont(theme.font(size, weight))
        p.setPen(color)
        wrap = Qt.TextFlag.TextSingleLine if single_line else Qt.TextFlag.TextWordWrap
        p.drawText(QRectF(r.left() + 40, y, r.width() - 80, size * 2.2),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | wrap, text)

    def _paint_idle(self, p: QPainter, r: QRectF) -> None:
        c = r.center()
        disc = QRectF(0, 0, 84, 84)
        disc.moveCenter(QPointF(c.x(), c.y() - 58))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(disc)
        draw_icon(p, "camera", disc.adjusted(24, 24, -24, -24), QColor(255, 255, 255, 220))
        title = tr("idle_title")
        if self.face_name:
            fm = QFontMetricsF(theme.font(19, theme.QFont.Weight.DemiBold))
            room = r.width() - 80 - fm.horizontalAdvance(tr("idle_title_face", name="")) - 6  # kerning slack
            name = fm.elidedText(self.face_name, Qt.TextElideMode.ElideRight, max(40.0, room))
            title = tr("idle_title_face", name=name)
        self._centered_text(p, r, c.y() + 2, title, 19, theme.TEXT, theme.QFont.Weight.DemiBold,
                            single_line=bool(self.face_name))
        self._centered_text(p, r, c.y() + 38, tr("idle_subtitle"), 13, theme.TEXT_SECONDARY)
        self._centered_text(p, r, r.bottom() - 44, tr("idle_hint_keys"), 11.5, theme.TEXT_TERTIARY)

    def _paint_loading(self, p: QPainter, r: QRectF) -> None:
        c = r.center()
        ring = QRectF(0, 0, 44, 44)
        ring.moveCenter(QPointF(c.x(), c.y() - 40))
        p.setPen(QPen(QColor(255, 255, 255, 40), 3))
        p.drawEllipse(ring)
        p.setPen(QPen(QColor(255, 255, 255, 230), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, int(-self._spin * 16), 100 * 16)
        if self.mode == "starting":
            self._centered_text(p, r, c.y() + 4, tr("status_starting"), 17, theme.TEXT, theme.QFont.Weight.DemiBold)
            return
        self._centered_text(p, r, c.y() + 4, tr("loading_title"), 17, theme.TEXT, theme.QFont.Weight.DemiBold)
        self._centered_text(p, r, c.y() + 36, tr("loading_subtitle"), 12.5, theme.TEXT_SECONDARY)

    def _paint_drop(self, p: QPainter, r: QRectF, radius: float) -> None:
        p.setBrush(QColor(12, 12, 20, 170))
        p.setPen(QPen(theme.ACCENT, 2, Qt.PenStyle.DashLine))
        p.drawRoundedRect(r.adjusted(6, 6, -6, -6), radius - 4, radius - 4)
        self._centered_text(p, r, r.center().y() - 14, tr("drop_hint"), 17, theme.TEXT, theme.QFont.Weight.DemiBold)
