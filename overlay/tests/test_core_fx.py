import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402

from chibi_overlay import core_fx  # noqa: E402
from chibi_overlay.core_fx import CoreFX  # noqa: E402


def run(fx, seconds, **kw):
    for _ in range(int(seconds * 30)):
        fx.update(1 / 30, **kw)


def test_geodesic_shapes():
    assert len(core_fx.SPHERE_V) == 42 and len(core_fx.SPHERE_E) == 120  # icosahedron subdivided once
    assert len(core_fx.CAGE_V) == 12 and len(core_fx.CAGE_E) == 30


def test_fades_in_while_thinking_and_out_after():
    fx = CoreFX()
    assert not fx.visible
    run(fx, 1.5, thinking=True, speaking=False, level=0.0)
    assert fx.alpha > 0.95 and fx.thinking
    run(fx, 2.0, thinking=False, speaking=False, level=0.0)
    assert not fx.visible


def test_thinking_spirals_the_shards_inward():
    fx = CoreFX()
    before = [s[1] for s in fx.shards]
    fx.update(0.1, thinking=True, speaking=False, level=0.0)
    after = [s[1] for s in fx.shards]
    assert sum(a < b for a, b in zip(after, before)) > len(before) * 0.8


def test_speaking_follows_the_voice():
    fx = CoreFX()
    run(fx, 1.0, thinking=False, speaking=True, level=1.0)
    loud = fx.level
    run(fx, 1.0, thinking=False, speaking=True, level=0.1)
    assert loud > 0.9 and fx.level < 0.2 and fx.visible and not fx.thinking


def test_paints_without_black_pixels():
    fx = CoreFX()
    run(fx, 1.0, thinking=True, speaking=False, level=0.0)
    img = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    fx.paint(p, QPointF(150, 150), 1.0)
    p.end()
    lit = dark = 0
    for y in range(0, 300, 3):
        for x in range(0, 300, 3):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                lit += 1
                dark += c.lightness() < 40  # an invalid (negative-alpha) colour paints black
    assert lit > 0 and dark == 0
