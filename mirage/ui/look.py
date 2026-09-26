"""The "Look" section: quality preset, blend, sharpness and a few toggles."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget

from mirage import theme
from mirage.i18n import tr
from mirage.settings import Settings
from mirage.ui.widgets import Segmented, Switch, labeled_row


def _label(text: str, size: float = 12.5, object_name: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setFont(theme.font(size))
    if object_name:
        lab.setObjectName(object_name)
    lab.setWordWrap(True)
    return lab


class LookPanel(QWidget):
    changed = Signal(str, object)   # settings field, new value

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.quality = Segmented([("fast", tr("quality_fast")), ("balanced", tr("quality_balanced")),
                                  ("best", tr("quality_best"))])
        self.quality.set_value(settings.quality)
        self.quality.changed.connect(self._on_quality)
        self.quality_hint = _label(tr(f"quality_hint_{settings.quality}"), 11.5, "hint")
        lay.addWidget(self.quality)
        lay.addWidget(self.quality_hint)

        self.blend = self._slider(settings.opacity)
        self.blend.valueChanged.connect(lambda v: self.changed.emit("opacity", v / 100))
        lay.addWidget(labeled_row(_label(tr("blend")), self.blend))

        self.sharpness = self._slider(settings.sharpness)
        self.sharpness.valueChanged.connect(lambda v: self.changed.emit("sharpness", v / 100))
        lay.addWidget(labeled_row(_label(tr("sharpness")), self.sharpness))

        self.mouth = self._switch("mouth_mask", settings.mouth_mask)
        mouth_row = labeled_row(_label(tr("keep_mouth")), self.mouth)
        mouth_row.setToolTip(tr("keep_mouth_hint"))
        lay.addWidget(mouth_row)

        self.more_toggle = Switch()
        self.more_toggle.toggled.connect(self._on_more)
        lay.addWidget(labeled_row(_label(tr("more_options"), 12.5, "hint"), self.more_toggle))

        self.more = QWidget()
        more = QVBoxLayout(self.more)
        more.setContentsMargins(0, 0, 0, 0)
        more.setSpacing(10)
        for field, key in (("many_faces", "many_faces"), ("color_fix", "color_fix"),
                           ("poisson_blend", "smooth_edges"), ("show_fps", "show_fps")):
            more.addWidget(labeled_row(_label(tr(key)), self._switch(field, getattr(settings, field))))
        self.more.setVisible(False)
        lay.addWidget(self.more)

    def _slider(self, value: float) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, 100)
        s.setValue(int(round(value * 100)))
        s.setFixedWidth(150)
        s.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        s.setCursor(Qt.CursorShape.PointingHandCursor)
        return s

    def _switch(self, field: str, on: bool) -> Switch:
        sw = Switch()
        sw.setChecked(on)
        sw.toggled.connect(lambda v, f=field: self.changed.emit(f, bool(v)))
        return sw

    def _on_quality(self, value: str) -> None:
        self.quality_hint.setText(tr(f"quality_hint_{value}"))
        self.changed.emit("quality", value)

    def _on_more(self, on: bool) -> None:
        self.more.setVisible(on)
