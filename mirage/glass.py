"""Native macOS Liquid Glass behind Qt widgets.

Qt draws every widget into one AppKit view (QNSView). With a transparent
window, anything placed *below* that view in the window's frame view shows
through wherever Qt paints nothing. GlassWindow uses that to stack, bottom →
top:

    NSVisualEffectView   behind-window blur (the desktop, softly)
    ambient NSView       a tiny, blurred copy of the live video (colour glow)
    NSGlassEffectView…   one per registered widget, kept exactly behind it
    QNSView              all Qt widgets, transparent background

so the glass refracts the colours of your own video. Without macOS 26+
(or with "Reduce transparency" on) ``native`` is False and widgets paint a
translucent fill themselves.
"""

from __future__ import annotations

import logging
import sys

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

AMBIENT_SIZE = (40, 24)          # tiny on purpose: the layer scales it up smoothly
BRAND_BLOBS = (                  # (x, y, radius, BGR) for the idle glow
    (0.18, 0.25, 0.55, (229, 70, 79)),     # indigo
    (0.80, 0.30, 0.50, (234, 51, 147)),    # violet
    (0.55, 0.90, 0.60, (166, 184, 20)),    # teal
)


def _reduce_transparency() -> bool:
    try:
        import AppKit

        return bool(AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency())
    except Exception:
        return False


def glass_supported() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import AppKit

        return hasattr(AppKit, "NSGlassEffectView") and not _reduce_transparency()
    except Exception:
        return False


def idle_ambient() -> np.ndarray:
    """Soft brand-coloured glow shown before the camera starts (BGR)."""
    w, h = AMBIENT_SIZE
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.full((h, w, 3), (30, 18, 16), np.float32)
    for cx, cy, r, color in BRAND_BLOBS:
        d = np.sqrt(((xx / w) - cx) ** 2 + ((yy / h) - cy) ** 2) / r
        weight = np.clip(1.0 - d, 0.0, 1.0)[..., None] ** 2
        img = img * (1 - weight) + np.array(color, np.float32) * weight
    return np.clip(img, 0, 255).astype(np.uint8)


def ambient_from_frame(bgr: np.ndarray) -> np.ndarray:
    """Tiny, blurred, saturated, slightly darkened copy of a video frame."""
    small = cv2.resize(bgr, AMBIENT_SIZE, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 2.2)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.5, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 0.72, 0, 255)  # keep white text readable
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _cgimage(bgr: np.ndarray):
    import Foundation
    import Quartz

    h, w = bgr.shape[:2]
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
    data = Foundation.NSData.dataWithBytes_length_(rgba.tobytes(), rgba.nbytes)
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB),
        Quartz.kCGImageAlphaNoneSkipLast, provider, None, True, Quartz.kCGRenderingIntentDefault,
    )


class GlassWindow(QObject):
    """Owns the native glass stack of one top-level Qt window."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._entries: list[tuple[QWidget, float, object]] = []   # widget, radius, NSGlassEffectView
        self._ambient_layer = None
        self._installed = False
        self._sync_queued = False
        self.native = glass_supported()
        window.installEventFilter(self)

    # ── public API ───────────────────────────────────────────────────────

    def add(self, widget: QWidget, radius: float) -> None:
        """Keep a glass pane exactly behind ``widget`` (a descendant of the window)."""
        self._entries.append((widget, radius, None))
        widget.installEventFilter(self)
        if self._installed:
            self._create_glass(len(self._entries) - 1)
            self._queue_sync()

    def install(self) -> None:
        """Call once, after the window is shown (it needs the native window)."""
        if self._installed:
            return
        self._installed = True
        if not self.native:
            return
        try:
            self._setup_window()
            for i in range(len(self._entries)):
                self._create_glass(i)
            self.set_ambient(None)
            self._sync()
        except Exception:
            log.exception("native glass unavailable; falling back to Qt painting")
            self.native = False

    def set_ambient(self, bgr: np.ndarray | None, fade: float = 0.6) -> None:
        """Update the colour glow under the glass (None = idle brand glow)."""
        if not (self.native and self._ambient_layer is not None):
            return
        try:
            import Quartz

            image = idle_ambient() if bgr is None else ambient_from_frame(bgr)
            transition = Quartz.CATransition.animation()
            transition.setType_(Quartz.kCATransitionFade)
            transition.setDuration_(fade)
            self._ambient_layer.addAnimation_forKey_(transition, "contents")
            self._ambient_layer.setContents_(_cgimage(image))
        except Exception:
            log.exception("ambient update failed")

    # ── native plumbing ──────────────────────────────────────────────────

    def _content_view(self):
        import objc

        return objc.objc_object(c_void_p=int(self._window.winId()))

    def _setup_window(self) -> None:
        import AppKit
        import Quartz

        content = self._content_view()
        nswin = content.window()
        frame_view = content.superview()
        nswin.setTitlebarAppearsTransparent_(True)
        nswin.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        nswin.setStyleMask_(nswin.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
        nswin.setOpaque_(False)
        nswin.setBackgroundColor_(AppKit.NSColor.clearColor())
        nswin.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))

        backdrop = AppKit.NSVisualEffectView.alloc().initWithFrame_(frame_view.bounds())
        backdrop.setMaterial_(AppKit.NSVisualEffectMaterialUnderWindowBackground)
        backdrop.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        backdrop.setState_(AppKit.NSVisualEffectStateActive)
        backdrop.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        frame_view.addSubview_positioned_relativeTo_(backdrop, AppKit.NSWindowBelow, content)

        ambient = AppKit.NSView.alloc().initWithFrame_(frame_view.bounds())
        ambient.setWantsLayer_(True)
        ambient.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        layer = ambient.layer()
        layer.setContentsGravity_(Quartz.kCAGravityResizeAspectFill)
        layer.setMagnificationFilter_(Quartz.kCAFilterLinear)
        layer.setOpacity_(0.82)  # let a little of the desktop blur through
        frame_view.addSubview_positioned_relativeTo_(ambient, AppKit.NSWindowBelow, content)
        self._ambient_layer = layer

    def _create_glass(self, i: int) -> None:
        if not self.native:
            return
        import AppKit

        widget, radius, view = self._entries[i]
        if view is not None:
            return
        content = self._content_view()
        view = AppKit.NSGlassEffectView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 1, 1))
        view.setCornerRadius_(float(radius))
        view.setStyle_(AppKit.NSGlassEffectViewStyleRegular)
        # Directly below Qt's view → above the backdrop and ambient layers.
        content.superview().addSubview_positioned_relativeTo_(view, AppKit.NSWindowBelow, content)
        self._entries[i] = (widget, radius, view)

    def _queue_sync(self) -> None:
        if self._sync_queued:
            return
        self._sync_queued = True
        QTimer.singleShot(0, self._sync)

    def _sync(self) -> None:
        self._sync_queued = False
        if not (self.native and self._installed):
            return
        try:
            import AppKit

            height = self._content_view().frame().size.height
            for widget, _radius, view in self._entries:
                if view is None:
                    continue
                visible = widget.isVisible() and widget.window() is self._window
                view.setHidden_(not visible)
                if not visible:
                    continue
                top_left = widget.mapTo(self._window, QPoint(0, 0))
                view.setFrame_(AppKit.NSMakeRect(
                    top_left.x(), height - top_left.y() - widget.height(), widget.width(), widget.height()
                ))
        except Exception:
            log.exception("glass sync failed")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
                            QEvent.Type.Hide, QEvent.Type.LayoutRequest):
            self._queue_sync()
        return False
