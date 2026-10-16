"""The transparent, always-on-top, click-through Live2D window (from spike 1).

One fixed full-monitor surface; she is drawn inside it and the window never
moves (moving a small surface flickered on the phone). Clicks pass through
everywhere except her pixels and the bubble: every frame reads the alpha under
the cursor, and WS_EX_TRANSPARENT is toggled only when that flips.

M1 scope: stand on the taskbar, look at the cursor, lip sync, bubble, and a
simple drag/drop. Her brain, physics and forms arrive in M2 (body/).
"""
from __future__ import annotations

import logging
import time

import live2d
import numpy as np
import OpenGL.GL as gl
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from chibi_shared.protocol import Bubble, Lip, MoodReq, Quit, Touch

from . import win32

log = logging.getLogger(__name__)

GRAVITY_DIP = 3000.0
DRAG_PX = 5
BUBBLE_HOLD_S = 6.0
BUBBLE_W_DIP = 300


class Overlay(QOpenGLWidget):
    def __init__(self, screen, rig: str, height_dip: int, link):
        super().__init__()
        self.scr, self.rig, self.height_dip, self.link = screen, rig, height_dip, link
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(screen.geometry())
        self.dpr = screen.devicePixelRatio()
        self.model: live2d.Model | None = None
        self.hwnd = 0

        # placement (physical px, y down); found by calibrating on the first frames
        self.calib = 0
        self.scale, self.k, self.base_c = 1.0, (1.0, 1.0), (0.0, 0.0)
        self.foot = [0.0, 0.0]
        self.floor = 0.0
        self.vy = 0.0
        self.head_top = 0.0

        # input
        self.cursor_in = False
        self.transparent: bool | None = None
        self.press = None
        self.dragging = False

        # agent-driven state
        self.mood = "idle"
        self.lip_target = 0.0
        self.lip = 0.0
        self.bubble_text = ""
        self.bubble_until = 0.0
        self.bubble_rect = QRectF()
        self.last_t = time.perf_counter()

        self.poll = QTimer(self)
        self.poll.setTimerType(Qt.TimerType.PreciseTimer)
        self.poll.timeout.connect(self._poll_cursor)
        self.frameSwapped.connect(self.update)

    # --- agent messages ---------------------------------------------------------
    def on_message(self, msg) -> None:
        if isinstance(msg, Lip):
            self.lip_target = max(0.0, min(1.0, msg.rms))
        elif isinstance(msg, Bubble):
            self.bubble_text = msg.text
            self.bubble_until = time.perf_counter() + (BUBBLE_HOLD_S if msg.done else 3600)
        elif isinstance(msg, MoodReq):
            self.mood = msg.mood
            if msg.mood == "thinking":
                self.bubble_text, self.bubble_until = "…", time.perf_counter() + 3600
            elif msg.mood == "listening":
                self.bubble_text = ""
        elif isinstance(msg, Quit):
            self.window().close()

    # --- win32 --------------------------------------------------------------------
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.hwnd:
            self.hwnd = int(self.winId())
            win32.add_exstyle(self.hwnd, win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW)
            self.poll.start(16)

    def _poll_cursor(self) -> None:
        on = not (self.cursor_in or self.dragging or self.press is not None)
        if on != self.transparent:
            win32.set_click_through(self.hwnd, on)
            self.transparent = on

    # --- GL -----------------------------------------------------------------------
    def initializeGL(self) -> None:
        live2d.glInit()
        log.info("GL_RENDERER=%s", gl.glGetString(gl.GL_RENDERER).decode())
        self.model = live2d.Model()
        self.model.LoadModelJson(self.rig)
        self.floor = (self.scr.availableGeometry().bottom() + 1 - self.scr.geometry().top()) * self.dpr

    def resizeGL(self, w: int, h: int) -> None:
        if self.model:
            self.model.Resize(int(w * self.dpr), int(h * self.dpr))

    def _fb(self) -> tuple[int, int]:
        return int(self.width() * self.dpr), int(self.height() * self.dpr)

    def _bbox(self):
        w, h = self._fb()
        a = np.frombuffer(gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE),
                          dtype=np.uint8).reshape(h, w, 4)[::-1, :, 3]
        ys, xs = np.nonzero(a > 8)
        return None if len(xs) == 0 else (xs.min(), ys.min(), xs.max(), ys.max())

    def _apply_offset(self) -> None:
        self.model.SetOffset((self.foot[0] - self.base_c[0]) / self.k[0],
                             (self.foot[1] - self.base_c[1]) / self.k[1])

    def _calibrate(self) -> bool:
        """Scale to height_dip, then learn how SetOffset maps to pixels (spike 1)."""
        bb = self._bbox()
        if bb is None:
            return False
        x0, y0, x1, y1 = bb
        cx, bot, hh = (x0 + x1) / 2, y1, y1 - y0
        if self.calib == 0:
            self.scale = self.height_dip * self.dpr / hh
            self.model.SetScale(self.scale)
        elif self.calib == 1:
            self.base_c = (cx, bot)
            self.model.SetOffset(0.1, 0.1)
        elif self.calib == 2:
            self.k = ((cx - self.base_c[0]) / 0.1, (bot - self.base_c[1]) / 0.1)
            self.foot = [self._fb()[0] * 0.85, self.floor]
            self._apply_offset()
        elif self.calib == 3:
            self.head_top = hh
            log.info("placed: %d px tall, feet at y=%d", hh, bot)
        return True

    def paintGL(self) -> None:
        t = time.perf_counter()
        dt, self.last_t = min(t - self.last_t, 0.05), t
        live2d.clearBuffer()
        if self.calib >= 4:
            self._physics(dt)
            self._drive(dt)
        self.model.Update()
        self.model.Draw()
        if self.calib < 4:
            self.calib += self._calibrate()
        else:
            self._sample_alpha()
            self._paint_bubble(t)

    def _drive(self, dt: float) -> None:
        # lip sync: fast attack, slower release, so syllables read clearly
        k = 0.6 if self.lip_target > self.lip else 0.25
        self.lip += (self.lip_target - self.lip) * k
        self.lip_target *= 0.85  # decays if the voice stops sending
        self.model.SetSaveParamById("ParamMouthOpenY", min(1.0, self.lip * 1.6), 1.0)  # survives Update()
        # gaze follows the cursor (window-local physical px)
        cx, cy = win32.cursor_pos()
        l, tp, _, _ = win32.window_rect(self.hwnd)
        self.model.Drag(cx - l, cy - tp)

    def _sample_alpha(self) -> None:
        cx, cy = win32.cursor_pos()
        l, tp, _, _ = win32.window_rect(self.hwnd)
        x, y = cx - l, cy - tp
        w, h = self._fb()
        inside = False
        if 0 <= x < w and 0 <= y < h:
            px = gl.glReadPixels(x, h - 1 - y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            alpha = px[3] if isinstance(px, (bytes, bytearray)) else int(np.asarray(px).ravel()[3])
            inside = alpha > 8 or self.bubble_rect.contains(x / self.dpr, y / self.dpr)
        self.cursor_in = inside

    def _paint_bubble(self, t: float) -> None:
        if not self.bubble_text or t > self.bubble_until:
            self.bubble_rect = QRectF()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", 11)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = self.bubble_text if len(self.bubble_text) < 600 else "…" + self.bubble_text[-600:]
        tr = fm.boundingRect(0, 0, BUBBLE_W_DIP - 24, 2000, Qt.TextFlag.TextWordWrap, text)
        bw, bh = tr.width() + 24, tr.height() + 18
        head_x, head_y = self.foot[0] / self.dpr, (self.foot[1] - self.head_top) / self.dpr
        x = min(max(head_x - bw / 2, 8), self.width() - bw - 8)
        y = max(head_y - bh - 18, 8)
        self.bubble_rect = QRectF(x, y, bw, bh)
        path = QPainterPath()
        path.addRoundedRect(self.bubble_rect, 14, 14)
        p.fillPath(path, QColor(250, 251, 255, 235))
        p.setPen(QPen(QColor(216, 180, 90), 1.5))  # gold trim
        p.drawPath(path)
        p.setPen(QColor(43, 47, 58))
        p.drawText(self.bubble_rect.adjusted(12, 9, -12, -9), Qt.TextFlag.TextWordWrap, text)
        p.end()

    # --- simple body until M2 -----------------------------------------------------
    def _physics(self, dt: float) -> None:
        if self.dragging:
            return
        if self.foot[1] < self.floor or self.vy:
            self.vy += GRAVITY_DIP * self.dpr * dt
            self.foot[1] += self.vy * dt
            if self.foot[1] >= self.floor:
                self.foot[1] = self.floor
                self.vy = -self.vy * 0.3 if self.vy > 600 * self.dpr else 0.0
            self._apply_offset()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.press = (e.globalPosition().toPoint(), list(self.foot))

    def mouseMoveEvent(self, e) -> None:
        if self.press is None:
            return
        d = (e.globalPosition().toPoint() - self.press[0]) * self.dpr
        if not self.dragging and (abs(d.x()) > DRAG_PX or abs(d.y()) > DRAG_PX):
            self.dragging, self.vy = True, 0.0
            self.link.send(Touch(t="hold", x=e.globalPosition().x(), y=e.globalPosition().y()))
        if self.dragging:
            self.foot[0] = min(max(self.press[1][0] + d.x(), 0), self._fb()[0])
            self.foot[1] = min(self.press[1][1] + d.y(), self.floor)
            self._apply_offset()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self.press is None:
            return
        g = e.globalPosition()
        if self.dragging:
            self.link.send(Touch(t="drop", x=g.x(), y=g.y()))
        else:
            self.model.StartRandomMotion("TapBody", live2d.MotionPriority.FORCE)
            self.link.send(Touch(t="poke", x=g.x(), y=g.y()))
        self.dragging, self.press = False, None
