"""Spike 1: Live2D overlay on the iGPU (throwaway).

Adapted from live2d-py examples/main_pyside6.py.

A frameless, translucent, always-on-top, never-activating QOpenGLWidget covers
one monitor. Haru (~360 DIP tall) stands on that monitor's taskbar top. A
vsync-paced frame loop logs fps / frame-time p50/p95/max per 10 s window to
CSV. Click-through: every frame samples the alpha under the cursor (1-px
glReadPixels); a 60 Hz poll toggles WS_EX_TRANSPARENT only when that flips.
Click her -> TapBody. Drag her -> the model moves inside the window, then
falls back to the taskbar.

Run:  uv run overlay_spike.py [--screen N] [--duration S] [--tag NAME]
Quit: Ctrl+C in the console, or --duration.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
import OpenGL.GL as gl
import psutil
import win32api
import win32con
import win32gui

import PySide6
from PySide6.QtCore import QElapsedTimer, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

import live2d

HERE = Path(__file__).resolve().parent
MODEL_JSON = HERE / "assets" / "Haru" / "Haru.model3.json"
OUT = HERE / "out"

TARGET_H_DIP = 360
WINDOW_S = 10.0
GRAVITY_DIP = 3000.0  # DIP/s^2
DRAG_THRESHOLD = 5  # physical px

WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x80
WS_EX_TOPMOST = 0x8
GWL_EXSTYLE = -20

user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def taskbar_rect() -> tuple[int, int, int, int] | None:
    abd = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA))
    if ctypes.windll.shell32.SHAppBarMessage(5, ctypes.byref(abd)):  # ABM_GETTASKBARPOS
        r = abd.rc
        return r.left, r.top, r.right, r.bottom
    return None


def on_ac() -> int:
    s = SYSTEM_POWER_STATUS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    return s.ACLineStatus


def nvidia_procs() -> str:
    """PIDs nvidia-smi lists (compute and graphics), or '' if none."""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10).stdout
    except Exception as e:  # noqa: BLE001
        return f"err:{e}"
    me = str(os.getpid())
    hit = [ln.strip() for ln in out.splitlines() if me in ln.split()]
    return " | ".join(hit)


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


class Overlay(QOpenGLWidget):
    def __init__(self, screen, args) -> None:
        super().__init__()
        self.args = args
        self.scr = screen
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(screen.geometry())
        self.dpr = screen.devicePixelRatio()
        self.model: live2d.Model | None = None
        self.hwnd = 0
        self.renderer = ""

        # placement / calibration (all physical px, GL window coords y-down)
        self.calib = 0
        self.scale = 1.0
        self.k = (1.0, 1.0)  # px per offset unit (x, y)
        self.base_c = (0.0, 0.0)  # bbox centre-x, bottom at offset 0 for current scale
        self.foot = [0.0, 0.0]  # where her feet are: centre-x, bottom
        self.floor = 0.0
        self.vy = 0.0
        self.bbox_h = 0.0

        # input state
        self.alpha_under = 0
        self.cursor_in = False
        self.transparent = None  # unknown until first poll
        self.toggles = 0
        self.press = None  # (global QPoint, foot copy)
        self.dragging = False
        self.hits = 0

        # timing
        self.last_frame = None
        self.intervals: list[float] = []
        self.paint_ms: list[float] = []
        self.win_start = time.perf_counter()
        self.t0 = self.win_start
        self.proc = psutil.Process()
        self.proc.cpu_percent(None)
        self.ncpu = psutil.cpu_count()
        self.hud = ""
        self.nv_last = ""
        self.last_t = time.perf_counter()

        OUT.mkdir(exist_ok=True)
        tag = args.tag
        self.csv_f = open(OUT / f"frames_{tag}.csv", "w", newline="")
        self.csv = csv.writer(self.csv_f)
        self.csv.writerow(["t_s", "frames", "fps", "p50_ms", "p95_ms", "max_ms", "paint_p95_ms",
                           "cpu_core_pct", "cpu_total_pct", "rss_mb", "toggles", "hits",
                           "transparent", "dragging", "ac", "nvidia_smi_lines"])
        self.ev_f = open(OUT / f"events_{tag}.log", "w")

        self.poll = QTimer(self)
        self.poll.setTimerType(Qt.TimerType.PreciseTimer)
        self.poll.timeout.connect(self.poll_cursor)
        self.frameSwapped.connect(self.update)

    # ---------- logging ----------
    def ev(self, msg: str) -> None:
        line = f"{time.perf_counter() - self.t0:9.3f} {msg}"
        print(line, flush=True)
        self.ev_f.write(line + "\n")
        self.ev_f.flush()

    # ---------- win32 ----------
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.hwnd:
            self.hwnd = int(self.winId())
            ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            self.ev(f"exstyle before 0x{ex:08x} layered={bool(ex & WS_EX_LAYERED)}")
            ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if self.args.force_layered:
                ex |= WS_EX_LAYERED
            user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)
            ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            self.ev(f"exstyle after  0x{ex:08x} layered={bool(ex & WS_EX_LAYERED)} "
                    f"rect={win32gui.GetWindowRect(self.hwnd)}")
            self.poll.start(16)

    def set_transparent(self, on: bool) -> None:
        if on == self.transparent:
            return
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        ex = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)
        if self.transparent is not None:
            self.toggles += 1
        self.transparent = on

    def poll_cursor(self) -> None:
        if self.dragging or self.press is not None:
            self.set_transparent(False)
            return
        was = self.transparent
        self.set_transparent(not self.cursor_in)
        if was is not None and was != self.transparent:
            QTimer.singleShot(50, self.check_wfp)

    def check_wfp(self) -> None:
        """Which top-level window does the system hit-test at the cursor now?"""
        pos = win32api.GetCursorPos()
        top = win32gui.GetAncestor(win32gui.WindowFromPoint(pos), 2)  # GA_ROOT
        mine = top == self.hwnd
        ok = mine != self.transparent
        self.ev(f"wfp transparent={self.transparent} hit_me={mine} "
                f"under='{win32gui.GetWindowText(top)[:40]}' {'OK' if ok else 'FAIL'}")

    # ---------- GL ----------
    def initializeGL(self) -> None:
        live2d.glInit()
        self.renderer = gl.glGetString(gl.GL_RENDERER).decode()
        vendor = gl.glGetString(gl.GL_VENDOR).decode()
        version = gl.glGetString(gl.GL_VERSION).decode()
        fmt = self.format()
        self.ev(f"GL_RENDERER={self.renderer} | GL_VENDOR={vendor} | GL_VERSION={version}")
        self.ev(f"format swapInterval={fmt.swapInterval()} alpha={fmt.alphaBufferSize()} "
                f"PySide6={PySide6.__version__} python={sys.version.split()[0]} dpr={self.dpr} "
                f"screen={self.scr.name()} geom={self.scr.geometry()} avail={self.scr.availableGeometry()} "
                f"abm_taskbar={taskbar_rect()} ac={on_ac()} exe={psutil.Process().exe()}")
        self.model = live2d.Model()
        self.model.LoadModelJson(str(MODEL_JSON))
        self.floor = (self.scr.availableGeometry().bottom() + 1 - self.scr.geometry().top()) * self.dpr

    def resizeGL(self, w: int, h: int) -> None:
        if self.model:
            self.model.Resize(int(w * self.dpr), int(h * self.dpr))

    def fb_size(self) -> tuple[int, int]:
        return int(self.width() * self.dpr), int(self.height() * self.dpr)

    def read_bbox(self):
        w, h = self.fb_size()
        data = gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        a = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)[::-1, :, 3]
        ys, xs = np.nonzero(a > 8)
        if len(xs) == 0:
            return None
        return xs.min(), ys.min(), xs.max(), ys.max()

    def apply_offset(self) -> None:
        ox = (self.foot[0] - self.base_c[0]) / self.k[0]
        oy = (self.foot[1] - self.base_c[1]) / self.k[1]
        self.model.SetOffset(ox, oy)

    def calibrate(self) -> bool:
        """Empirical placement: a few frames of full readback at startup."""
        bb = self.read_bbox()
        if bb is None:
            self.ev(f"calib {self.calib}: empty frame")
            return False
        x0, y0, x1, y1 = bb
        cx, bot, hh = (x0 + x1) / 2, y1, y1 - y0
        self.ev(f"calib {self.calib}: bbox={bb} h={hh}")
        if self.calib == 0:
            self.scale = TARGET_H_DIP * self.dpr / hh
            self.model.SetScale(self.scale)
        elif self.calib == 1:
            self.base_c = (cx, bot)
            self.model.SetOffset(0.1, 0.1)
        elif self.calib == 2:
            self.k = ((cx - self.base_c[0]) / 0.1, (bot - self.base_c[1]) / 0.1)
            w, _ = self.fb_size()
            self.foot = [w * 0.75, self.floor]
            self.apply_offset()
            self.ev(f"calib: scale={self.scale:.3f} k={self.k} floor={self.floor}")
        elif self.calib == 3:
            self.bbox_h = hh
            self.ev(f"placed: bottom={bot} (floor {self.floor}) height={hh}px "
                    f"({hh / self.dpr:.0f} DIP) centre-x={cx}")
        return True

    def paintGL(self) -> None:
        t = time.perf_counter()
        if self.last_frame is not None:
            self.intervals.append((t - self.last_frame) * 1000)
        self.last_frame = t
        dt = t - self.last_t
        self.last_t = t

        live2d.clearBuffer()
        self.physics(dt)
        self.model.Update()
        self.model.Draw()

        if self.calib < 4:
            if self.calibrate():
                self.calib += 1
                if self.calib == 4 and self.args.busy:
                    self.busy = QTimer(self)
                    self.busy.timeout.connect(
                        lambda: self.model.StartRandomMotion("TapBody", live2d.MotionPriority.FORCE))
                    self.busy.start(3000)
        else:
            self.sample_alpha()

        if not self.args.no_hud and self.hud:
            p = QPainter(self)
            p.setPen(QColor(255, 255, 255))
            p.fillRect(self.width() - 330, 8, 320, 22, QColor(0, 0, 0, 160))
            p.setFont(QFont("Consolas", 10))
            p.drawText(self.width() - 325, 24, self.hud)
            p.end()

        self.paint_ms.append((time.perf_counter() - t) * 1000)
        if t - self.win_start >= WINDOW_S:
            self.flush_window(t)

    def sample_alpha(self) -> None:
        cx, cy = win32api.GetCursorPos()
        l, tp, r, b = win32gui.GetWindowRect(self.hwnd)
        x, y = cx - l, cy - tp
        w, h = self.fb_size()
        if 0 <= x < w and 0 <= y < h:
            px = gl.glReadPixels(x, h - 1 - y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            self.alpha_under = px[3] if isinstance(px, (bytes, bytearray)) else int(np.asarray(px).ravel()[3])
        else:
            self.alpha_under = 0
        inside = self.alpha_under > 8
        if inside != self.cursor_in:
            self.cursor_in = inside
            self.ev(f"cursor {'ON' if inside else 'off'} her at ({cx},{cy}) alpha={self.alpha_under}")

    def flush_window(self, t: float) -> None:
        iv = self.intervals
        n = len(self.paint_ms)
        span = t - self.win_start
        fps = n / span if span else 0
        cpu = self.proc.cpu_percent(None)
        nv = self.nv_last
        threading.Thread(target=lambda: setattr(self, "nv_last", nvidia_procs()), daemon=True).start()
        row = [round(t - self.t0, 1), n, round(fps, 2), round(statistics.median(iv), 2) if iv else "",
               round(pct(iv, 95), 2), round(max(iv), 2) if iv else "", round(pct(self.paint_ms, 95), 2),
               round(cpu, 1), round(cpu / self.ncpu, 2), round(self.proc.memory_info().rss / 2**20),
               self.toggles, self.hits, self.transparent, self.dragging, on_ac(), nv]
        self.csv.writerow(row)
        self.csv_f.flush()
        self.hud = (f"{fps:5.1f} fps p50 {row[3]} p95 {row[4]} ms cpu {row[8]}%")
        print("WINDOW", row, flush=True)
        self.intervals, self.paint_ms = [], []
        self.win_start = t

    # ---------- body ----------
    def physics(self, dt: float) -> None:
        if self.calib < 4 or self.dragging:
            return
        dt = min(dt, 0.05)
        if self.foot[1] < self.floor or self.vy != 0:
            self.vy += GRAVITY_DIP * self.dpr * dt
            self.foot[1] += self.vy * dt
            if self.foot[1] >= self.floor:
                self.foot[1] = self.floor
                if self.vy > 600 * self.dpr:
                    self.vy = -self.vy * 0.3  # small bounce
                else:
                    self.vy = 0.0
                    self.ev("landed")
            self.apply_offset()

    # ---------- mouse ----------
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.press = (e.globalPosition().toPoint(), list(self.foot))
        self.ev(f"press at {self.press[0].toTuple()} fg_is_me={win32gui.GetForegroundWindow() == self.hwnd}")

    def mouseMoveEvent(self, e) -> None:
        if self.press is None:
            return
        d = (e.globalPosition().toPoint() - self.press[0]) * self.dpr
        if not self.dragging and (abs(d.x()) > DRAG_THRESHOLD or abs(d.y()) > DRAG_THRESHOLD):
            self.dragging = True
            self.vy = 0.0
            self.ev("drag start")
        if self.dragging:
            w, _ = self.fb_size()
            self.foot[0] = min(max(self.press[1][0] + d.x(), 0), w)
            self.foot[1] = min(self.press[1][1] + d.y(), self.floor)
            self.apply_offset()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self.press is None:
            return
        if self.dragging:
            self.ev(f"drag end foot={[round(v) for v in self.foot]} -> falling")
        else:
            self.hits += 1
            self.model.StartRandomMotion("TapBody", live2d.MotionPriority.FORCE)
            self.ev(f"HIT #{self.hits}: TapBody fg_is_me={win32gui.GetForegroundWindow() == self.hwnd}")
        self.dragging = False
        self.press = None

    def close_logs(self) -> None:
        self.csv_f.close()
        self.ev_f.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", type=int, default=-1, help="QScreen index (default: primary)")
    ap.add_argument("--duration", type=float, default=0, help="quit after S seconds")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--no-hud", action="store_true")
    ap.add_argument("--force-layered", action="store_true")
    ap.add_argument("--busy", action="store_true", help="loop TapBody every 3 s")
    args = ap.parse_args()

    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(1)
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    live2d.init()
    app = QApplication(sys.argv)
    screens = QGuiApplication.screens()
    for i, s in enumerate(screens):
        print(f"screen {i}: {s.name()} {s.geometry()} dpr={s.devicePixelRatio()} hz={s.refreshRate()}")
    scr = QGuiApplication.primaryScreen() if args.screen < 0 else screens[args.screen]
    win = Overlay(scr, args)
    win.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)  # let Python see Ctrl+C
    tick.timeout.connect(lambda: None)
    if args.duration:
        QTimer.singleShot(int(args.duration * 1000), app.quit)
    app.exec()
    win.close_logs()
    live2d.dispose()


if __name__ == "__main__":
    main()
