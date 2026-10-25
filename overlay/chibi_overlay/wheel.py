"""Right-click on her: a wheel of 8 poses beside her, to pick what she does.

Like a game's emote wheel: a thick ring of frosted-glass segments, each with a white silhouette
of her in that pose (overlay/icons/wheel/, rendered from her 3D body), the hovered one lit in
teal and its name in bold under the ring. `PoseWheel` is the state and geometry (desktop px;
pure Python apart from QRectF-free maths), `paint_wheel` draws it on the overlay window.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

ICONS = Path(__file__).resolve().parents[1] / "icons" / "wheel"
OUTER_DIP = 128.0  # ring radius at 100 % scaling
INNER_DIP = 66.0   # the hole
GAP_DIP = 26.0     # between her and the ring
GAP_DEG = 1.6      # between segments
IDLE_CLOSE_S = 8.0  # closes this long after the cursor left it


@dataclass(frozen=True)
class Pose:
    key: str     # Stage.perform key
    label: str


# clockwise from the top
POSES = (
    Pose("wave", "Wave"),
    Pose("cheer", "Cheer"),
    Pose("think", "Think"),
    Pose("look_around", "Look around"),
    Pose("stretch", "Stretch"),
    Pose("dance", "Dance"),
    Pose("sit", "Sit"),
    Pose("sleep", "Sleep"),
)


class PoseWheel:
    def __init__(self) -> None:
        self.open = False
        self.centre = (0.0, 0.0)  # desktop px
        self.outer = self.inner = 0.0  # px
        self.hover: int | None = None
        self._away_since: float | None = None

    def show(self, feet: tuple[float, float], height: float, half_width: float, scale: float,
             monitor: tuple[int, int, int, int]) -> None:
        """Open it beside her: to her right at chest height, to her left if the monitor ends."""
        self.outer, self.inner = OUTER_DIP * scale, INNER_DIP * scale
        gap = GAP_DIP * scale
        l, t, r, b = monitor
        x = feet[0] + half_width + gap + self.outer
        if x + self.outer > r:
            x = feet[0] - half_width - gap - self.outer
        label_room = 40 * scale  # the pose name under the ring
        y = min(max(feet[1] - height * 0.55, t + self.outer + 8), b - self.outer - label_room)
        self.centre = (x, y)
        self.open, self.hover, self._away_since = True, None, None

    def close(self) -> None:
        self.open, self.hover = False, None

    @property
    def rect(self) -> tuple[float, float, float, float]:
        """Its clickable box in desktop px (the ring and the name under it)."""
        x, y = self.centre
        return x - self.outer, y - self.outer, x + self.outer, y + self.outer + 40 * self.outer / OUTER_DIP

    def segment_at(self, x: float, y: float) -> int | None:
        """The pose under a desktop point: clockwise from the top; None in the hole or outside."""
        dx, dy = x - self.centre[0], y - self.centre[1]
        d = math.hypot(dx, dy)
        if not (self.inner <= d <= self.outer):
            return None
        angle = (math.degrees(math.atan2(dx, -dy)) + 360.0 + 180.0 / len(POSES)) % 360.0
        return int(angle // (360.0 / len(POSES)))

    def track(self, cursor: tuple[float, float]) -> None:
        """Hover follows the cursor; it closes itself a while after the cursor has left it."""
        self.hover = self.segment_at(*cursor)
        l, t, r, b = self.rect
        inside = l <= cursor[0] <= r and t <= cursor[1] <= b
        now = time.monotonic()
        if inside:
            self._away_since = None
        elif self._away_since is None:
            self._away_since = now
        elif now - self._away_since > IDLE_CLOSE_S:
            self.close()


# --- drawing (Qt) ---------------------------------------------------------------------------------
_icons: dict[str, object] = {}


def _icon(key: str):
    from PySide6.QtGui import QImage
    if key not in _icons:
        img = QImage(str(ICONS / f"{key}.png"))
        _icons[key] = None if img.isNull() else img
    return _icons[key]


def paint_wheel(widget, origin: tuple[int, int], dpr: float, wheel: PoseWheel) -> None:
    """Draw the open wheel on `widget` (an overlay window at desktop `origin`, `dpr` scale)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                               QRadialGradient)

    from .hud import GLASS_TINT, TEAL, panel_font

    if not wheel.open:
        return
    cx, cy = (wheel.centre[0] - origin[0]) / dpr, (wheel.centre[1] - origin[1]) / dpr
    ro, ri = wheel.outer / dpr, wheel.inner / dpr
    n = len(POSES)
    span = 360.0 / n
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def segment(i: int, grow: float = 0.0) -> QPainterPath:
        # Qt angles: degrees counter-clockwise from 3 o'clock; ours: clockwise from 12
        start = 90.0 - (i * span - span / 2 + GAP_DEG / 2)
        sweep = -(span - GAP_DEG)
        outer = QRectF(cx - ro - grow, cy - ro - grow, 2 * (ro + grow), 2 * (ro + grow))
        inner = QRectF(cx - ri, cy - ri, 2 * ri, 2 * ri)
        path = QPainterPath()
        path.arcMoveTo(outer, start)
        path.arcTo(outer, start, sweep)
        path.arcTo(inner, start + sweep, -sweep)
        path.closeSubpath()
        return path

    # a soft shadow under the ring, so the glass reads on light and dark wallpapers
    shadow = QRadialGradient(QPointF(cx, cy + 6), ro + 14)
    shadow.setColorAt((ri - 6) / (ro + 14), QColor(6, 8, 20, 0))
    shadow.setColorAt(0.86, QColor(6, 8, 20, 46))
    shadow.setColorAt(1.0, QColor(6, 8, 20, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(shadow))
    p.drawEllipse(QPointF(cx, cy + 6), ro + 14, ro + 14)

    for i, pose in enumerate(POSES):
        lit = i == wheel.hover
        path = segment(i, 4.0 if lit else 0.0)
        # frosted glass: a white-blue wash with the panels' teal tint; lit: teal, brighter
        glass = QRadialGradient(QPointF(cx, cy), ro + 4)
        if lit:
            glass.setColorAt(ri / ro, QColor(TEAL.red(), TEAL.green(), TEAL.blue(), 150))
            glass.setColorAt(1.0, QColor(90, 235, 225, 190))
        else:
            glass.setColorAt(ri / ro, QColor(255, 255, 255, 34))
            glass.setColorAt(1.0, QColor(210, 240, 245, 58))
        p.fillPath(path, QBrush(glass))
        p.fillPath(path, QColor(TEAL.red(), TEAL.green(), TEAL.blue(), int(255 * GLASS_TINT * (0.5 if lit else 0.35))))
        p.fillPath(path, QColor(6, 20, 26, 40))  # depth, so white icons read on light desktops
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 210 if lit else 150), 1.4 if lit else 1.1))  # the bright rim
        p.drawPath(path)
        # her silhouette in that pose, centred in the segment
        mid = math.radians(i * span)
        rm = (ro + ri) / 2 + (2.0 if lit else 0.0)
        ix, iy = cx + rm * math.sin(mid), cy - rm * math.cos(mid)
        size = (ro - ri) * (0.86 if lit else 0.78)
        img = _icon(pose.key)
        box = QRectF(ix - size / 2, iy - size / 2, size, size)
        if img is not None:
            w, h = img.width(), img.height()
            k = min(size / w, size / h)
            target = QRectF(ix - w * k / 2, iy - h * k / 2, w * k, h * k)
            p.setOpacity(1.0 if lit else 0.86)
            p.drawImage(target, img)
            p.setOpacity(1.0)
        else:  # no icon yet: the name, small
            p.setFont(panel_font(9.0))
            p.setPen(QColor(246, 249, 255))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, pose.label)

    # the hovered pose's name under the ring (like an emote wheel); "Poses" when none
    name = POSES[wheel.hover].label if wheel.hover is not None else "Poses"
    font = QFont(panel_font(15.0))
    font.setBold(True)
    p.setFont(font)
    label = QRectF(cx - ro, cy + ro + 4, 2 * ro, 32)
    p.setPen(QColor(0, 0, 0, 120))
    p.drawText(label.translated(0, 1.5), Qt.AlignmentFlag.AlignCenter, name.upper())
    p.setPen(QColor(250, 252, 255))
    p.drawText(label, Qt.AlignmentFlag.AlignCenter, name.upper())
    p.end()
