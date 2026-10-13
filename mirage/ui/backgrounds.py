"""Choosing a virtual background: a round button in the control bar and the
panel it opens above the bar (a grid of previews, like a rich menu)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Property, QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QVBoxLayout, QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.ui.widgets import EASE_OUT, IconButton, draw_icon

ADD = "__add__"
TILE_W, TILE_H, LABEL_H = 96, 60, 22
COLUMNS = 4
SHADOW = 18          # room around the panel for its soft shadow
PAD = 18
THUMB = (2 * TILE_W, 2 * TILE_H)   # thumbnails are made at 2× for Retina


def to_pixmap(bgr: np.ndarray) -> QPixmap:
    """A QPixmap that owns its pixels (the numpy buffer may go away)."""
    bgr = np.ascontiguousarray(bgr)
    h, w = bgr.shape[:2]
    return QPixmap.fromImage(QImage(bgr.data, w, h, bgr.strides[0], QImage.Format.Format_BGR888).copy())


def thumbnail(bgr: np.ndarray) -> QPixmap:
    from mirage.compose import cover

    return to_pixmap(cover(bgr, *THUMB))


def blur_thumbnail() -> QPixmap:
    """The Blur tile: a room-ish picture, softly out of focus."""
    from mirage.backgrounds import render_preset

    room = cv2.GaussianBlur(render_preset("office", *THUMB), (0, 0), 9.0).astype(np.float32)
    frosted = room * 0.7 + np.array((215, 205, 200), np.float32) * 0.3   # milky, like frosted glass
    return to_pixmap(np.clip(frosted, 0, 255).astype(np.uint8))


@dataclass
class Choice:
    value: str                  # settings value, or ADD
    name: str
    pixmap: QPixmap | None = None
    removable: bool = False     # your own pictures


def _silhouette(rect: QRectF) -> QPainterPath:
    """A small head-and-shoulders standing at the bottom middle of ``rect``."""
    h = rect.height()
    c = QPointF(rect.center().x(), rect.bottom())
    path = QPainterPath()
    path.addEllipse(QPointF(c.x(), c.y() - h * 0.50), h * 0.15, h * 0.15)
    path.addRoundedRect(QRectF(c.x() - h * 0.30, c.y() - h * 0.31, h * 0.60, h * 0.40), h * 0.2, h * 0.2)
    return path


class BackgroundTile(QWidget):
    clicked = Signal(str)
    menuRequested = Signal(str, QPointF)

    def __init__(self, choice: Choice, parent: QWidget | None = None):
        super().__init__(parent)
        self.choice = choice
        self.selected = False
        self._hover = False
        self.setFixedSize(TILE_W + 8, TILE_H + LABEL_H + 6)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(choice.name)
        self.setToolTip(choice.name)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.choice.value)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if self.choice.removable:
            self.menuRequested.emit(self.choice.value, QPointF(e.globalPos()))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(4, 4, TILE_W, TILE_H)
        radius = 10.0
        shape = QPainterPath()
        shape.addRoundedRect(r, radius, radius)
        value = self.choice.value

        if value == ADD:
            p.setPen(QPen(QColor(255, 255, 255, 90 if self._hover else 60), 1.3, Qt.PenStyle.DashLine))
            p.setBrush(QColor(255, 255, 255, 22 if self._hover else 10))
            p.drawPath(shape)
            draw_icon(p, "plus", QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22), QColor(255, 255, 255, 220))
        else:
            p.save()
            p.setClipPath(shape)
            if self.choice.pixmap is not None:
                pix = self.choice.pixmap
                scale = max(r.width() / pix.width(), r.height() / pix.height())
                w, h = pix.width() * scale, pix.height() * scale
                p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h).toRect(), pix)
            else:
                p.fillRect(r, QColor(255, 255, 255, 16))
            if value == "none":
                draw_icon(p, "none", QRectF(r.center().x() - 12, r.center().y() - 12, 24, 24),
                          QColor(255, 255, 255, 200))
            else:  # you, in front of it
                person = _silhouette(r.adjusted(0, 6, 0, 0))
                p.setPen(QPen(QColor(255, 255, 255, 110), 1))
                p.setBrush(QColor(14, 14, 22, 170))
                p.drawPath(person)
            if self._hover and not self.selected:
                p.fillRect(r, QColor(255, 255, 255, 18))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 60 if self._hover else 34), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if self.selected:
            ring = QConicalGradient(r.center(), 90)
            ring.setColorAt(0.0, theme.ACCENT)
            ring.setColorAt(0.5, theme.ACCENT_2)
            ring.setColorAt(1.0, theme.ACCENT)
            p.setPen(QPen(ring, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)

        p.setFont(theme.font(11.5, theme.QFont.Weight.DemiBold if self.selected else theme.QFont.Weight.Normal))
        p.setPen(theme.TEXT if self.selected or self._hover else theme.TEXT_SECONDARY)
        label = QRectF(0, r.bottom() + 5, self.width(), LABEL_H - 4)
        text = p.fontMetrics().elidedText(self.choice.name, Qt.TextElideMode.ElideRight, int(label.width()) - 4)
        p.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)


class BackgroundPicker(QWidget):
    """The panel above the control bar. A child of the window, so it floats over
    the stage; it closes on Esc, on a click outside, or after a pick."""

    picked = Signal(str)                 # a settings value, or ADD
    menuRequested = Signal(str, QPointF)
    filesDropped = Signal(list)          # list[Path] of pictures dropped on the panel
    visibilityChanged = Signal(bool)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self._anchor: QWidget | None = None
        self._tiles: list[BackgroundTile] = []
        self._reveal = 0.0
        self._drop = False
        self._anim = QPropertyAnimation(self, b"reveal", self)
        self._anim.setDuration(theme.SWITCH_MS + 40)
        self._anim.setEasingCurve(EASE_OUT)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SHADOW + PAD, SHADOW + PAD - 2, SHADOW + PAD, SHADOW + PAD - 4)
        lay.setSpacing(4)
        head = QWidget()
        hl = QGridLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel(tr("background"))
        title.setFont(theme.font(15, theme.QFont.Weight.Bold))
        keys = QLabel(tr("background_keys"))
        keys.setObjectName("faint")
        keys.setFont(theme.font(11.5))
        hl.addWidget(title, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(keys, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(head)
        hint = QLabel(tr("background_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setFont(theme.font(12))
        lay.addWidget(hint)
        lay.addSpacing(8)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(4)
        self._grid.setVerticalSpacing(4)
        lay.addWidget(self._grid_host)
        width = 2 * SHADOW + 2 * PAD + COLUMNS * (TILE_W + 8) + (COLUMNS - 1) * 4
        self.setFixedWidth(width)
        hint.setFixedWidth(width - 2 * (SHADOW + PAD))
        self.hide()

    # ── content ──────────────────────────────────────────────────────────

    def set_choices(self, choices: list[Choice], selected: str) -> None:
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        for i, choice in enumerate(choices):
            tile = BackgroundTile(choice)
            tile.clicked.connect(self.picked)
            tile.menuRequested.connect(self.menuRequested)
            self._grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
            self._tiles.append(tile)
        self.set_selected(selected)
        self.adjustSize()
        if self.isVisible():
            self._place()

    def set_selected(self, value: str) -> None:
        for tile in self._tiles:
            tile.selected = tile.choice.value == value
            tile.update()

    # ── showing ──────────────────────────────────────────────────────────

    def toggle(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.close_panel()
        else:
            self.open_at(anchor)

    def open_at(self, anchor: QWidget) -> None:
        self._anchor = anchor
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.visibilityChanged.emit(True)

    def close_panel(self) -> None:
        if not self.isVisible():
            return
        QApplication.instance().removeEventFilter(self)
        self.hide()
        self.visibilityChanged.emit(False)

    def _place(self) -> None:
        """Above the anchor button, its right edge near the button, inside the window."""
        if self._anchor is None:
            return
        win = self.parentWidget()
        top_left = self._anchor.mapTo(win, QPoint(0, 0))
        x = top_left.x() + self._anchor.width() // 2 + 60 - self.width() + SHADOW
        x = max(theme.MARGIN - SHADOW, min(x, win.width() - self.width() - theme.MARGIN + SHADOW))
        bar_top = self._anchor.parentWidget().mapTo(win, QPoint(0, 0)).y()
        y = bar_top - self.height() + SHADOW - 10
        self.move(x, max(theme.TITLEBAR_HEIGHT, y))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and self.isVisible():
            pos = event.globalPosition().toPoint()
            inside = self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW).contains(self.mapFromGlobal(pos))
            on_anchor = self._anchor is not None and self._anchor.rect().contains(self._anchor.mapFromGlobal(pos))
            if not inside and not on_anchor:
                self.close_panel()
        elif kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.isVisible():
            self.close_panel()
            return True
        elif kind == QEvent.Type.Resize and obj is self.parentWidget() and self.isVisible():
            self._place()
        return False

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, v: float) -> None:
        self._reveal = v
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)

    # ── dropping pictures ────────────────────────────────────────────────

    def _pictures(self, event) -> list[Path]:
        from mirage.ui.main_window import IMAGE_SUFFIXES

        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return [Path(u.toLocalFile()) for u in urls
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._pictures(event):
            event.acceptProposedAction()
            self._drop = True
            self.update()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._pictures(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._drop = False
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop = False
        self.update()
        files = self._pictures(event)
        if files:
            event.acceptProposedAction()
            self.filesDropped.emit(files)

    # ── painting ─────────────────────────────────────────────────────────

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        radius = 22.0
        p.setOpacity(0.35 + 0.65 * self._reveal)
        if theme.SWITCH_MS:
            p.translate(0, 8 * (1.0 - self._reveal))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8, 0, -1):   # a soft shadow, darker towards the panel
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(panel.adjusted(-i * 2, -i * 1.5, i * 2, i * 2.5), radius + i * 2, radius + i * 2)
        p.setBrush(QColor(26, 26, 36, 246))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawRoundedRect(panel, radius, radius)
        if self._drop:
            p.setPen(QPen(theme.ACCENT, 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(139, 124, 255, 26))
            p.drawRoundedRect(panel.adjusted(5, 5, -5, -5), radius - 4, radius - 4)


class BackgroundButton(IconButton):
    """Round button in the control bar: the background icon when off; when on, a
    tiny preview of the background with you in front of it, ringed like a toggle."""

    def __init__(self, size: int = 36, parent: QWidget | None = None):
        super().__init__("background", tr("bg_button"), size, parent)
        self.preview: QPixmap | None = None
        self.on = False
        self.open = False

    def set_state(self, on: bool, preview: QPixmap | None) -> None:
        self.on, self.preview = on, preview
        self.update()

    def set_open(self, open_: bool) -> None:
        self.open = open_
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.size()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        self._begin(p)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not (self.on and self.preview is not None):
            # Off: the plain icon button; while the panel is open, lit like a toggle that is on.
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            edge = QColor(theme.ACCENT_2)
            edge.setAlpha(170)
            p.setPen(QPen(edge, 1.2) if self.open else QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(QColor(255, 255, 255, 44 if self.open else (28 if self._hover else 16)))
            p.drawEllipse(r)
            inset = r.width() * 0.24
            draw_icon(p, "background", r.adjusted(inset, inset, -inset, -inset),
                      QColor(theme.ACCENT_2) if self.open else QColor(255, 255, 255, 235))
            return
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        clip = QPainterPath()
        clip.addEllipse(r)
        p.save()
        p.setClipPath(clip)
        pix = self.preview
        scale = max(r.width() / pix.width(), r.height() / pix.height())
        w, h = pix.width() * scale, pix.height() * scale
        p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h).toRect(), pix)
        p.fillRect(r, QColor(0, 0, 0, 40 if self._hover else 70))
        person = _silhouette(r.adjusted(r.width() * 0.2, r.height() * 0.28, -r.width() * 0.2, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawPath(person)
        p.restore()
        edge = QColor(theme.ACCENT_2)
        edge.setAlpha(230 if self.open else 190)
        p.setPen(QPen(edge, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
