"""Render the Mirage app icon (PNG + .icns) without opening a window.

    venv/bin/python scripts/make_icon.py

Writes assets/icon/mirage-1024.png, assets/icon/mirage-256.png and, on macOS,
assets/icon/Mirage.icns (via sips + iconutil).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTransform,
)

REPO = Path(__file__).resolve().parent.parent
CANVAS = 1024
BODY = 824                      # Apple macOS icon grid: 824 px body, 100 px margin
BODY_RADIUS = BODY * 0.225      # continuous-corner radius
ICONSET = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
           (256, 1), (256, 2), (512, 1), (512, 2)]

INDIGO = QColor("#4F46E5")
VIOLET = QColor("#9333EA")
TEAL = QColor("#14B8A6")

# One corner of Apple's continuous ("squircle") rounded rect, in units of the
# corner radius: u runs back along the incoming edge, v along the outgoing one.
_CORNER: list[tuple[str, tuple[float, ...]]] = [
    ("line", (1.52866471, 0.0)),
    ("cubic", (1.08849323, 0.0, 0.86840689, 0.0, 0.66993427, 0.06549600)),
    ("line", (0.63149399, 0.07491100)),
    ("cubic", (0.37282392, 0.16905899, 0.16906013, 0.37282401, 0.07491176, 0.63149399)),
    ("cubic", (0.0, 0.86840701, 0.0, 1.08849299, 0.0, 1.52866483)),
]


def squircle(rect: QRectF, radius: float) -> QPainterPath:
    r = min(radius, min(rect.width(), rect.height()) / 2 / 1.52866483)
    corners = [  # corner point, incoming direction, outgoing direction (clockwise)
        (rect.topRight(), (1, 0), (0, 1)),
        (rect.bottomRight(), (0, 1), (-1, 0)),
        (rect.bottomLeft(), (-1, 0), (0, -1)),
        (rect.topLeft(), (0, -1), (1, 0)),
    ]
    path = QPainterPath()
    for i, (c, d_in, d_out) in enumerate(corners):
        # corner-local (u, v) -> canvas: c - u*r*d_in + v*r*d_out
        t = QTransform(-r * d_in[0], -r * d_in[1], r * d_out[0], r * d_out[1], c.x(), c.y())
        for kind, a in _CORNER:
            pts = [t.map(QPointF(a[k], a[k + 1])) for k in range(0, len(a), 2)]
            if kind == "cubic":
                path.cubicTo(*pts)
            elif i == 0 and path.elementCount() == 0:
                path.moveTo(pts[0])
            else:
                path.lineTo(pts[0])
    path.closeSubpath()
    return path


def mask_path(cx: float, cy: float, s: float, tilt: float = 0.0, holes: bool = True) -> QPainterPath:
    """Theatre-mask silhouette (with eye and smile cut-outs) centred on cx, cy."""
    face = QPainterPath()
    face.moveTo(0.0, -1.02)
    face.cubicTo(0.56, -1.02, 0.98, -0.80, 0.98, -0.34)
    face.cubicTo(0.98, 0.10, 0.84, 0.46, 0.58, 0.76)
    face.cubicTo(0.38, 0.99, 0.18, 1.10, 0.0, 1.10)
    face.cubicTo(-0.18, 1.10, -0.38, 0.99, -0.58, 0.76)
    face.cubicTo(-0.84, 0.46, -0.98, 0.10, -0.98, -0.34)
    face.cubicTo(-0.98, -0.80, -0.56, -1.02, 0.0, -1.02)
    face.closeSubpath()

    cutouts = QPainterPath()
    for side in (1.0, -1.0):
        # almond eye, outer corner a touch higher
        cutouts.moveTo(side * 0.16, -0.18)
        cutouts.cubicTo(side * 0.26, -0.38, side * 0.58, -0.42, side * 0.70, -0.26)
        cutouts.cubicTo(side * 0.60, -0.08, side * 0.28, -0.04, side * 0.16, -0.18)
        cutouts.closeSubpath()
    # crescent smile
    cutouts.moveTo(-0.40, 0.36)
    cutouts.cubicTo(-0.18, 0.52, 0.18, 0.52, 0.40, 0.36)
    cutouts.cubicTo(0.30, 0.66, 0.12, 0.76, 0.0, 0.76)
    cutouts.cubicTo(-0.12, 0.76, -0.30, 0.66, -0.40, 0.36)
    cutouts.closeSubpath()

    if holes:
        # Odd-even fill punches the holes and keeps the curves exact (boolean
        # ops would flatten them into polygons at unit scale).
        face.addPath(cutouts)
        face.setFillRule(Qt.FillRule.OddEvenFill)
    t = QTransform()
    t.translate(cx, cy)
    t.rotate(tilt)
    t.scale(s, s)
    return t.map(face)


def to_array(img: QImage) -> np.ndarray:
    """BGRA view (premultiplied) of an ARGB32_Premultiplied image."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return arr[:, : img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def from_array(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    data = np.ascontiguousarray(arr, dtype=np.uint8)
    return QImage(data.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()


def new_layer() -> QImage:
    img = QImage(CANVAS, CANVAS, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    return img


def painter(img: QImage) -> QPainter:
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    return p


def shadow(path: QPainterPath, sigma: float, color: QColor, dx: float = 0, dy: float = 0) -> QImage:
    """Gaussian-blurred silhouette of `path` in `color` (alpha respected)."""
    layer = new_layer()
    p = painter(layer)
    p.translate(dx, dy)
    p.fillPath(path, QColor(255, 255, 255))
    p.end()
    alpha = to_array(layer)[:, :, 3].astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigma) * color.alphaF()
    out = np.empty((CANVAS, CANVAS, 4), np.float32)
    for i, channel in enumerate((color.blue(), color.green(), color.red())):
        out[:, :, i] = alpha * channel / 255.0          # premultiplied
    out[:, :, 3] = alpha
    return from_array(np.clip(out, 0, 255))


def render() -> QImage:
    body_rect = QRectF((CANVAS - BODY) / 2, (CANVAS - BODY) / 2, BODY, BODY)
    body = squircle(body_rect, BODY_RADIUS)
    icon = new_layer()
    p = painter(icon)

    # Grounding shadow under the tile (Apple grid: soft, slightly offset down).
    p.drawImage(0, 0, shadow(body, 14, QColor(10, 6, 40, 110), dy=10))
    p.drawImage(0, 0, shadow(body, 3, QColor(10, 6, 40, 60), dy=2))

    # Tile: diagonal indigo -> violet -> teal.
    p.setClipPath(body)
    grad = QLinearGradient(body_rect.topLeft(), body_rect.bottomRight())
    grad.setColorAt(0.0, INDIGO)
    grad.setColorAt(0.52, VIOLET)
    grad.setColorAt(1.0, TEAL)
    p.fillRect(body_rect, grad)

    # Colour bloom: a teal glow rising from the lower right, violet haze top right.
    for centre, radius, colour in (
        (QPointF(870, 900), 520, QColor(45, 212, 191, 140)),
        (QPointF(900, 160), 420, QColor(192, 132, 252, 90)),
        (QPointF(140, 820), 380, QColor(79, 70, 229, 110)),
    ):
        glow = QRadialGradient(centre, radius)
        glow.setColorAt(0.0, colour)
        glow.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
        p.fillRect(body_rect, glow)

    # Soft radial highlight, top left.
    hi = QRadialGradient(QPointF(320, 190), 660)
    hi.setColorAt(0.0, QColor(255, 255, 255, 84))
    hi.setColorAt(0.5, QColor(255, 255, 255, 22))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(body_rect, hi)

    # Gentle vignette for depth.
    vig = QRadialGradient(QPointF(512, 470), 640)
    vig.setColorAt(0.62, QColor(20, 10, 60, 0))
    vig.setColorAt(1.0, QColor(20, 10, 60, 70))
    p.fillRect(body_rect, vig)

    # Glyphs: a faint "reflection" mask behind, the frosted mask in front.
    echo = mask_path(590, 470, 222, tilt=11, holes=False)
    front = mask_path(490, 544, 236, tilt=-5)

    p.drawImage(0, 0, shadow(echo, 18, QColor(30, 12, 80, 55), dy=10))
    echo_fill = QLinearGradient(QPointF(700, 250), QPointF(520, 740))
    echo_fill.setColorAt(0.0, QColor(255, 255, 255, 86))
    echo_fill.setColorAt(1.0, QColor(153, 246, 228, 40))
    p.fillPath(echo, echo_fill)
    echo_rim = QLinearGradient(QPointF(560, 250), QPointF(700, 720))
    echo_rim.setColorAt(0.0, QColor(255, 255, 255, 170))
    echo_rim.setColorAt(1.0, QColor(255, 255, 255, 40))
    p.strokePath(echo, QPen(QBrush(echo_rim), 2.5))

    # Frosted glass: blur what is behind the front mask, then tint it white.
    p.end()
    behind = to_array(icon).astype(np.float32)
    behind = cv2.GaussianBlur(behind, (0, 0), 22)
    frosted = from_array(np.clip(behind, 0, 255))
    p = painter(icon)
    p.setClipPath(body)

    p.drawImage(0, 0, shadow(front, 26, QColor(24, 8, 70, 120), dy=22))
    p.drawImage(0, 0, shadow(front, 6, QColor(24, 8, 70, 70), dy=5))

    p.save()
    p.setClipPath(front, Qt.ClipOperation.IntersectClip)
    p.drawImage(0, 0, frosted)
    fill = QLinearGradient(QPointF(430, 300), QPointF(560, 800))
    fill.setColorAt(0.0, QColor(250, 248, 255, 226))
    fill.setColorAt(0.55, QColor(242, 238, 255, 206))
    fill.setColorAt(1.0, QColor(226, 234, 255, 184))
    p.fillPath(front, fill)

    # Inner shade along the lower edge gives the glass some thickness.
    rim_shade = new_layer()
    rp = painter(rim_shade)
    rp.fillRect(rim_shade.rect(), QColor(88, 60, 200, 70))
    rp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    rp.drawImage(0, 0, shadow(front, 10, QColor(0, 0, 0, 255), dy=-16))
    rp.end()
    p.drawImage(0, 0, rim_shade)

    # Specular arc across the forehead.
    spec = QPainterPath()
    spec.moveTo(292, 420)
    spec.cubicTo(300, 350, 380, 302, 478, 300)
    spec.cubicTo(400, 318, 334, 360, 292, 420)
    spec.closeSubpath()
    p.drawImage(0, 0, shadow(spec, 5, QColor(255, 255, 255, 255)))
    p.restore()

    # Glass rim: bright top-left, fading toward the bottom-right.
    rim = QLinearGradient(QPointF(300, 280), QPointF(640, 820))
    rim.setColorAt(0.0, QColor(255, 255, 255, 255))
    rim.setColorAt(0.5, QColor(255, 255, 255, 120))
    rim.setColorAt(1.0, QColor(255, 255, 255, 200))
    p.strokePath(front, QPen(QBrush(rim), 3.0))

    # Tile rim, Liquid Glass style: thin light edge, strongest at the top.
    edge = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
    edge.setColorAt(0.0, QColor(255, 255, 255, 120))
    edge.setColorAt(0.35, QColor(255, 255, 255, 28))
    edge.setColorAt(0.8, QColor(255, 255, 255, 14))
    edge.setColorAt(1.0, QColor(255, 255, 255, 60))
    p.setClipPath(body)
    p.strokePath(body, QPen(QBrush(edge), 5.0))
    p.end()
    return icon


def build_icns(master: Path, out: Path) -> None:
    if not (shutil.which("sips") and shutil.which("iconutil")):
        print("sips/iconutil not found (not macOS?) — skipping .icns")
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Mirage.iconset"
        iconset.mkdir()
        for size, scale in ICONSET:
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(master), "--out", str(iconset / name)],
                check=True, stdout=subprocess.DEVNULL,
            )
        subprocess.run(["iconutil", "-c", "icns", "-o", str(out), str(iconset)], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "assets" / "icon",
                        help="output directory (default: assets/icon)")
    parser.add_argument("--no-icns", action="store_true", help="only write the PNGs")
    args = parser.parse_args(argv)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    args.out.mkdir(parents=True, exist_ok=True)
    icon = render()
    master = args.out / "mirage-1024.png"
    small = args.out / "mirage-256.png"
    icon.save(str(master))
    icon.scaled(256, 256, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation).save(str(small))
    print(f"wrote {master.relative_to(REPO) if master.is_relative_to(REPO) else master}")
    print(f"wrote {small.relative_to(REPO) if small.is_relative_to(REPO) else small}")
    if not args.no_icns:
        icns = args.out / "Mirage.icns"
        build_icns(master, icns)
        if icns.exists():
            print(f"wrote {icns.relative_to(REPO) if icns.is_relative_to(REPO) else icns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
