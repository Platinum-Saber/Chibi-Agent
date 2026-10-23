"""The thinking core: a glowing geometric object above her head while she thinks or speaks.

Kryo's references: a geodesic wire sphere with bright nodes inside a larger low-poly cage,
tilted rings, a white-hot centre and square shards in cyan / violet / green light.
- Thinking: it rotates, and the shards spiral in toward the centre.
- Speaking: it keeps rotating; size and brightness follow the voice level (stage.lip).
It fades in and out. Drawn with QPainter by hud.Painter; the state lives on the stage.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient

CYAN, VIOLET, GREEN, WHITE = QColor(127, 227, 255), QColor(165, 123, 255), QColor(120, 230, 170), QColor(245, 250, 255)
SIZE_DIP = 70.0      # radius of the cage at rest, at her default height (scaled with her size)
FADE_S = 0.35        # fade in / out time constant
SHARDS = 26


def _icosahedron() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    n = [(x / math.hypot(x, y, z), y / math.hypot(x, y, z), z / math.hypot(x, y, z)) for x, y, z in v]
    return n, f


def _geodesic() -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    """An icosahedron subdivided once (42 points on the sphere) and its edges."""
    verts, faces = _icosahedron()
    verts = list(verts)
    mid: dict[tuple[int, int], int] = {}

    def m(a: int, b: int) -> int:
        k = (min(a, b), max(a, b))
        if k not in mid:
            x, y, z = [(verts[a][i] + verts[b][i]) / 2 for i in range(3)]
            r = math.hypot(x, y, z)
            verts.append((x / r, y / r, z / r))
            mid[k] = len(verts) - 1
        return mid[k]

    edges: set[tuple[int, int]] = set()
    for a, b, c in faces:
        ab, bc, ca = m(a, b), m(b, c), m(c, a)
        for tri in ((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)):
            for i in range(3):
                e = (tri[i], tri[(i + 1) % 3])
                edges.add((min(e), max(e)))
    return verts, sorted(edges)


SPHERE_V, SPHERE_E = _geodesic()
CAGE_V, _faces = _icosahedron()
CAGE_E = sorted({(min(a, b), max(a, b)) for f in _faces for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0]))})


def _c(col: QColor, a: float) -> QColor:
    """`col` at opacity `a` (clamped: a negative alpha makes an invalid QColor, drawn black)."""
    return QColor(col.red(), col.green(), col.blue(), max(0, min(255, int(a))))


def _rot(p, ay: float, ax: float, az: float = 0.0):
    x, y, z = p
    x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
    y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
    x, y = x * math.cos(az) - y * math.sin(az), x * math.sin(az) + y * math.cos(az)
    return x, y, z


class CoreFX:
    def __init__(self, seed: int = 7):
        self.alpha = 0.0     # 0 hidden .. 1 shown
        self.level = 0.0     # voice strength, smoothed
        self.spin = 0.0      # accumulated rotation
        self.thinking = False
        rng = random.Random(seed)
        # shards: angle, radius (x cage), height, size, speed
        self.shards = [[rng.uniform(0, 2 * math.pi), rng.uniform(0.3, 1.6), rng.uniform(-0.5, 0.5),
                        rng.uniform(0.05, 0.12), rng.uniform(0.6, 1.4)] for _ in range(SHARDS)]

    @property
    def visible(self) -> bool:
        return self.alpha > 0.01

    def update(self, dt: float, thinking: bool, speaking: bool, level: float) -> None:
        """Advance by `dt` s. Shown while `thinking` or `speaking`; `level` 0..1 is the voice."""
        self.thinking = thinking and not speaking
        want = 1.0 if (thinking or speaking) else 0.0
        self.alpha += (want - self.alpha) * (1 - math.exp(-dt / FADE_S))
        k = 0.5 if level > self.level else 0.15  # quick attack, slow release
        self.level += ((level if speaking else 0.0) - self.level) * k
        self.spin += dt * (0.9 if self.thinking else 0.55 + 0.6 * self.level)
        for s in self.shards:  # thinking: spiral inward, respawn outside; speaking: orbit
            s[0] += dt * s[4] * (1.6 if self.thinking else 0.7)
            if self.thinking:
                s[1] -= dt * 0.35 * s[4]
                if s[1] < 0.15:
                    s[1] = 1.6
            else:
                s[1] += (1.15 + 0.3 * math.sin(s[0] * 3) - s[1]) * min(1.0, dt * 1.5)

    def paint(self, p: QPainter, centre: QPointF, scale: float) -> None:
        """Draw at `centre` (logical px); `scale` = her size relative to the default."""
        if not self.visible:
            return
        a = self.alpha
        lv = self.level
        r = SIZE_DIP * scale * (1.0 + 0.35 * lv)       # expands with the voice
        bright = 0.55 + 0.45 * lv if not self.thinking else 0.75
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(centre)
        t = self.spin

        def proj(v, radius, ay, ax, az=0.0):
            x, y, z = _rot(v, ay, ax, az)
            f = 3.2 / (3.2 + z)  # perspective
            return QPointF(x * radius * f, y * radius * f), z

        # glow behind everything
        g = QRadialGradient(QPointF(0, 0), r * 1.6)
        g.setColorAt(0.0, QColor(255, 255, 255, int(230 * a * bright)))
        g.setColorAt(0.18, QColor(CYAN.red(), CYAN.green(), CYAN.blue(), int(150 * a * bright)))
        g.setColorAt(0.45, QColor(GREEN.red(), GREEN.green(), GREEN.blue(), int(60 * a * bright)))
        g.setColorAt(0.75, QColor(VIOLET.red(), VIOLET.green(), VIOLET.blue(), int(35 * a * bright)))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, 0), r * 1.6, r * 1.6)

        # outer cage: low-poly, counter-rotating
        pts = [proj(v, r * 1.25, -t * 0.6, 0.5 + t * 0.2, 0.2) for v in CAGE_V]
        for i, j in CAGE_E:
            (pa, za), (pb, zb) = pts[i], pts[j]
            depth = (2 - (za + zb) / 2) / 3
            p.setPen(QPen(_c(QColor(220, 240, 200), 140 * a * depth * bright), 1.0 * scale))
            p.drawLine(pa, pb)
        for q, z in pts:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(WHITE, 200 * a * (1 - z) / 2 * bright + 40 * a))
            p.drawEllipse(q, 2.2 * scale, 2.2 * scale)

        # rings
        for k, (tilt, col) in enumerate(((0.9, WHITE), (-1.2, CYAN))):
            ring = [proj((math.cos(u), 0, math.sin(u)), r * (0.95 + 0.12 * k), t * (0.8 - 0.3 * k), tilt)[0]
                    for u in (2 * math.pi * i / 32 for i in range(33))]
            p.setPen(QPen(_c(col, 170 * a * bright), (2.2 - k * 0.8) * scale))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(ring)

        # geodesic sphere
        pts = [proj(v, r * 0.72, t, 0.35 + t * 0.4) for v in SPHERE_V]
        for i, j in SPHERE_E:
            (pa, za), (pb, zb) = pts[i], pts[j]
            depth = (2 - (za + zb) / 2) / 3
            col = CYAN if (i + j) % 3 else VIOLET
            p.setPen(QPen(_c(col, 190 * a * depth * bright), 0.9 * scale))
            p.drawLine(pa, pb)
        for q, z in pts:
            if z < 0.2:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_c(WHITE, 230 * a * bright))
                p.drawEllipse(q, 1.6 * scale, 1.6 * scale)

        # shards
        for ang, rad, hgt, size, _sp in self.shards:
            pos, z = proj((math.cos(ang) * rad, hgt, math.sin(ang) * rad), r, t * 0.3, 0.4)
            s = size * r * (3.2 / (3.2 + z))
            col = WHITE if z < 0 else CYAN
            p.save()
            p.translate(pos)
            p.rotate(math.degrees(ang) * 1.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(col, 200 * a * (0.5 + 0.5 * bright) * max(0.15, (1.2 - z) / 2.2)))
            p.drawRect(QRectF(-s / 2, -s / 2, s, s))
            p.restore()

        # white-hot centre
        g = QRadialGradient(QPointF(0, 0), r * 0.38)
        g.setColorAt(0.0, QColor(255, 255, 255, int(255 * a)))
        g.setColorAt(0.5, QColor(255, 255, 255, int(160 * a * bright)))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, 0), r * 0.38, r * 0.38)
        p.restore()
