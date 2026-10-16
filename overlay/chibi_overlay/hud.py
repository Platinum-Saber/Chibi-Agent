"""2D overlays drawn with QPainter on top of the GL frame: bubble, serious-form HUD,
confirm buttons and the transform particles. Rects are recorded in desktop px
on the stage so clicks on them don't pass through."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen

INK = QColor(43, 47, 58)
PAPER = QColor(250, 251, 255, 235)
GOLD = QColor(216, 180, 90)
CYAN = QColor(127, 227, 255)
PANEL = QColor(16, 22, 34, 215)


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
        if st.ov.bubble and now < st.ov.bubble_until and not st.hidden:
            self._bubble(p, st.ov.bubble, fx, fy - h)
        else:
            st.ov.rects.pop("bubble", None)
        if st.form == "serious" and (st.ov.hud or st.ov.confirm) and not st.hidden:
            self._panel(p, st, fx, fy - h)
        else:
            for k in ("hud", "yes", "no"):
                st.ov.rects.pop(k, None)
        p.end()

    def _bubble(self, p: QPainter, text: str, head_x: float, head_y: float) -> None:
        font = QFont("Segoe UI", 11)
        p.setFont(font)
        text = text if len(text) < 600 else "…" + text[-600:]
        tr = QFontMetrics(font).boundingRect(0, 0, 276, 2000, Qt.TextFlag.TextWordWrap, text)
        bw, bh = tr.width() + 24, tr.height() + 18
        x = min(max(head_x - bw / 2, 8), self.w.width() - bw - 8)
        y = max(head_y - bh - 16, 8)
        r = QRectF(x, y, bw, bh)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, PAPER)
        p.setPen(QPen(GOLD, 1.5))
        p.drawPath(path)
        p.setPen(INK)
        p.drawText(r.adjusted(12, 9, -12, -9), Qt.TextFlag.TextWordWrap, text)
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
