"""One transparent, always-on-top, click-through GL window per monitor (spike 1).

Each window is a fixed full-monitor surface; she is drawn inside whichever
window(s) she overlaps (she can be thrown across monitors). Clicks pass through
everywhere except her pixels and the bubble/HUD: each frame reads the alpha
under the cursor, and WS_EX_TRANSPARENT flips only when that changes.

The primary window ticks the stage once per vsync; the others only repaint
while she (or her particles) are near them.
"""
from __future__ import annotations

import logging
import time

import live2d
import numpy as np
import OpenGL.GL as gl
from PySide6.QtCore import Qt, QTimer
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from . import win32
from .hud import Painter
from .puppet import Geom, Puppet, read_bbox
from .stage import Stage

log = logging.getLogger(__name__)
FORMS = ("chibi", "serious")


class MonitorWindow(QOpenGLWidget):
    def __init__(self, screen, stage: Stage, rigs: dict[str, str], primary: bool, peers: list):
        super().__init__()
        self.scr, self.stage, self.rig_paths, self.primary, self.peers = screen, stage, rigs, primary, peers
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(screen.geometry())
        self.setWindowOpacity(0.0)  # hidden while the puppets calibrate
        self.dpr = screen.devicePixelRatio()
        self.hwnd = 0
        self.rect_px = (0, 0, 0, 0)  # this window in desktop physical px
        self.puppets: dict[str, Puppet] = {}
        self.calibrating = list(FORMS)
        self.drew_last = True
        self.transparent: bool | None = None
        self.cursor_here = False
        self.poll = QTimer(self)
        self.poll.setTimerType(Qt.TimerType.PreciseTimer)
        self.poll.timeout.connect(self._poll_cursor)
        self.frameSwapped.connect(self._next_frame)

    # --- win32 ------------------------------------------------------------------------
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.hwnd:
            self.hwnd = int(self.winId())
            win32.add_exstyle(self.hwnd, win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW)
            self.stage.ground.own.add(self.hwnd)
            self.rect_px = win32.window_rect(self.hwnd)
            self.poll.start(16)

    def _poll_cursor(self) -> None:
        st = self.stage
        busy = st.press is not None or st.dragging
        on = not ((self.cursor_here and st.cursor_on_her) or busy)
        if on != self.transparent:
            win32.set_click_through(self.hwnd, on)
            self.transparent = on

    # --- frames -----------------------------------------------------------------------------
    def _fb(self) -> tuple[int, int]:
        return int(self.width() * self.dpr), int(self.height() * self.dpr)

    def _near_me(self) -> bool:
        l, t, r, b = self.rect_px
        x, y = self.stage.feet
        reach = 700 * self.dpr
        return l - reach < x < r + reach and t - reach < y < b + reach

    def _next_frame(self) -> None:
        if self.primary or self.calibrating or self._near_me() or self.drew_last:
            self.update()

    def wake(self) -> None:
        if not self.calibrating and self._near_me():
            self.update()

    def initializeGL(self) -> None:
        live2d.glInit()
        log.info("%s: GL_RENDERER=%s", self.scr.name(), gl.glGetString(gl.GL_RENDERER).decode())
        for form in FORMS:
            self.puppets[form] = Puppet(self.rig_paths[form], self.stage.rigs[form], self.dpr, self._fb())

    def resizeGL(self, w: int, h: int) -> None:
        for p in self.puppets.values():
            p.model.Resize(int(w * self.dpr), int(h * self.dpr))

    def paintGL(self) -> None:
        live2d.clearBuffer()
        if self.calibrating:
            self._calibrate()
            return
        st = self.stage
        cx, cy = win32.cursor_pos()
        if self.primary:
            st.tick((cx, cy))
            for w in self.peers:
                if w is not self:
                    w.wake()
        l, t, r, b = self.rect_px
        form = st.draw_form()
        drew = False
        if form and self._near_me():
            pup = self.puppets[form]
            x, y = st.feet
            pup.place(x - l, y - t)
            pup.face(st.facing_left)
            pup.play(st.clip(form))
            for pid, v in st.params(time.monotonic()).items():
                pup.set_param(pid, v)
            g = st.gaze_target()
            gx, gy = (g[0] - l, g[1] - t) if g else (x - l, y - t - pup.height)
            pup.model.Drag(gx, gy)
            pup.model.Update()
            pup.model.Draw()
            drew = True
        self.cursor_here = l <= cx < r and t <= cy < b
        if self.cursor_here:
            st.cursor_on_her = (drew and self._alpha_at(cx - l, cy - t) > 8) \
                or st.hit_overlay(cx, cy) is not None
        if self._near_me() or st.transform_progress() is not None:
            Painter(self, (l, t), self.dpr, st).paint()
            drew = True
        self.drew_last = drew

    def _alpha_at(self, x: int, y: int) -> int:
        w, h = self._fb()
        if not (0 <= x < w and 0 <= y < h):
            return 0
        px = gl.glReadPixels(x, h - 1 - y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        return px[3] if isinstance(px, (bytes, bytearray)) else int(np.asarray(px).ravel()[3])

    def _calibrate(self) -> None:
        """Primary: measure each rig once at scale 1. Every window: derive its placement."""
        st = self.stage
        for form in list(self.calibrating):
            pup = self.puppets[form]
            if form not in st.geom:
                if not self.primary:
                    return  # wait for the primary window's measurement
                pup.model.Update()
                pup.model.Draw()
                bb = read_bbox(*self._fb())
                live2d.clearBuffer()
                if bb is None:
                    return
                st.geom[form] = Geom.measure(bb, self._fb())
                log.info("%s rig measured: %s", form, st.geom[form])
            pup.configure(st.geom[form], self._fb())
            if self.primary:
                st.size[form] = (pup.height, pup.half_width)
            self.calibrating.remove(form)
        if not self.calibrating:
            QTimer.singleShot(50, lambda: self.setWindowOpacity(1.0))

    # --- mouse: forwarded to the stage in desktop px -------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.stage.press_at(*win32.cursor_pos())

    def mouseMoveEvent(self, e) -> None:
        self.stage.move_to(*win32.cursor_pos())

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.stage.release_at(*win32.cursor_pos())
