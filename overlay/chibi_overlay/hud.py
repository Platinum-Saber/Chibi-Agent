"""2D overlays drawn with QPainter on top of the GL frame: her words in a glass panel beside
her, the thinking core, the task HUD, confirm buttons and the transform particles. Rects are recorded in desktop px
on the stage so clicks on them don't pass through."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen

from .core_fx import SIZE_DIP as CORE_SIZE_DIP

GOLD = QColor(216, 180, 90)
CYAN = QColor(127, 227, 255)
PANEL = QColor(16, 22, 34, 215)
CORE_REF_H = 320.0  # her height (logical px) at which the core has its designed size
TEAL = QColor(20, 200, 190)
GLASS_TINT = 0.20   # the glass panel's teal wash (Kryo: 20 %)
# Kryo's pick, loaded from [overlay] fonts_dir at startup (load_fonts); then installed fallbacks
PANEL_FONTS = ["Electroharmonix", "OCR A Extended", "Consolas"]


def load_fonts(folder) -> list[str]:
    """Register every .otf/.ttf under `folder` with Qt (for this app only); returns the families."""
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase
    families: list[str] = []
    if not folder or not Path(folder).is_dir():
        return families
    for f in sorted(Path(folder).rglob("*")):
        if f.suffix.lower() in (".otf", ".ttf"):
            i = QFontDatabase.addApplicationFont(str(f))
            if i >= 0:
                families += QFontDatabase.applicationFontFamilies(i)
    return families


def panel_font(size: float = 11.5, family: str = "") -> QFont:
    """The text panel's font: Kryo's pick (Customize -> Look), then the defaults as fallbacks."""
    f = QFont()
    f.setFamilies([family, *PANEL_FONTS] if family else PANEL_FONTS)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSizeF(size)
    return f


class Painter:
    """Converts desktop px <-> this window's logical px."""

    def __init__(self, widget, origin: tuple[int, int], dpr: float, stage):
        self.w, self.ox, self.oy, self.dpr, self.stage = widget, origin[0], origin[1], dpr, stage

    def to_local(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) / self.dpr, (y - self.oy) / self.dpr

    def record(self, name: str, r: QRectF) -> None:
        self.stage.ov.rects[name] = (r.left() * self.dpr + self.ox, r.top() * self.dpr + self.oy,
                                     r.right() * self.dpr + self.ox, r.bottom() * self.dpr + self.oy)

    def paint(self) -> None:
        st = self.stage
        p = QPainter(self.w)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fx, fy = self.to_local(*st.feet)
        h = st.size[st.form][0] / self.dpr
        if st.transform_progress() is not None:
            self._particles(p, st)
        now = time.monotonic()
        top = fy - h  # her head; the thinking core floats above it
        if st.core.visible and not st.hidden and st.draw_form():
            scale = h / CORE_REF_H
            r = CORE_SIZE_DIP * scale
            st.core.paint(p, QPointF(fx, top - r * 1.15), scale)
        if st.ov.bubble and now < st.ov.bubble_until and not st.hidden:
            half_w = st.size[st.form][1] / self.dpr
            self._bubble(p, st.ov.bubble, fx, top, half_w, h)
        else:
            st.ov.rects.pop("bubble", None)
        # chibi_only keeps the panel (task HUD, confirm buttons) on the chibi form
        if (st.form == "serious" or st.chibi_only) and (st.ov.hud or st.ov.confirm) and not st.hidden:
            self._panel(p, st, fx, fy - h)
        else:
            for k in ("hud", "yes", "no"):
                st.ov.rects.pop(k, None)
        p.end()

    def _bubble(self, p: QPainter, text: str, x: float, head_y: float, half_w: float, height: float) -> None:
        """Her words in a liquid-glass panel beside her (her right, or her left near the screen
        edge), level with her face. A layered window can't blur what's behind it, so the glass is
        frosted translucency: a soft shadow, a white-blue fill, a top sheen and a bright rim."""
        b = getattr(getattr(self.stage, "character", None), "behaviour", None)
        font = panel_font(b.panel_font_size, b.panel_font) if b else panel_font()
        p.setFont(font)
        text = text if len(text) < 600 else "…" + text[-600:]
        tr = QFontMetrics(font).boundingRect(0, 0, 320, 2000, Qt.TextFlag.TextWordWrap, text)
        bw, bh = tr.width() + 32, tr.height() + 24
        gap = 14
        bx = x + half_w + gap
        if bx + bw > self.w.width() - 8:  # no room on her right: her left
            bx = x - half_w - gap - bw
        bx = min(max(bx, 8), self.w.width() - bw - 8)
        by = min(max(head_y + height * 0.12, 8), self.w.height() - bh - 8)
        r = QRectF(bx, by, bw, bh)
        radius = 18.0
        p.save()
        for k, a in ((10, 18), (6, 26), (3, 34)):  # soft drop shadow
            sh = QPainterPath()
            sh.addRoundedRect(r.adjusted(-k / 2, -k / 2 + 6, k / 2, k / 2 + 6), radius + k / 2, radius + k / 2)
            p.fillPath(sh, QColor(6, 8, 20, a))
        body = QPainterPath()
        body.addRoundedRect(r, radius, radius)
        fill = QLinearGradient(r.topLeft(), r.bottomRight())
        fill.setColorAt(0.0, QColor(255, 255, 255, 40))
        fill.setColorAt(0.55, QColor(200, 240, 240, 20))
        fill.setColorAt(1.0, QColor(255, 255, 255, 26))
        p.fillPath(body, QBrush(fill))
        p.fillPath(body, QColor(TEAL.red(), TEAL.green(), TEAL.blue(), int(255 * GLASS_TINT)))  # the teal wash
        p.fillPath(body, QColor(6, 20, 26, 34))  # a little depth, so white text reads on light desktops
        sheen = QPainterPath()
        sheen.addRoundedRect(r.adjusted(2, 2, -2, -r.height() * 0.52), radius - 2, radius - 2)
        top = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.5))
        top.setColorAt(0.0, QColor(255, 255, 255, 70))
        top.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(sheen, QBrush(top))
        rim = QLinearGradient(r.topLeft(), r.bottomLeft())
        rim.setColorAt(0.0, QColor(255, 255, 255, 200))
        rim.setColorAt(0.5, QColor(150, 240, 230, 90))
        rim.setColorAt(1.0, QColor(255, 255, 255, 140))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(rim), 1.3))
        p.drawPath(body)
        inner = QPainterPath()
        inner.addRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1.5, radius - 1.5)
        p.setPen(QPen(QColor(10, 14, 30, 60), 1.0))
        p.drawPath(inner)
        box = r.adjusted(16, 12, -16, -12)
        p.setPen(QColor(0, 0, 0, 110))
        p.drawText(box.translated(0, 1), Qt.TextFlag.TextWordWrap, text)
        p.setPen(QColor(246, 249, 255))
        p.drawText(box, Qt.TextFlag.TextWordWrap, text)
        p.restore()
        self.record("bubble", r)

    def _panel(self, p: QPainter, st, fx: float, head_y: float) -> None:
        """Translucent HUD left of her: task title, items, progress, confirm buttons."""
        title_f, body_f = QFont("Segoe UI Semibold", 11), QFont("Segoe UI", 10)
        lines: list[str] = []
        title = "Analysis"
        if st.ov.hud:
            title, lines = st.ov.hud.title, list(st.ov.hud.items)
        c = st.ov.confirm
        if c:
            title = "Confirm: " + c.summary
            lines = [c.detail] if c.detail else []
        show_progress = bool(st.ov.hud and st.ov.hud.progress is not None and not c)
        w = 320
        body = "\n".join(lines)
        bh = QFontMetrics(body_f).boundingRect(0, 0, w - 28, 2000, Qt.TextFlag.TextWordWrap, body).height() if body else 0
        h = 44 + bh + (14 if show_progress else 0) + (44 if c else 0)
        x = max(fx - w - 60, 8)
        y = max(head_y, 8)
        r = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, PANEL)
        p.setPen(QPen(CYAN, 1.2))
        p.drawPath(path)
        p.setFont(title_f)
        p.setPen(QColor(230, 240, 255))
        p.drawText(QRectF(x + 14, y + 10, w - 28, 24), Qt.TextFlag.TextSingleLine, title)
        p.setFont(body_f)
        p.setPen(QColor(200, 215, 235))
        if body:
            p.drawText(QRectF(x + 14, y + 38, w - 28, bh), Qt.TextFlag.TextWordWrap, body)
        cy = y + 40 + bh
        if show_progress:
            p.fillRect(QRectF(x + 14, cy, w - 28, 4), QColor(255, 255, 255, 40))
            p.fillRect(QRectF(x + 14, cy, (w - 28) * max(0, min(1, st.ov.hud.progress)), 4), CYAN)
            cy += 14
        self.record("hud", r)
        if c:
            for i, (name, label, col) in enumerate((("yes", "Yes", GOLD), ("no", "No", QColor(140, 150, 170)))):
                br = QRectF(x + 14 + i * 104, cy + 4, 92, 30)
                bp = QPainterPath()
                bp.addRoundedRect(br, 8, 8)
                p.fillPath(bp, QColor(col.red(), col.green(), col.blue(), 70))
                p.setPen(QPen(col, 1.2))
                p.drawPath(bp)
                p.setPen(QColor(240, 244, 250))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, label)
                self.record(name, br)

    def _particles(self, p: QPainter, st) -> None:
        prog = st.transform_progress() or 0.0
        alpha = int(255 * (1 - abs(prog - 0.5) * 2) ** 0.5) if prog < 1 else 0
        p.setPen(Qt.PenStyle.NoPen)
        for pt in st.particles:
            x, y = self.to_local(pt.x, pt.y)
            c = QColor(GOLD if pt.gold else CYAN)
            c.setAlpha(alpha)
            p.setBrush(c)
            s = 2.5 + 1.5 * ((pt.phase * 7) % 1)
            p.drawEllipse(QRectF(x - s, y - s, 2 * s, 2 * s))
