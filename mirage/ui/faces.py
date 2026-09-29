"""Face gallery: round thumbnails, number badges, one-click switching."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.ui.widgets import draw_icon

ME = "__me__"
ADD = "__add__"
RANDOM = "__random__"
BUSY = "__busy__"

TILE_W, TILE_H, DISC = 88, 108, 68
COLUMNS = 3


class FaceTile(QWidget):
    clicked = Signal(str)
    menuRequested = Signal(str, QPointF)

    def __init__(self, face_id: str, name: str, pixmap: QPixmap | None = None,
                 number: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.face_id = face_id
        self.name = name
        self.pixmap = pixmap
        self.number = number
        self.selected = False
        self._hover = False
        self._spin = 0.0
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{name} ({number})" if number else name)
        if face_id == ME:
            self.setToolTip(tr("face_me_hint"))
        if face_id == BUSY:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._timer = QTimer(self)
            self._timer.setInterval(16)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(TILE_W, TILE_H)

    def _tick(self) -> None:
        self._spin = (self._spin + 6) % 360
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()) and self.face_id != BUSY:
            self.clicked.emit(self.face_id)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if self.face_id not in (ME, ADD, RANDOM, BUSY):
            self.menuRequested.emit(self.face_id, QPointF(e.globalPos()))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        disc = QRectF((TILE_W - DISC) / 2, 6, DISC, DISC)

        if self.selected:
            ring = QConicalGradient(disc.center(), 90)
            ring.setColorAt(0.0, theme.ACCENT)
            ring.setColorAt(0.5, theme.ACCENT_2)
            ring.setColorAt(1.0, theme.ACCENT)
            p.setPen(QPen(ring, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(disc.adjusted(-4, -4, 4, 4))
        elif self._hover and self.face_id != BUSY:
            p.setPen(QPen(QColor(255, 255, 255, 70), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(disc.adjusted(-4, -4, 4, 4))

        path = QPainterPath()
        path.addEllipse(disc)
        if self.pixmap is not None and not self.pixmap.isNull():
            p.save()
            p.setClipPath(path)
            p.drawPixmap(disc.toRect(), self.pixmap)
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(disc)
        else:
            dashed = self.face_id in (ADD, RANDOM)
            p.setPen(QPen(QColor(255, 255, 255, 70 if self._hover else 45), 1.3,
                          Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            p.setBrush(QColor(255, 255, 255, 30 if self._hover else 18))
            p.drawEllipse(disc)
            icon = {ME: "person", ADD: "plus", RANDOM: "dice"}.get(self.face_id)
            if icon:
                inset = DISC * 0.31
                draw_icon(p, icon, disc.adjusted(inset, inset, -inset, -inset), QColor(255, 255, 255, 220))
            elif self.face_id == BUSY:
                p.setPen(QPen(QColor(255, 255, 255, 220), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(disc.adjusted(24, 24, -24, -24), int(-self._spin * 16), 100 * 16)

        if self.number is not None:
            badge = QRectF(0, 0, 19, 19)
            badge.moveCenter(QPointF(disc.right() - 3, disc.top() + 3))
            p.setPen(QPen(QColor(24, 22, 36, 235), 2.5))   # a cut-out edge where it crosses the ring
            p.setBrush(QColor(255, 255, 255, 235) if self.selected else QColor(28, 28, 40, 235))
            p.drawEllipse(badge)
            p.setPen(QColor(20, 20, 30) if self.selected else theme.TEXT)
            p.setFont(theme.font(10, theme.QFont.Weight.Bold))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.number))

        p.setFont(theme.font(11.5, theme.QFont.Weight.DemiBold if self.selected else theme.QFont.Weight.Normal))
        p.setPen(theme.TEXT if self.selected else theme.TEXT_SECONDARY)
        text_rect = QRectF(2, disc.bottom() + 8, TILE_W - 4, 18)
        text = p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)


class FaceGrid(QWidget):
    """Grid of tiles: Me, the library (numbered 1–9), then Add and Random."""

    picked = Signal(str)                 # face id, or ME / ADD / RANDOM
    menuRequested = Signal(str, QPointF)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 4, 0, 4)
        self._grid.setHorizontalSpacing(4)
        self._grid.setVerticalSpacing(6)
        self._tiles: list[FaceTile] = []

    def rebuild(self, faces: list[tuple[str, str, QPixmap | None]], selected: str | None, busy: int = 0) -> None:
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        tiles = [FaceTile(ME, tr("face_me"))]
        for i, (face_id, name, pix) in enumerate(faces):
            tiles.append(FaceTile(face_id, name, pix, number=i + 1 if i < 9 else None))
        tiles += [FaceTile(BUSY, "…") for _ in range(busy)]
        tiles += [FaceTile(ADD, tr("add_photos")), FaceTile(RANDOM, tr("random_face"))]
        for i, tile in enumerate(tiles):
            tile.clicked.connect(self.picked)
            tile.menuRequested.connect(self.menuRequested)
            self._grid.addWidget(tile, i // COLUMNS, i % COLUMNS, Qt.AlignmentFlag.AlignHCenter)
            tile.show()
        self._tiles = tiles
        self.set_selected(selected)
        self.updateGeometry()

    def set_selected(self, face_id: str | None) -> None:
        target = face_id or ME
        for tile in self._tiles:
            tile.selected = tile.face_id == target
            tile.update()
