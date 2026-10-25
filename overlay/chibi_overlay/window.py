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
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from . import win32
from .hud import Painter
from .puppet import Geom, Puppet, read_bbox
from .stage import Stage
from .wheel import paint_wheel

log = logging.getLogger(__name__)
FORMS = ("chibi", "serious")


class MonitorWindow(QOpenGLWidget):
    def __init__(self, screen, stage: Stage, primary: bool, peers: list):
        super().__init__()
        self.scr, self.stage, self.primary, self.peers = screen, stage, primary, peers
        self.outfit_gen = stage.outfit_gen  # the outfit our puppets wear
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
        self.character_gen = -1  # the stage's customization these puppets were tuned with
        self.drew_last = True
        self.min_frame_s = 0.0  # 1/30 on battery (main.py), else every vsync
        self._t_frame = 0.0
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
        self._models_visible(True)

    def hideEvent(self, e) -> None:
        self._models_visible(False)  # hidden (tray, fullscreen app, gaming): the 3D body too
        super().hideEvent(e)

    def _models_visible(self, on: bool) -> None:
        for p in self.puppets.values():
            if hasattr(p.model, "set_visible"):
                p.model.set_visible(on)

    def _poll_cursor(self) -> None:
        st = self.stage
        busy = st.press is not None or st.dragging or st.rotating
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
            now = time.monotonic()
            wait = self.min_frame_s - (now - self._t_frame)
            if wait > 0.002:
                QTimer.singleShot(int(wait * 1000), self.update)  # battery: skip a vsync
            else:
                self.update()
            self._t_frame = now + max(wait, 0.0)

    def wake(self) -> None:
        if not self.calibrating and self._near_me():
            self.update()

    def initializeGL(self) -> None:
        live2d.glInit()
        log.info("%s: GL_RENDERER=%s", self.scr.name(), gl.glGetString(gl.GL_RENDERER).decode())
        self._load_puppets()

    def _load_puppets(self) -> None:
        """Load the current outfit's models (GL context current) and queue their calibration."""
        st = self.stage
        for p in self.puppets.values():
            if hasattr(p.model, "close"):  # the 3D body's renderer process
                p.model.close()
        self.puppets = {}  # drops the old outfit's models
        for form in FORMS:
            self.puppets[form] = Puppet(st.rig_paths[form], st.rigs[form], self.dpr, self._fb(), self)
        self.outfit_gen = st.outfit_gen
        self.character_gen = -1  # tune the new puppets on the next frame
        self.calibrating = list(FORMS)

    def _tune(self) -> None:
        """Hand Kryo's customization to puppets that take it (sprite packs)."""
        for p in self.puppets.values():
            if hasattr(p.model, "tune"):
                p.model.tune(self.stage.character, self.stage.outfit)
        self.character_gen = self.stage.character_gen

    def resizeGL(self, w: int, h: int) -> None:
        # also runs after _follow() moved us to another monitor (its DPI may differ)
        self.dpr = self.devicePixelRatioF()
        for form, p in self.puppets.items():
            p.dpr = self.dpr
            if form in self.stage.geom:
                p.configure(self.stage.geom[form], self._fb())
            else:
                p.model.Resize(*self._fb())
        if self.hwnd:
            self.rect_px = win32.window_rect(self.hwnd)
        log.debug("resized: %dx%d logical, dpr %.2f, fb %s, rect %s, feet %s",
                 w, h, self.dpr, self._fb(), self.rect_px, self.stage.feet)

    def _follow(self) -> None:
        """One GL window follows her across monitors (a second window's context drew
        the rigs untextured). It hops when her feet cross into another monitor."""
        x, y = self.stage.feet
        mon = self.stage.ground.monitor_at(x, y - 1)
        if tuple(mon) != tuple(self.rect_px):
            cx, cy = (mon.left + mon.right) // 2, (mon.top + mon.bottom) // 2
            scr = QGuiApplication.screenAt(QPoint(cx, cy)) or next(
                (s for s in QGuiApplication.screens() if s.geometry().contains(QPoint(cx, cy))), None)
            if scr is None:
                return
            log.info("following her to %s %s", scr.name(), tuple(mon))
            self.scr = scr
            self.rect_px = tuple(mon)  # until resizeGL reads the real rect
            self.setGeometry(scr.geometry())

    def paintGL(self) -> None:
        live2d.clearBuffer()
        if self.outfit_gen != self.stage.outfit_gen:  # new outfit, mid-puff: reload and re-measure
            self._load_puppets()
        if self.character_gen != self.stage.character_gen:
            self._tune()
        if self.calibrating:
            self._calibrate()
            return
        st = self.stage
        cx, cy = win32.cursor_pos()
        if self.primary:
            st.tick((cx, cy), win32.buttons_down())
            self._follow()
            for w in self.peers:
                if w is not self:
                    w.wake()
        l, t, r, b = self.rect_px
        form = st.draw_form()
        drew = False
        hit = None  # the 3D body answers hit tests itself (Godot draws her, not this window)
        if form and self._near_me():
            pup = self.puppets[form]
            x, y = st.feet
            pup.place(x - l, y - t)
            pup.face(st.facing_left)
            pup.play(st.clip(form))
            for pid, v in st.params(time.monotonic()).items():
                pup.set_param(pid, v)
            g = st.gaze_target()
            # no target: look ahead, at a point level with her eyes (above her head rolled them up)
            gx, gy = (g[0] - l, g[1] - t) if g else (x - l, y - t - pup.height * 0.6)
            pup.model.Drag(gx, gy)
            pup.model.Update()
            pup.model.Draw()
            drew = True
            hit = getattr(pup.model, "hit", None)
        self.cursor_here = l <= cx < r and t <= cy < b
        if self.cursor_here:
            on_her = hit(cx - l, cy - t) if hit else drew and self._alpha_at(cx - l, cy - t) > 8
            st.cursor_on_her = on_her or st.hit_overlay(cx, cy) is not None
        if self._near_me() or st.transform_progress() is not None:
            Painter(self, (l, t), self.dpr, st).paint()
            drew = True
        if st.wheel.open:
            paint_wheel(self, (l, t), self.dpr, st.wheel)
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
            if getattr(pup.model, "failed", ""):  # the 3D renderer didn't start: back to 2D
                st.body_failed(pup.model.failed)
                return
            if form not in st.geom and hasattr(pup.model, "geom"):  # the 3D body reports its size
                g = pup.model.geom()
                if g is None:
                    return  # the renderer is still starting
                st.geom[form] = g
                log.info("%s 3D body measured: %s", form, g)
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
        if not self.calibrating and self.windowOpacity() < 1.0:  # first calibration only
            QTimer.singleShot(50, lambda: self.setWindowOpacity(1.0))

    # --- mouse: forwarded to the stage in desktop px -------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.stage.press_at(*win32.cursor_pos())
        elif e.button() == Qt.MouseButton.MiddleButton and self.stage.hit_overlay(*win32.cursor_pos()) is None:
            self.stage.rotate_press(win32.cursor_pos()[0])  # middle-drag on her: turn her
        elif e.button() == Qt.MouseButton.RightButton and self.stage.hit_overlay(*win32.cursor_pos()) in (None, "wheel"):
            self.stage.toggle_wheel()  # right-click on her: the pose wheel (again, or on it: close)

    def mouseMoveEvent(self, e) -> None:
        x, y = win32.cursor_pos()
        self.stage.move_to(x, y)
        self.stage.rotate_move(x)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.stage.release_at(*win32.cursor_pos())
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.stage.rotate_release()
