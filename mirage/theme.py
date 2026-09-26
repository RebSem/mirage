"""Colours, sizes and the Qt style sheet.

The window is always dark (the native glass is forced to dark appearance), so
the palette is tuned for white text over tinted glass.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# ── colour ───────────────────────────────────────────────────────────────
TEXT = QColor(255, 255, 255, 235)
TEXT_SECONDARY = QColor(255, 255, 255, 150)
TEXT_TERTIARY = QColor(255, 255, 255, 95)
HAIRLINE = QColor(255, 255, 255, 38)
ACCENT = QColor("#8B7CFF")            # soft violet
ACCENT_2 = QColor("#5AC8FA")          # Apple-ish teal-blue for gradients
LIVE = QColor("#FF453A")              # system red (dark)
READY = QColor("#32D74B")             # system green (dark)
WARN = QColor("#FFD60A")
STAGE_BG = QColor(10, 10, 16, 235)
FALLBACK_GLASS = QColor(255, 255, 255, 26)   # used when native glass is unavailable
FALLBACK_WINDOW = QColor("#17161F")          # opaque window background without native glass
FALLBACK_EDGE = QColor(255, 255, 255, 46)

# ── geometry ─────────────────────────────────────────────────────────────
WINDOW_MIN = (1040, 680)
WINDOW_DEFAULT = (1240, 780)
MARGIN = 16
GAP = 14
RADIUS_PANEL = 28
RADIUS_STAGE = 30
RADIUS_BAR = 30
SIDEBAR_WIDTH = 332
CONTROL_BAR_HEIGHT = 76
TRAFFIC_LIGHTS_SPACE = 70
TITLEBAR_HEIGHT = 32

# ── motion (see docs/DESIGN.md) ──────────────────────────────────────────


def reduce_motion() -> bool:
    """macOS Accessibility → Display → Reduce motion."""
    try:
        import AppKit

        return bool(AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


_STILL = reduce_motion()
PRESS_MS = 0 if _STILL else 120        # button press feedback
SWITCH_MS = 0 if _STILL else 160       # toggles, segmented highlight
TOAST_IN_MS = 220                      # toasts only fade when motion is reduced
TOAST_OUT_MS = 160
TOAST_SLIDE_PX = 0 if _STILL else 8


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def rgba(color: QColor) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha() / 255:.3f})"


STYLE = f"""
* {{ color: {rgba(TEXT)}; }}
QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{
    background: rgba(30, 30, 40, 0.96); color: white;
    border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 6px 8px;
}}
QLabel#sectionTitle {{ color: {rgba(TEXT)}; }}
QLabel#hint {{ color: {rgba(TEXT_SECONDARY)}; }}
QLabel#faint {{ color: {rgba(TEXT_TERTIARY)}; }}

QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: rgba(255,255,255,0.16);
}}
QSlider::sub-page:horizontal {{
    height: 4px; border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT.name()}, stop:1 {ACCENT_2.name()});
}}
QSlider::handle:horizontal {{
    width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
    background: white; border: 0.5px solid rgba(0,0,0,0.15);
}}

QComboBox {{
    background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.14);
    border-radius: 14px; padding: 6px 30px 6px 12px; min-height: 18px;
}}
QComboBox:hover {{ background: rgba(255,255,255,0.15); }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: rgba(28, 28, 36, 0.98); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 4px; selection-background-color: {ACCENT.name()};
}}

QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QMenu {{
    background: rgba(30, 30, 40, 0.98); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT.name()}; }}
QLineEdit {{
    background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18);
    border-radius: 8px; padding: 6px 8px; selection-background-color: {ACCENT.name()};
}}
"""
