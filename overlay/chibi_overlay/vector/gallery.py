"""Pose gallery: every expression and review pose of the vector rig, as PNG sheets.

    uv run python -m chibi_overlay.vector.gallery OUT_DIR [--scale 2.4] [--size 320]

Writes gallery-light.png and gallery-dark.png (the overlay sits on any
wallpaper), plus actual-size.png: neutral at the overlay's height_dip.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")  # offscreen has no font database

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from .pose import GALLERY, NEUTRAL  # noqa: E402
from .raphael import draw_raphael  # noqa: E402

BOX = QRectF(-12, -16, 124, 160)  # rig units around her, halo and effects included
COLS = 6


def sheet(bg: str, fg: str, scale: float) -> QImage:
    cw, ch, label = BOX.width() * scale, BOX.height() * scale, 26
    rows = (len(GALLERY) + COLS - 1) // COLS
    img = QImage(int(cw * COLS), int((ch + label) * rows), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont("Segoe UI", 11)
    for i, (name, pose) in enumerate(GALLERY):
        x, y = (i % COLS) * cw, (i // COLS) * (ch + label)
        p.save()
        p.translate(x, y)
        p.scale(scale, scale)
        p.translate(-BOX.x(), -BOX.y())
        draw_raphael(p, pose, t=0.6)
        p.restore()
        p.setFont(f)
        p.setPen(QColor(fg))
        p.drawText(QRectF(x, y + ch, cw, label), Qt.AlignmentFlag.AlignCenter, name)
    p.end()
    return img


def actual_size(height_dip: int) -> QImage:
    """Neutral at the overlay's on-screen height (feet to halo top ~ 152 rig units)."""
    s = height_dip / 152
    img = QImage(int(BOX.width() * s) * 2, int(BOX.height() * s), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    for k, bg in enumerate(("#EEF1F6", "#1E222B")):
        p.fillRect(QRectF(k * img.width() / 2, 0, img.width() / 2, img.height()), QColor(bg))
        p.save()
        p.translate(k * img.width() / 2, 0)
        p.scale(s, s)
        p.translate(-BOX.x(), -BOX.y())
        draw_raphael(p, NEUTRAL, t=0.6)
        p.restore()
    p.end()
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scale", type=float, default=2.4)
    ap.add_argument("--size", type=int, default=320, help="height_dip for actual-size.png")
    a = ap.parse_args()
    app = QGuiApplication([])  # noqa: F841  (fonts need it)
    a.out.mkdir(parents=True, exist_ok=True)
    sheet("#EEF1F6", "#2B2F3A", a.scale).save(str(a.out / "gallery-light.png"))
    sheet("#1E222B", "#D8DEEA", a.scale).save(str(a.out / "gallery-dark.png"))
    actual_size(a.size).save(str(a.out / "actual-size.png"))
    # draw cost per frame at the overlay's size, for the perf budget
    img = QImage(400, 500, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.scale(a.size / 152, a.size / 152)
    t0 = time.perf_counter()
    for k in range(60):
        img.fill(Qt.GlobalColor.transparent)
        draw_raphael(p, NEUTRAL, t=k / 60)
    ms = (time.perf_counter() - t0) / 60 * 1000
    p.end()
    print(f"wrote {a.out}; draw_raphael {ms:.2f} ms/frame (raster, {a.size} dip)")


if __name__ == "__main__":
    main()
