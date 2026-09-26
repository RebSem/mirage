"""Non-blocking toasts: slide up 8px and fade in, never a modal dialog."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from mirage import theme

LEVEL_COLOR = {"info": theme.ACCENT_2, "warn": theme.WARN, "error": theme.LIVE}
LEVEL_SECONDS = {"info": 3.2, "warn": 5.0, "error": 7.0}
MAX_WIDTH = 460
MAX_TOASTS = 3


class _Toast(QWidget):
    def __init__(self, host: "ToastHost", text: str, level: str):
        super().__init__(host)
        self.host = host
        self.text = text
        self.level = level
        self._t = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(12.5, theme.QFont.Weight.Medium))
        fm = self.fontMetrics()
        br = fm.boundingRect(0, 0, MAX_WIDTH - 52, 1000, Qt.TextFlag.TextWordWrap, text)
        self.resize(min(MAX_WIDTH, br.width() + 56), br.height() + 24)
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def _get(self) -> float:
        return self._t

    def _set(self, v: float) -> None:
        self._t = v
        self.host.layout_toasts()
        self.update()

    progress = Property(float, _get, _set)

    def appear(self) -> None:
        self._anim.setDuration(theme.TOAST_IN_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(int(LEVEL_SECONDS.get(self.level, 3.2) * 1000))
        self.show()

    def dismiss(self) -> None:
        self._timer.stop()
        self._anim.stop()
        self._anim.setDuration(theme.TOAST_OUT_MS)  # exits faster than it enters
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(lambda: self.host.remove(self))
        self._anim.start()

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self.dismiss()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._t)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.setBrush(QColor(22, 22, 32, 225))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(LEVEL_COLOR.get(self.level, theme.ACCENT_2))
        p.drawEllipse(QRectF(r.left() + 16, r.center().y() - 4, 8, 8))
        p.setPen(theme.TEXT)
        p.drawText(r.adjusted(34, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.text)


class ToastHost(QWidget):
    """Transparent overlay that stacks toasts above an anchor widget's bottom edge."""

    def __init__(self, parent: QWidget, anchor: QWidget):
        super().__init__(parent)
        self.anchor = anchor
        self._toasts: list[_Toast] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def show_toast(self, text: str, level: str = "info") -> None:
        for t in self._toasts:
            if t.text == text and t._t > 0:  # same message again: just keep it up
                t._timer.start(int(LEVEL_SECONDS.get(level, 3.2) * 1000))
                return
        while len(self._toasts) >= MAX_TOASTS:
            old = self._toasts.pop(0)
            old.deleteLater()
        toast = _Toast(self, text, level)
        self._toasts.append(toast)
        self.sync_geometry()
        self.raise_()
        self.show()
        toast.appear()

    def remove(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.deleteLater()
        self.layout_toasts()

    def sync_geometry(self) -> None:
        top_left = self.anchor.mapTo(self.parentWidget(), self.anchor.rect().topLeft())
        self.setGeometry(top_left.x(), top_left.y(), self.anchor.width(), self.anchor.height())
        self.layout_toasts()

    def layout_toasts(self) -> None:
        y = self.height() - 64
        for t in reversed(self._toasts):
            x = (self.width() - t.width()) // 2
            offset = int((1 - t._t) * theme.TOAST_SLIDE_PX)
            t.move(x, y - t.height() + offset)
            y -= t.height() + 8
        # only the toasts take clicks; the rest of the overlay stays click-through
        if self._toasts:
            region = None
            for t in self._toasts:
                region = t.geometry() if region is None else region.united(t.geometry())
            self.setMask(QRegion(region))
        else:
            self.hide()
