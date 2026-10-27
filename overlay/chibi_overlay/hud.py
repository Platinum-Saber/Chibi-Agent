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
CORE_REF_H = 320.0  # her height (logical px) at which the core has its designed size
TEAL = QColor(20, 200, 190)
GLASS_TINT = 0.20   # the glass panel's teal wash (Kryo: 20 %)
MIN_W = 180         # narrowest a HUD card gets when it squeezes into a free side
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
        half_w = st.size[st.form][1] / self.dpr
        speech = None
        if st.ov.bubble and now < st.ov.bubble_until and not st.hidden:
            speech = self._bubble(p, st.ov.bubble, fx, top, half_w, h)
        else:
            st.ov.rects.pop("bubble", None)
        # chibi_only keeps the panel (task HUD, confirm buttons) on the chibi form
        if (st.form == "serious" or st.chibi_only) and (st.ov.hud or st.ov.confirm) and not st.hidden:
            self._panel(p, st, fx, top, half_w, h, speech)
        else:
            for k in ("hud", "yes", "no"):
                st.ov.rects.pop(k, None)
        p.end()

    def _font(self, bold: bool = False) -> QFont:
        b = getattr(getattr(self.stage, "character", None), "behaviour", None)
        font = panel_font(b.panel_font_size, b.panel_font) if b else panel_font()
        if bold:
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() + 0.5)
        return font

    def _glass(self, p: QPainter, r: QRectF, radius: float = 18.0) -> None:
        """The liquid-glass card every text panel uses. A layered window can't blur what's behind
        it, so the glass is frosted translucency: a soft shadow, a white-blue fill with the teal
        wash, a top sheen and a bright rim."""
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
        p.restore()

    def _text(self, p: QPainter, box: QRectF, text: str, flags=Qt.TextFlag.TextWordWrap,
              color: QColor | None = None) -> None:
        p.setPen(QColor(0, 0, 0, 110))  # a faint drop, so glass text reads on any wallpaper
        p.drawText(box.translated(0, 1), flags, text)
        p.setPen(color or QColor(246, 249, 255))
        p.drawText(box, flags, text)

    def _bubble(self, p: QPainter, text: str, x: float, head_y: float, half_w: float, height: float) -> QRectF:
        """Her words in a liquid-glass panel beside her (her right, or her left near the screen
        edge), level with her face."""
        font = self._font()
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
        self._glass(p, r)
        p.save()
        p.setFont(font)
        self._text(p, r.adjusted(16, 12, -16, -12), text)
        p.restore()
        self.record("bubble", r)
        return r

    def _panel(self, p: QPainter, st, fx: float, head_y: float, half_w: float, height: float,
               speech: QRectF | None = None) -> None:
        """Task HUD (title, items, progress) or confirm buttons, in the same glass as her words.
        It takes the side of her the speech panel doesn't; with no room there, it sits under it."""
        title_f, body_f = self._font(bold=True), self._font()
        lines: list[str] = []
        title = "Analysis"
        if st.ov.hud:
            title, lines = st.ov.hud.title, list(st.ov.hud.items)
        c = st.ov.confirm
        if c:
            title = "Confirm: " + c.summary
            lines = [c.detail] if c.detail else []
        show_progress = bool(st.ov.hud and st.ov.hud.progress is not None and not c)
        body = "\n".join(lines)
        wrap = Qt.TextFlag.TextWordWrap
        gap, W, H = 14, self.w.width(), self.w.height()
        right = fx + half_w + gap
        # as wide as its longest line (320 at most), narrower still to fit a free side
        natural = max(QFontMetrics(title_f).horizontalAdvance(title),
                      *(QFontMetrics(body_f).horizontalAdvance(ln) for ln in lines or [""]))
        w = min(max(natural + 34, 232 if c else MIN_W), 320)
        if speech is not None and not c:
            free = W - 8 - right if speech.center().x() < fx else fx - half_w - gap - 8
            if MIN_W <= free < w:
                w = free
        th = QFontMetrics(title_f).boundingRect(0, 0, w - 32, 2000, wrap, title).height()
        bh = QFontMetrics(body_f).boundingRect(0, 0, w - 32, 2000, wrap, body).height() if body else 0
        h = 12 + th + (8 + bh if body else 0) + (16 if show_progress else 0) + (46 if c else 0) + 14
        left = fx - half_w - gap - w
        y = head_y + height * 0.12
        if speech is None:
            x = right if right + w <= W - 8 else left
        else:
            x = right if speech.center().x() < fx else left  # the side her words don't use
            if x < 8 or x + w > W - 8:  # no room there: under her words
                x, y = speech.left(), speech.bottom() + 10
        x = min(max(x, 8), W - w - 8)
        y = min(max(y, 8), H - h - 8)
        r = QRectF(x, y, w, h)
        self._glass(p, r)
        p.save()
        p.setFont(title_f)
        self._text(p, QRectF(x + 16, y + 12, w - 32, th), title)
        cy = y + 12 + th
        if body:
            p.setFont(body_f)
            self._text(p, QRectF(x + 16, cy + 8, w - 32, bh), body, color=QColor(220, 240, 245))
            cy += 8 + bh
        if show_progress:
            cy += 8
            p.fillRect(QRectF(x + 16, cy, w - 32, 4), QColor(255, 255, 255, 50))
            p.fillRect(QRectF(x + 16, cy, (w - 32) * max(0, min(1, st.ov.hud.progress)), 4), CYAN)
            cy += 8
        self.record("hud", r)
        if c:
            p.setFont(body_f)
            for i, (name, label, col) in enumerate((("yes", "Yes", GOLD), ("no", "No", QColor(170, 185, 200)))):
                br = QRectF(x + 16 + i * 104, cy + 10, 92, 30)
                bp = QPainterPath()
                bp.addRoundedRect(br, 12, 12)
                p.fillPath(bp, QColor(col.red(), col.green(), col.blue(), 60))
                p.setPen(QPen(col, 1.2))
                p.drawPath(bp)
                self._text(p, br, label, Qt.AlignmentFlag.AlignCenter)
                self.record(name, br)
        p.restore()

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
