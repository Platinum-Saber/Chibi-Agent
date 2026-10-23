"""Raphael's chibi (blue coat outfit) drawn from vector parts with QPainter.

Style (Kryo's references, 2026-10-23, in ChibiAgent/references/chibi/vector-2026-10-23/):
the Tensura mini-chibi look. The head and hair are about 60 % of her height,
the body a stubby block with mitten hands, flat cel fills with one shadow
tone, a bold outer outline over thin inner lines, huge eyes with a heavy upper
lash. The outfit is Kryo's pick (2026-10-23): a long blue coat with blue fur
cuffs, a cream fur scarf with one tail, black baggy pants and blue boots with
fur tops. Raphael's own parts: the ruby eyes and the halo.

Hair is built from clumps: each clump is a spine curve (root to tip) swept
into a tapered ribbon, so a clump bends as one piece when its spine bends.
The front clumps are unioned to draw one bold silhouette over thin inner
edges.

`draw_raphael(p, pose, t)` draws one frame in rig units: the box is 100 x 140,
feet at (50, 140), y down; the halo reaches about y = -12. The caller sets the
painter transform. Colours: docs/character.md palette.
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)

from .pose import Brows, Eyes, Mouth, Pose

HAIR, HAIR_SHADE, HAIR_LINE = QColor("#B4E2F7"), QColor("#7CC4EC"), QColor("#3E8FD6")
RUBY, RUBY_DARK, PUPIL = QColor("#D4243A"), QColor("#8E1426"), QColor("#4A0A14")
SKIN, SKIN_SHADE, SKIN_PINK = QColor("#FDEDE4"), QColor("#F4CFC3"), QColor("#F3B3B3")
WHITE, CLOTH_SHADE, SCLERA_SHADE = QColor("#FBFCFF"), QColor("#D3DAEC"), QColor("#DCEBF7")
GOLD, GOLD_DARK, GEM = QColor("#D8B45A"), QColor("#9E7A2C"), QColor("#C8372D")
CYAN, VIOLET = QColor("#7FE3FF"), QColor("#A57BFF")
INK = QColor("#1F222B")
MOUTH_DARK, TONGUE = QColor("#7A2633"), QColor("#E98390")
BLUSH, TEAR = QColor("#F48A9A"), QColor("#BFE9FF")
COAT, COAT_SHADE, COAT_LIGHT, FUR_BLUE = QColor("#3D5EA6"), QColor("#2C447F"), QColor("#7393D6"), QColor("#86A6E0")
SCARF, SCARF_SHADE, PANTS = QColor("#ECDDAB"), QColor("#CDB57F"), QColor("#2A2C35")

LINE = 0.7          # inner lines, rig units (1 unit ~ 2.3 dip at height 320)
BOLD = 1.5          # outer silhouettes
NECK = (50.0, 92.0)  # head pivot


# --- path helpers --------------------------------------------------------------------------------
def smooth(pts, closed: bool = True) -> QPainterPath:
    """Catmull-Rom through `pts`; a point given as (x, y, True) is a sharp corner.
    Cached: most parts are the same every frame (rounded to 0.01 rig units)."""
    return _smooth(tuple((round(q[0], 2), round(q[1], 2), *q[2:]) for q in pts), closed)


@lru_cache(maxsize=4096)
def _smooth(pts, closed: bool) -> QPainterPath:
    P = [QPointF(q[0], q[1]) for q in pts]
    sharp = [len(q) > 2 and q[2] for q in pts]
    n = len(P)
    path = QPainterPath(P[0])
    for i in range(n if closed else n - 1):
        a, b = P[i], P[(i + 1) % n]
        prev = P[(i - 1) % n] if (closed or i > 0) else a
        nxt = P[(i + 2) % n] if (closed or i + 2 < n) else b
        c1 = a if sharp[i] else a + (b - prev) / 6
        c2 = b if sharp[(i + 1) % n] else b - (nxt - a) / 6
        path.cubicTo(c1, c2, b)
    if closed:
        path.closeSubpath()
    return path


def mirror(pts):
    return [(100 - q[0], *q[1:]) for q in pts]


def bend(pts, sway: float, top: float = 60.0, span: float = 60.0, amount: float = 6.0):
    """Shift points below `top` sideways by sway * amount, growing with depth squared."""
    out = []
    for q in pts:
        d = max(0.0, (q[1] - top) / span)
        out.append((q[0] + sway * amount * d * d, *q[1:]))
    return out


def ribbon(spine, w_root: float, w_mid: float | None = None, steps: int = 12) -> QPainterPath:
    return _ribbon(tuple((round(q[0], 2), round(q[1], 2)) for q in spine), w_root, w_mid, steps)


@lru_cache(maxsize=1024)
def _ribbon(spine, w_root: float, w_mid: float | None, steps: int) -> QPainterPath:
    """A hair clump: `spine` (root to tip) swept into a ribbon that tapers to a point.
    The width bulges to `w_mid` a third of the way down, which gives the clump its leaf shape."""
    w_mid = w_root * 1.1 if w_mid is None else w_mid
    sp = smooth(spine, False)
    left, right = [], []
    for k in range(steps + 1):
        t = k / steps
        c = sp.pointAtPercent(t)
        a = math.radians(sp.angleAtPercent(t))
        n = QPointF(math.sin(a), math.cos(a))  # left normal in y-down coordinates
        w = (w_root + (w_mid - w_root) * t / 0.33 if t < 0.33 else w_mid * ((1 - t) / 0.67) ** 0.85) / 2
        left.append((c.x() + n.x() * w, c.y() + n.y() * w))
        right.append((c.x() - n.x() * w, c.y() - n.y() * w))
    tip = sp.pointAtPercent(1.0)
    return smooth([(*left[0], True), *left[1:-1], (tip.x(), tip.y(), True), *right[-2:0:-1], (*right[0], True)])


def fluff(cx: float, cy: float, rx: float, ry: float, n: int = 18, jag: float = 0.22) -> list[tuple]:
    """Points of a furry edge: an ellipse with sharp, uneven tufts."""
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        r = 1.0 + (jag if k % 2 else 0.0) * (0.75 + 0.5 * ((k * 7919) % 13) / 13)
        pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r, True))
    return pts


def pen(color: QColor, w: float = LINE) -> QPen:
    pn = QPen(color, w)
    pn.setCapStyle(Qt.PenCapStyle.RoundCap)
    pn.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pn


def fill(p: QPainter, path: QPainterPath, brush, outline: QColor | None = INK, w: float = LINE) -> None:
    p.setBrush(brush if isinstance(brush, QBrush) else QBrush(brush))
    p.setPen(pen(outline, w) if outline is not None else Qt.PenStyle.NoPen)
    p.drawPath(path)


def stroke(p: QPainter, path: QPainterPath, color: QColor, w: float = LINE) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen(color, w))
    p.drawPath(path)


def line(p: QPainter, pts, color: QColor = INK, w: float = LINE) -> None:
    stroke(p, smooth(pts, False), color, w)


def blob(p: QPainter, c: QPointF, rx: float, ry: float, color: QColor, outline: QColor | None = INK,
         w: float = LINE) -> None:
    p.setBrush(QBrush(color))
    p.setPen(pen(outline, w) if outline is not None else Qt.PenStyle.NoPen)
    p.drawEllipse(c, rx, ry)


def alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def vgrad(y0: float, y1: float, *stops) -> QBrush:
    g = QLinearGradient(0, y0, 0, y1)
    for i, c in enumerate(stops):
        g.setColorAt(i / (len(stops) - 1), c)
    return QBrush(g)


# --- shapes (rig units; symmetric parts given for the viewer's left) -----------------------------
# The Rimuru-style hair dome: wide and glossy, falling past her shoulders to pointed ends at her hips
BACK_HAIR = [(50, 10), (70, 13), (86, 25), (94, 44), (96, 66), (95, 88), (93, 106), (90, 122, True), (85, 112),
             (81, 123, True), (76, 108), (72, 98), (50, 99), (28, 98), (24, 108), (19, 123, True), (15, 112),
             (10, 122, True), (7, 106), (5, 88), (4, 66), (6, 44), (14, 25), (30, 13)]
BACK_STRANDS = [[(10, 70), (8.5, 92), (11, 114)], [(16, 80), (16, 100), (19, 116)]]
CROWN_STRANDS = [[(50, 14), (40, 22), (31, 32)], [(52, 14), (58, 22), (66, 30)], [(48, 15), (44, 24)]]
# Below the crown: the bangs are clipped to this, so their roots melt into the dome without an outline
BELOW_CROWN = [(8, 60), (13, 38), (27, 27), (50, 22.5), (73, 27), (87, 38), (92, 60), (92, 135, True),
               (8, 135, True)]
FACE = [(25.5, 56), (24.6, 72), (27.6, 84), (37.5, 90.8), (50, 92.4), (62.5, 90.8), (72.4, 84), (75.4, 72),
        (74.5, 56), (50, 47)]
# Bangs: (spine root -> tip, root width, mid width); the roots fan from the crown
BANGS = [
    ([(29, 26), (23.5, 50), (24.5, 74)], 10, 10),
    ([(71, 26), (76.5, 50), (75.5, 74)], 10, 10),
    ([(37, 20), (30.5, 44), (28, 61)], 10, 11),
    ([(63, 20), (69.5, 44), (72, 61)], 10, 11),
    ([(45, 17), (40.5, 44), (36.5, 60)], 10, 11),
    ([(56, 17), (59.5, 44), (63.5, 60)], 10, 11),
    ([(51, 16), (49.2, 46), (50.6, 64)], 9, 10),
    ([(47, 22), (51, 52), (47.6, 71)], 3.4, 3.8),  # the strand that falls between her eyes
]
# Long side locks, framing her face, down to her hips
LOCKS = [([(25, 42), (19, 70), (15.5, 98), (17, 112), (12.5, 121)], 10, 12),
         ([(28.5, 56), (26.2, 82), (24, 101), (25.6, 113)], 7, 8)]
COAT_BODY = [(35, 93.5), (65, 93.5), (70, 103), (73.5, 115), (77, 126.5, True), (63, 128), (52.5, 128.4, True),
             (50, 123.5, True), (47.5, 128.4, True), (37, 128), (23, 126.5, True), (26.5, 115), (30, 103)]
COAT_SHADE_L = [(30, 103), (35, 94), (39, 96), (37, 112), (35.5, 127.6), (23, 126.5), (26.5, 115)]
COAT_SEAMS = [[(50.6, 98), (50, 123.5)], [(42.5, 101), (40, 127.6)], [(58, 101), (60.5, 127.6)]]
COAT_GLINTS = [[(62, 99), (64.5, 108)], [(66, 112), (67.5, 119)], [(53, 104), (53.6, 112)]]
SCARF_TAIL = [(30, 96, True), (36.5, 97, True), (35, 106), (33.6, 116, True), (31.2, 118.6, True),
              (29.6, 116.4, True), (27.6, 118.8, True), (26, 116, True), (24.4, 117.8, True), (24.6, 112),
              (27.6, 105)]
EYE_L, EYE_R = (37.4, 70.6), (62.6, 70.6)
SHOULDER_L, SHOULDER_R = QPointF(32.5, 98), QPointF(67.5, 98)
HIP_L, HIP_R = QPointF(43.6, 124.5), QPointF(56.4, 124.5)


# --- parts -----------------------------------------------------------------------------------------
def halo(p: QPainter, glow: float, t: float) -> None:
    c, r = QPointF(50, 52 - 0.6 * math.sin(t * 1.3)), 52.0  # halo float
    p.save()
    p.setOpacity(0.72 + 0.28 * glow)
    if glow > 0:
        g = QRadialGradient(c, r + 16)
        g.setColorAt(0.6, alpha(GOLD, 0.0))
        g.setColorAt(0.85, alpha(GOLD, 0.5 * glow))
        g.setColorAt(1.0, alpha(GOLD, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r + 16, r + 16)
    for deg, length, w in ((90, 10, 2.4), (72, 5.5, 1.6), (108, 5.5, 1.6), (55, 8, 2.0), (125, 8, 2.0),
                           (40, 4.5, 1.4), (140, 4.5, 1.4)):
        a = math.radians(deg)
        u, n = QPointF(math.cos(a), -math.sin(a)), QPointF(math.sin(a), math.cos(a))
        base = c + u * (r - 0.5)
        spike = QPainterPath(base + n * w)
        spike.lineTo(base + u * length)
        spike.lineTo(base - n * w)
        spike.closeSubpath()
        fill(p, spike, GOLD, GOLD_DARK, 0.45)
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    arc = QPainterPath()
    arc.arcMoveTo(rect, 24)
    arc.arcTo(rect, 24, 132)
    stroke(p, arc, GOLD_DARK, 2.2)
    stroke(p, arc, GOLD, 1.3)
    for deg, s in ((90, 2.4), (55, 1.8), (125, 1.8)):
        a = math.radians(deg)
        q = c + QPointF(math.cos(a), -math.sin(a)) * r
        blob(p, q, s * 1.3, s * 1.4, GOLD, GOLD_DARK, 0.45)
        gem = QPainterPath(q + QPointF(0, -s * 1.15))
        for d in ((s * 0.85, 0), (0, s * 1.15), (-s * 0.85, 0)):
            gem.lineTo(q + QPointF(*d))
        gem.closeSubpath()
        fill(p, gem, GEM, QColor("#6E1414"), 0.4)
        blob(p, q + QPointF(-s * 0.25, -s * 0.4), s * 0.2, s * 0.28, alpha(WHITE, 0.9), None)
    p.restore()


def back_hair(p: QPainter, sway: float) -> None:
    fill(p, smooth(bend(BACK_HAIR, sway, 70, 55)), vgrad(30, 124, HAIR, HAIR, HAIR_SHADE), INK, BOLD)
    for pts in BACK_STRANDS:
        line(p, bend(pts, sway, 70, 55), alpha(HAIR_LINE, 0.55), 0.55)
        line(p, bend(mirror(pts), sway, 70, 55), alpha(HAIR_LINE, 0.55), 0.55)
    for pts in CROWN_STRANDS:
        line(p, pts, alpha(HAIR_LINE, 0.6), 0.55)
    # the slime-like gloss along the top of the dome
    line(p, [(22, 28), (28, 21), (35, 17)], alpha(WHITE, 0.95), 1.6)
    line(p, [(66, 17), (73, 21), (78, 26)], alpha(WHITE, 0.95), 1.6)
    for x, y, r in ((18.5, 33, 1.0), (82, 31.5, 1.1), (44, 14.5, 0.9)):
        blob(p, QPointF(x, y), r, r, alpha(WHITE, 0.95), None)


def clumps(spec, sway: float, top: float = 60.0) -> list[QPainterPath]:
    return [ribbon(bend(sp, sway, top), w0, w1) for sp, w0, w1 in spec]


_unions: dict[tuple, QPainterPath] = {}


def hair_group(p: QPainter, paths: list[QPainterPath], gloss: bool, key: tuple) -> None:
    """Clumps with thin inner edges and one bold silhouette around them all; `key` names
    the clumps and their bend, for the union cache."""
    union = _unions.get(key)
    if union is None:
        union = QPainterPath()
        for path in paths:
            union = union.united(path)
        if len(_unions) > 512:
            _unions.clear()
        _unions[key] = union
    fill(p, union, HAIR, INK, BOLD)
    for path in paths:
        fill(p, path, HAIR, alpha(INK, 0.85), LINE * 0.8)
    stroke(p, union, INK, BOLD)
    if gloss:
        p.save()
        p.setClipPath(union)
        for x, y, rx, ry in ((36, 41, 2.2, 1.2), (41.5, 38.5, 1.2, 0.8), (62, 40, 2.4, 1.2), (57, 37.5, 1.1, 0.7)):
            blob(p, QPointF(x, y), rx, ry, alpha(WHITE, 0.95), None)
        p.restore()


def bang_shadow(p: QPainter, paths: list[QPainterPath]) -> None:
    """The pink shade the bangs cast on her forehead, peeking between the tips."""
    p.save()
    p.setClipPath(smooth(FACE))
    p.translate(0.6, 2.8)
    for path in paths:
        fill(p, path, SKIN_PINK, None)
    p.restore()


def side_locks(p: QPainter, sway: float) -> None:
    for side, spec in ((-1, LOCKS), (1, [(mirror(sp), w0, w1) for sp, w0, w1 in LOCKS])):
        paths = clumps(spec, sway, 80)
        hair_group(p, paths, False, ("locks", side, round(sway, 2)))
        for sp, _, _ in spec:  # a strand line down each lock
            line(p, bend(sp[:-1], sway, 80), alpha(HAIR_LINE, 0.6), 0.5)


def face(p: QPainter) -> None:
    fill(p, smooth(FACE), SKIN, INK, BOLD)


def fur(p: QPainter, pts, color: QColor, shade: QColor | None = None) -> None:
    path = smooth(pts)
    fill(p, path, color, INK, LINE)
    if shade is not None:  # one shadow tone along the lower part
        p.save()
        p.setClipPath(path)
        r = path.boundingRect()
        y = r.center().y() + r.height() * 0.12
        fill(p, smooth([(r.left() - 1, y, True), (r.right() + 1, y - 1, True), (r.right() + 1, r.bottom() + 1, True),
                        (r.left() - 1, r.bottom() + 1, True)]), shade, None)
        p.restore()
        stroke(p, path, INK, LINE)


def coat(p: QPainter) -> None:
    path = smooth(COAT_BODY)
    fill(p, path, COAT, INK, BOLD)
    p.save()
    p.setClipPath(path)
    fill(p, smooth(COAT_SHADE_L), COAT_SHADE, None)
    p.restore()
    for pts in COAT_SEAMS:
        line(p, pts, COAT_SHADE, 0.8)
    for pts in COAT_GLINTS:
        line(p, pts, alpha(COAT_LIGHT, 0.9), 0.9)
    stroke(p, path, INK, BOLD)


def scarf(p: QPainter) -> None:
    fur(p, SCARF_TAIL, SCARF)
    line(p, [(31, 100), (29.6, 109), (28.6, 115)], SCARF_SHADE, 0.7)
    fur(p, fluff(50, 96.6, 21, 6.6, 28, 0.17), SCARF, SCARF_SHADE)


def legs(p: QPainter, pose: Pose) -> None:
    for hip, ang, side in ((HIP_L, pose.leg_l, -1), (HIP_R, -pose.leg_r, 1)):
        a = math.radians(ang)
        d = QPointF(-math.sin(a), math.cos(a))
        blob(p, hip + d * 3.2, 4.6, 3.8, PANTS, INK, LINE)  # baggy pants
        top, ankle = hip + d * 6.4, hip + d * 11.4
        p.setPen(pen(INK, 6.4 + 2 * LINE))
        p.drawLine(top, ankle)
        p.setPen(pen(COAT, 6.4))
        p.drawLine(top, ankle)
        foot = hip + d * 13.2 + QPointF(side * 1.0, 0)
        blob(p, foot, 4.6, 2.3, COAT, INK, LINE)
        line(p, [(foot.x() - side * 1.4, foot.y() - 1.6), (foot.x() + side * 2.4, foot.y() - 0.4)], COAT_LIGHT, 0.6)
        fur(p, fluff(top.x(), top.y(), 4.4, 1.9, 12, 0.35), FUR_BLUE)


def arms(p: QPainter, pose: Pose) -> None:
    """Coat sleeves with blue fur cuffs and mitten hands."""
    for shoulder, ang in ((SHOULDER_L, pose.arm_l), (SHOULDER_R, -pose.arm_r)):
        a = math.radians(ang)
        d = QPointF(-math.sin(a), math.cos(a))
        wrist = shoulder + d * 9.6
        blob(p, wrist + d * 4.4, 3.3, 3.4, SKIN, INK, LINE)  # mitten
        p.setPen(pen(INK, 6.6 + 2 * LINE))
        p.drawLine(shoulder, wrist)
        p.setPen(pen(COAT, 6.6))
        p.drawLine(shoulder, wrist)
        p.save()
        p.translate(wrist)
        p.rotate(ang)
        fur(p, fluff(0, 0, 4.4, 2.2, 12, 0.4), FUR_BLUE)
        p.restore()


def eye(p: QPainter, cx: float, cy: float, side: int, pose: Pose) -> None:
    """One eye, drawn with x pointing outward (side -1: viewer's left)."""
    p.save()
    p.translate(cx, cy)
    p.scale(side, 1)
    e = pose.eyes
    if e == Eyes.OPEN:
        lid = pose.lid
        ty = -4.6 + (lid * 7.0 if lid > 0 else lid * 2.4)  # the upper lash line
        sclera = smooth([(-6.0, ty + 0.4, True), (7.0, ty - 0.6, True), (7.2, 1.0), (4.6, 7.4), (0.4, 8.6),
                         (-4.2, 7.4), (-6.4, 2.0)])
        fill(p, sclera, WHITE, None)
        p.save()
        p.setClipPath(sclera)
        fill(p, smooth([(-7, ty - 1, True), (8, ty - 1, True), (8, ty + 2.6), (-7, ty + 2.6)]), SCLERA_SHADE, None)
        ic = QPointF(0.4 + pose.gaze_x * 2.0 * side, 1.4 + pose.gaze_y * 1.4)
        g = QLinearGradient(0, ic.y() - 6.6, 0, ic.y() + 6.6)
        g.setColorAt(0.0, RUBY_DARK)
        g.setColorAt(0.45, RUBY)
        g.setColorAt(1.0, QColor("#F2707E"))
        p.setBrush(QBrush(g))
        p.setPen(pen(RUBY_DARK, 0.6))
        p.drawEllipse(ic, 4.7, 6.6)
        blob(p, ic + QPointF(0, 0.8), 0.9, 3.2, PUPIL, None)
        blob(p, ic + QPointF(-1.8, -2.0), 1.8, 2.5, WHITE, None)
        blob(p, ic + QPointF(2.0, 3.6), 0.9, 0.9, WHITE, None)
        p.restore()
        # heavy upper lash: a filled bar, thickest in the middle, with a flick past the outer corner
        lash = smooth([(-6.6, ty + 1.0, True), (-2, ty - 1.1), (4, ty - 1.4), (8.6, ty - 1.4, True),
                       (7.4, ty + 1.2), (2, ty + 1.2), (-4, ty + 1.6)])
        fill(p, lash, INK, None)
        line(p, [(2.6, 8.4), (5.6, 6.6)], INK, 0.8)  # lower lash, outer half
    elif e == Eyes.CLOSED:
        line(p, [(-6.0, 1.2), (0.6, 4.0), (7.2, 0.8), (8.6, -0.6)], INK, 1.6)
    elif e == Eyes.HAPPY:
        line(p, [(-5.6, 3.6), (0.6, -3.0), (6.8, 3.6)], INK, 1.8)
    elif e == Eyes.SQUEEZE:
        stroke(p, smooth([(6.0, -4.0, True), (-4.2, 0.8, True), (6.0, 5.2, True)], False), INK, 1.8)
    elif e == Eyes.DIZZY:
        spiral = QPainterPath(QPointF(0.4, 1.4))
        for k in range(1, 44):
            th = k * 0.3
            r = 0.3 + th * 0.5
            spiral.lineTo(QPointF(0.4 + r * math.cos(th), 1.4 + r * math.sin(th)))
        stroke(p, spiral, INK, 0.9)
    elif e == Eyes.BLANK:
        blank = QPainterPath()
        blank.addEllipse(QPointF(0.6, 1.2), 5.8, 6.4)
        fill(p, blank, WHITE, INK, 1.1)
    p.restore()


def brows(p: QPainter, kind: Brows, dx: float, dy: float) -> None:
    if kind == Brows.NONE:
        return
    shapes = {
        Brows.CALM: [(-3.6, -10.6), (0.4, -11.6), (4.2, -11.0)],
        Brows.ANGRY: [(-4.0, -9.6), (0.4, -11.2), (4.2, -12.6)],
        Brows.WORRIED: [(-4.0, -12.6), (0.4, -11.6), (4.2, -9.8)],
        Brows.RAISED: [(-3.6, -13.0), (0.4, -14.2), (4.2, -13.4)],
    }
    for (cx, cy), side in ((EYE_L, -1), (EYE_R, 1)):
        pts = [(cx + dx + side * x, cy + dy + y) for x, y in shapes[kind]]
        line(p, pts, WHITE, 3.0)  # a light halo so the brow reads over the bangs
        line(p, pts, INK, 1.4)


def mouth(p: QPainter, pose: Pose, dx: float, dy: float) -> None:
    p.save()
    p.translate(50 + dx, 84.2 + dy)
    p.scale(1.35, 1.35)
    m, o = pose.mouth, pose.mouth_open
    if m in (Mouth.NEUTRAL, Mouth.SMILE, Mouth.FROWN) and o >= 0.08:
        m = Mouth.OPEN
    if m == Mouth.NEUTRAL:
        line(p, [(-1.0, 0), (1.0, 0)], INK, 0.6)
    elif m == Mouth.SMILE:
        line(p, [(-2.0, -0.6), (0, 0.9), (2.0, -0.6)], INK, 0.6)
    elif m == Mouth.FROWN:
        line(p, [(-1.7, 0.7), (0, -0.4), (1.7, 0.7)], INK, 0.6)
    elif m == Mouth.POUT:
        line(p, [(-1.5, 0.3), (-0.5, -0.5), (0.5, 0.3), (1.4, -0.3)], INK, 0.6)
    else:
        if m == Mouth.SHOCK:
            shape = smooth([(0, -1.7, True), (2.0, 1.6, True), (-2.0, 1.6, True)])
        elif m == Mouth.WAIL:
            shape = smooth([(-2.9, -1.4, True), (2.9, -1.4, True), (1.9, 2.7), (-1.9, 2.7)])
        else:
            o = max(o, 0.35)
            shape = QPainterPath()
            shape.addEllipse(QPointF(0, 0.2 + o * 0.5), 1.1 + o * 0.5, 0.4 + o * 1.3)
        fill(p, shape, MOUTH_DARK, INK, 0.5)
        p.save()
        p.setClipPath(shape)
        r = shape.boundingRect()
        blob(p, QPointF(r.center().x(), r.bottom()), r.width() * 0.4, r.height() * 0.42, TONGUE, None)
        p.restore()
    p.restore()


def blush(p: QPainter, amount: float, dx: float) -> None:
    for x in (31.2, 68.8):
        blob(p, QPointF(x + dx, 80.2), 4.6, 2.2, alpha(BLUSH, 0.35 + 0.35 * amount), None)
        for k in (-1.5, 0, 1.5):
            line(p, [(x + dx + k + 0.5, 79.2), (x + dx + k - 0.5, 81.2)], alpha(QColor("#E0607A"), 0.45 + 0.5 * amount),
                 0.45)


def orb(p: QPainter, amount: float, t: float) -> None:
    if amount <= 0.01:
        return
    c = QPointF(50, 111 - 1.2 * math.sin(t * 2.0))
    r = 5.0 * amount
    g = QRadialGradient(c, r * 2.4)
    g.setColorAt(0.0, alpha(CYAN, 0.55))
    g.setColorAt(1.0, alpha(VIOLET, 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(c, r * 2.4, r * 2.4)
    g = QRadialGradient(c - QPointF(r * 0.3, r * 0.35), r)
    g.setColorAt(0.0, QColor("#F2FDFF"))
    g.setColorAt(0.45, CYAN)
    g.setColorAt(1.0, VIOLET)
    p.setBrush(QBrush(g))
    p.setPen(pen(INK, LINE))
    p.drawEllipse(c, r, r)
    for k in range(4):  # sparks
        a = t * 3 + k * math.pi / 2
        s = c + QPointF(math.cos(a), math.sin(a)) * r * 1.35
        line(p, [(s.x(), s.y()), (s.x() + math.cos(a + 0.8) * 1.8, s.y() + math.sin(a + 0.8) * 1.8)],
             alpha(VIOLET, 0.9 * amount), 0.6)


def star(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
    path = QPainterPath(c + QPointF(0, -r))
    for k in range(1, 8):
        a = -math.pi / 2 + k * math.pi / 4
        rr = r if k % 2 == 0 else r * 0.34
        path.lineTo(c + QPointF(math.cos(a) * rr, math.sin(a) * rr))
    path.closeSubpath()
    fill(p, path, color, INK, 0.45)


def text(p: QPainter, s: str, at: QPointF, size: float, color: QColor) -> None:
    p.save()
    p.translate(at)
    p.scale(size / 20, size / 20)  # glyphs at 20 px, scaled into rig units
    f = QFont("Segoe UI", 20)
    f.setBold(True)
    p.setFont(f)
    p.setPen(color)
    p.drawText(QPointF(0, 0), s)
    p.restore()


def effects(p: QPainter, pose: Pose, t: float, dx: float, dy: float) -> None:
    if pose.tears:
        for x, side in ((EYE_L[0] - 5, -1), (EYE_R[0] + 5, 1)):
            line(p, [(x + dx, 74 + dy), (x + dx + side * 0.8, 81), (x + dx + side * 0.4, 89)], alpha(TEAR, 0.95), 2.4)
            ph = (t * 1.6) % 1.0
            blob(p, QPointF(x + dx + side * (2.5 + 7 * ph), 73 - 5 * ph + 11 * ph * ph), 1.2, 1.6, TEAR,
                 alpha(HAIR_LINE, 0.7), 0.4)
    if pose.sweat:
        fill(p, smooth([(84, 46, True), (86.2, 51.6), (84, 53.6), (81.8, 51.6)]), TEAR, INK, 0.5)
    if pose.zzz:
        for k, (x, y, s) in enumerate(((78, 30, 6), (85, 21, 8), (92, 11, 10))):
            text(p, "z" if k < 2 else "Z", QPointF(x, y + math.sin(t * 1.5 + k) * 0.8), s,
                 alpha(QColor("#5B7FB3"), 0.95))
    if pose.dots:
        for k, (x, y, r) in enumerate(((84, 30, 1.2), (89, 24, 1.7), (95, 17, 2.3))):
            on = (t * 2 - k) % 4 < 3
            blob(p, QPointF(x, y), r, r, WHITE if on else alpha(WHITE, 0.35), INK, 0.45)
    if pose.alert:
        c = QPointF(88, 14)
        fill(p, smooth([(c.x(), c.y() - 7, True), (c.x() + 6.4, c.y() + 4.2, True), (c.x() - 6.4, c.y() + 4.2, True)]),
             QColor("#FFD24A"), INK, LINE)
        text(p, "!", QPointF(c.x() - 1.15, c.y() + 3.3), 8.5, INK)
    if pose.sparkles:
        for k, (x, y, r) in enumerate(((10, 30, 3.0), (90, 34, 2.4), (94, 62, 3.2), (6, 60, 2.2))):
            star(p, QPointF(x, y), r * (0.75 + 0.25 * math.sin(t * 3 + k * 1.7)), QColor("#FFE9A8"))
    if pose.dizzy:
        for k in range(3):
            a = t * 2.4 + k * 2 * math.pi / 3
            star(p, QPointF(50 + 24 * math.cos(a), 4 + 4 * math.sin(a)), 2.6, QColor("#FFD24A"))


# --- the whole figure ----------------------------------------------------------------------------
def draw_raphael(p: QPainter, pose: Pose, t: float = 0.0) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(50, 140 - pose.lift)
    p.scale(1, pose.squash)
    p.rotate(pose.body_tilt)
    p.translate(-50, -140)
    dx, dy = pose.head_turn * 3.5, pose.head_nod * 2.0
    sway = pose.hair_sway

    def head():
        p.translate(*NECK)
        p.rotate(pose.head_tilt)
        p.translate(-NECK[0], -NECK[1])

    p.save(); head(); halo(p, pose.halo_glow, t); back_hair(p, sway); p.restore()
    legs(p, pose)
    coat(p)
    scarf(p)
    p.save()
    head()
    face(p)
    bangs = clumps(BANGS, 0.0)
    bang_shadow(p, bangs)
    p.save()
    p.setClipPath(smooth(FACE))
    blush(p, pose.blush, dx)
    p.restore()
    eye(p, EYE_L[0] + dx, EYE_L[1] + dy, -1, pose)
    eye(p, EYE_R[0] + dx, EYE_R[1] + dy, 1, pose)
    mouth(p, pose, dx, dy)
    side_locks(p, sway)
    p.save()
    p.setClipPath(smooth(BELOW_CROWN))  # the roots melt into the dome
    hair_group(p, bangs, True, ("bangs",))
    p.restore()
    brows(p, pose.brows, dx, dy)
    p.restore()
    arms(p, pose)
    orb(p, pose.orb, t)
    p.save(); head(); effects(p, pose, t, dx, dy); p.restore()
    p.restore()
