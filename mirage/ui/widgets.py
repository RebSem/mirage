"""Small custom controls drawn with QPainter so they sit well on glass."""

from __future__ import annotations

import math

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QWidget

from mirage import theme

EASE_OUT = QEasingCurve.Type.OutCubic


class GlassPanel(QWidget):
    """A rounded pane. Native glass is placed behind it by GlassWindow;
    without it, the panel paints a translucent fill itself."""

    def __init__(self, radius: float = theme.RADIUS_PANEL, parent: QWidget | None = None):
        super().__init__(parent)
        self.radius = radius
        self.native_glass = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.native_glass:
            p.setBrush(theme.FALLBACK_GLASS)
            p.setPen(QPen(theme.FALLBACK_EDGE, 1))
            p.drawRoundedRect(rect, self.radius, self.radius)


# ── icons ────────────────────────────────────────────────────────────────

def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Tiny vector icon set (play, stop, plus, dice, mirror, person, camera, help)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = min(rect.width(), rect.height())
    c = rect.center()
    pen = QPen(color, max(1.6, s * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if name == "play":
        path = QPainterPath()
        path.moveTo(c.x() - s * 0.28, c.y() - s * 0.36)
        path.lineTo(c.x() + s * 0.38, c.y())
        path.lineTo(c.x() - s * 0.28, c.y() + s * 0.36)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(path)
    elif name == "stop":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        r = s * 0.30
        p.drawRoundedRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), s * 0.08, s * 0.08)
    elif name == "plus":
        p.setPen(pen)
        r = s * 0.30
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
    elif name == "dice":
        p.setPen(QPen(color, max(1.4, s * 0.075)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = s * 0.34
        p.drawRoundedRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), s * 0.1, s * 0.1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        d = s * 0.075
        for dx, dy in ((-0.16, -0.16), (0.16, 0.16), (0, 0), (0.16, -0.16), (-0.16, 0.16)):
            p.drawEllipse(QPointF(c.x() + dx * s, c.y() + dy * s), d, d)
    elif name == "mirror":
        p.setPen(pen)
        p.drawLine(QPointF(c.x(), c.y() - s * 0.36), QPointF(c.x(), c.y() + s * 0.36))
        for sign in (-1, 1):
            path = QPainterPath()
            path.moveTo(c.x() + sign * s * 0.10, c.y() - s * 0.24)
            path.lineTo(c.x() + sign * s * 0.38, c.y() + s * 0.24)
            path.lineTo(c.x() + sign * s * 0.10, c.y() + s * 0.24)
            path.closeSubpath()
            p.setBrush(color if sign > 0 else Qt.BrushStyle.NoBrush)
            p.drawPath(path)
    elif name == "person":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(c.x(), c.y() - s * 0.14), s * 0.17, s * 0.17)
        body = QPainterPath()
        body.addRoundedRect(QRectF(c.x() - s * 0.30, c.y() + s * 0.08, s * 0.60, s * 0.34), s * 0.17, s * 0.17)
        p.drawPath(body)
    elif name == "camera":
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(c.x() - s * 0.38, c.y() - s * 0.24, s * 0.52, s * 0.48), s * 0.08, s * 0.08)
        lens = QPainterPath()
        lens.moveTo(c.x() + s * 0.18, c.y() - s * 0.08)
        lens.lineTo(c.x() + s * 0.40, c.y() - s * 0.20)
        lens.lineTo(c.x() + s * 0.40, c.y() + s * 0.20)
        lens.lineTo(c.x() + s * 0.18, c.y() + s * 0.08)
        p.drawPath(lens)
    elif name == "photo":
        p.setPen(QPen(color, max(1.5, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        frame = QRectF(c.x() - s * 0.40, c.y() - s * 0.30, s * 0.80, s * 0.60)
        p.drawRoundedRect(frame, s * 0.08, s * 0.08)
        hill = QPainterPath()
        hill.moveTo(frame.left() + s * 0.06, frame.bottom() - s * 0.06)
        hill.lineTo(c.x() - s * 0.08, c.y() - s * 0.02)
        hill.lineTo(c.x() + s * 0.06, c.y() + s * 0.12)
        hill.lineTo(c.x() + s * 0.18, c.y() + s * 0.02)
        hill.lineTo(frame.right() - s * 0.06, frame.bottom() - s * 0.06)
        p.drawPath(hill)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(c.x() + s * 0.18, c.y() - s * 0.14), s * 0.06, s * 0.06)
    elif name == "swap":
        p.setPen(pen)
        r = s * 0.30
        for sign in (-1, 1):
            y = c.y() + sign * s * 0.12
            p.drawLine(QPointF(c.x() - r, y), QPointF(c.x() + r, y))
            tip = c.x() + (r if sign < 0 else -r)
            back = tip - s * 0.12 if sign < 0 else tip + s * 0.12  # arrowheads: → on top, ← below
            p.drawLine(QPointF(tip, y), QPointF(back, y - s * 0.10))
            p.drawLine(QPointF(tip, y), QPointF(back, y + s * 0.10))
    elif name == "save":
        p.setPen(pen)
        p.drawLine(QPointF(c.x(), c.y() - s * 0.34), QPointF(c.x(), c.y() + s * 0.10))
        p.drawLine(QPointF(c.x() - s * 0.14, c.y() - s * 0.04), QPointF(c.x(), c.y() + s * 0.10))
        p.drawLine(QPointF(c.x() + s * 0.14, c.y() - s * 0.04), QPointF(c.x(), c.y() + s * 0.10))
        tray = QPainterPath()
        tray.moveTo(c.x() - s * 0.34, c.y() + s * 0.06)
        tray.lineTo(c.x() - s * 0.34, c.y() + s * 0.30)
        tray.lineTo(c.x() + s * 0.34, c.y() + s * 0.30)
        tray.lineTo(c.x() + s * 0.34, c.y() + s * 0.06)
        p.drawPath(tray)
    elif name == "folder":
        p.setPen(QPen(color, max(1.5, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        body = QPainterPath()
        body.moveTo(c.x() - s * 0.38, c.y() - s * 0.24)
        body.lineTo(c.x() - s * 0.12, c.y() - s * 0.24)
        body.lineTo(c.x() - s * 0.04, c.y() - s * 0.14)
        body.lineTo(c.x() + s * 0.38, c.y() - s * 0.14)
        body.lineTo(c.x() + s * 0.38, c.y() + s * 0.28)
        body.lineTo(c.x() - s * 0.38, c.y() + s * 0.28)
        body.closeSubpath()
        p.drawPath(body)
    elif name == "film":
        p.setPen(QPen(color, max(1.5, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        frame = QRectF(c.x() - s * 0.34, c.y() - s * 0.36, s * 0.68, s * 0.72)
        p.drawRoundedRect(frame, s * 0.06, s * 0.06)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        for i in range(3):
            y = frame.top() + s * (0.12 + i * 0.22)
            p.drawRect(QRectF(frame.left() + s * 0.04, y, s * 0.08, s * 0.08))
            p.drawRect(QRectF(frame.right() - s * 0.12, y, s * 0.08, s * 0.08))
    elif name == "people":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        for dx, scale in ((-0.16, 0.8), (0.16, 1.0)):
            p.drawEllipse(QPointF(c.x() + dx * s, c.y() - s * 0.14), s * 0.12 * scale, s * 0.12 * scale)
            body = QPainterPath()
            body.addRoundedRect(QRectF(c.x() + dx * s - s * 0.20 * scale, c.y() + s * 0.04,
                                       s * 0.40 * scale, s * 0.26 * scale), s * 0.12, s * 0.12)
            p.drawPath(body)
    elif name == "compare":
        p.setPen(QPen(color, max(1.5, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, s * 0.34, s * 0.34)
        half = QPainterPath()
        half.moveTo(c.x(), c.y() - s * 0.34)
        half.arcTo(QRectF(c.x() - s * 0.34, c.y() - s * 0.34, s * 0.68, s * 0.68), 90, 180)
        half.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(half)
    elif name == "help":
        p.setPen(QPen(color, max(1.4, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, s * 0.40, s * 0.40)
        f = theme.font(s * 0.42, theme.QFont.Weight.DemiBold)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
    p.restore()


# ── pressable base with a subtle scale on press ─────────────────────────

class _Pressable(QAbstractButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scale = 1.0
        self._hover = False
        self._anim = QPropertyAnimation(self, b"pressScale", self)
        self._anim.setDuration(theme.PRESS_MS)
        self._anim.setEasingCurve(EASE_OUT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space belongs to Start/Stop
        self.pressed.connect(lambda: self._animate(0.965))
        self.released.connect(lambda: self._animate(1.0))

    def _animate(self, to: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._scale)
        self._anim.setEndValue(to)
        self._anim.start()

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = v
        self.update()

    pressScale = Property(float, _get_scale, _set_scale)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def _begin(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()
        p.translate(c)
        p.scale(self._scale, self._scale)
        p.translate(-c)


class PrimaryButton(_Pressable):
    """The one big Start / Stop pill."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = "start"        # start | stop | busy
        self.icon = "play"
        self._spin = 0.0
        self._spinner = QTimer(self)
        self._spinner.setInterval(16)
        self._spinner.timeout.connect(self._tick)
        self.setMinimumSize(210, 50)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(220, 52)

    def set_mode(self, mode: str, text: str, icon: str | None = None) -> None:
        self.mode = mode
        self.icon = icon or ("stop" if mode == "stop" else "play")
        self.setText(text)
        self.setAccessibleName(text)
        self.setEnabled(mode != "busy")
        if mode == "busy":
            self._spinner.start()
        else:
            self._spinner.stop()
        self.update()

    def _tick(self) -> None:
        self._spin = (self._spin + 7.5) % 360
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        self._begin(p)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = r.height() / 2
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        if self.mode == "stop":
            grad.setColorAt(0, QColor("#FF5E57"))
            grad.setColorAt(1, QColor("#E0245E"))
        elif self.mode == "busy":
            grad.setColorAt(0, QColor(255, 255, 255, 60))
            grad.setColorAt(1, QColor(255, 255, 255, 40))
        else:
            grad.setColorAt(0, QColor("#7C6CFF"))
            grad.setColorAt(1, QColor("#3FA7F5"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, radius, radius)
        # top sheen: a glassy highlight on the upper half
        sheen = QLinearGradient(r.topLeft(), QPointF(r.left(), r.center().y()))
        sheen.setColorAt(0, QColor(255, 255, 255, 70 if self._hover else 48))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -r.height() / 2), radius - 1, radius - 1)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, radius, radius)

        icon = QRectF(0, 0, 18, 18)
        p.setFont(theme.font(15, theme.QFont.Weight.DemiBold))
        text_w = p.fontMetrics().horizontalAdvance(self.text())
        total = icon.width() + 10 + text_w
        x0 = r.center().x() - total / 2
        icon.moveCenter(QPointF(x0 + icon.width() / 2, r.center().y()))
        if self.mode == "busy":
            p.setPen(QPen(QColor(255, 255, 255, 220), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(icon.adjusted(1, 1, -1, -1), int(-self._spin * 16), 270 * 16)
        else:
            draw_icon(p, self.icon, icon, QColor("white"))
        p.setPen(QColor("white"))
        p.drawText(QRectF(icon.right() + 10, r.top(), text_w + 4, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class IconButton(_Pressable):
    """Round glassy icon button, optionally checkable."""

    def __init__(self, icon: str, tooltip: str = "", size: int = 34, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon = icon
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(size, size)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        self._begin(p)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isCheckable() and self.isChecked()
        base = 34 if on else (26 if self._hover else 16)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(theme.ACCENT if on else QColor(255, 255, 255, base))
        p.drawEllipse(r)
        draw_icon(p, self.icon, r.adjusted(r.width() * 0.24, r.height() * 0.24, -r.width() * 0.24, -r.height() * 0.24),
                  QColor(255, 255, 255, 235 if self.isEnabled() else 90))


class Switch(QAbstractButton):
    """iOS-style toggle with an animated knob."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(40, 24)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(theme.SWITCH_MS)
        self._anim.setEasingCurve(EASE_OUT)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # noqa: N802 — jump without animation (initial state)
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        off, on = QColor(255, 255, 255, 46), QColor(theme.ACCENT)
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
            int(off.alpha() + (on.alpha() - off.alpha()) * self._pos),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.left() + 2 + (r.width() - d - 4) * self._pos
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))


class Segmented(QWidget):
    """Segmented control with a sliding highlight."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self._options = options          # (value, label)
        self._index = 0
        self._x = 0.0
        self._anim = QPropertyAnimation(self, b"highlight", self)
        self._anim.setDuration(theme.SWITCH_MS + 40)
        self._anim.setEasingCurve(EASE_OUT)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def value(self) -> str:
        return self._options[self._index][0]

    def set_value(self, value: str, animate: bool = False) -> None:
        idx = next((i for i, (v, _l) in enumerate(self._options) if v == value), 0)
        self._index = idx
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._x)
            self._anim.setEndValue(float(idx))
            self._anim.start()
        else:
            self._x = float(idx)
            self.update()

    def set_labels(self, labels: list[str]) -> None:
        self._options = [(v, labels[i]) for i, (v, _l) in enumerate(self._options)]
        self.update()

    def _get(self) -> float:
        return self._x

    def _set(self, v: float) -> None:
        self._x = v
        self.update()

    highlight = Property(float, _get, _set)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        seg = self.width() / len(self._options)
        idx = max(0, min(len(self._options) - 1, int(e.position().x() // seg)))
        if idx != self._index:
            self.set_value(self._options[idx][0], animate=True)
            self.changed.emit(self.value())

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        seg = r.width() / len(self._options)
        hl = QRectF(r.left() + seg * self._x + 3, r.top() + 3, seg - 6, r.height() - 6)
        p.setBrush(QColor(255, 255, 255, 58))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(hl, hl.height() / 2, hl.height() / 2)
        p.setFont(theme.font(12.5, theme.QFont.Weight.Medium))
        for i, (_v, label) in enumerate(self._options):
            near = max(0.0, 1.0 - abs(self._x - i))
            p.setPen(QColor(255, 255, 255, int(150 + 105 * near)))
            p.drawText(QRectF(r.left() + seg * i, r.top(), seg, r.height()), Qt.AlignmentFlag.AlignCenter, label)


class StatusPill(QWidget):
    """Dot + short text: Ready / Loading models… / Live · 14 fps."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = ""
        self._color = theme.TEXT_TERTIARY
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(28)

    def set_status(self, text: str, color: QColor, pulse: bool = False) -> None:
        self._text = text
        self._color = color
        if pulse and not self._timer.isActive():
            self._timer.start()
        elif not pulse:
            self._timer.stop()
            self._pulse = 0.0
        fm = self.fontMetrics()
        self.setFixedWidth(fm.horizontalAdvance(text) + 44)
        self.update()

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.033) % 2.0  # slow 2 s breathing
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        c = QPointF(r.left() + 15, r.center().y())
        if self._timer.isActive():
            halo = QColor(self._color)
            halo.setAlpha(int(90 * (0.5 + 0.5 * math.cos(self._pulse * math.pi))))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(c, 4, 4)
        p.setPen(theme.TEXT)
        p.setFont(self.font())
        p.drawText(r.adjusted(26, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


def labeled_row(label: QLabel, control: QWidget, parent: QWidget | None = None) -> QWidget:
    control.setAccessibleName(label.text())  # VoiceOver reads the row's label
    row = QWidget(parent)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lay.addWidget(label, 1)
    lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return row
