"""Her 3D body (overlay3d/, Godot 4.7) as a puppet model the stage drives like a Live2D rig.

`godot:<overlay3d dir>` in a rig path picks it; `godot:<dir>#<file>.vrm` picks another model in
its models/ folder (a variant, e.g. her ruby-red eyes). `GodotModel` takes the calls `Puppet` makes on
live2d models (SetScale/SetOffset/StartMotion/SetExpression/SetSaveParamById/Drag/Update...)
and, on Update, sends one frame to a Godot renderer process: her feet and height in window
px, the clip and expression names (overlay/rigs/raphael_3d.toml -> overlay3d/clips.gd),
the Live2D-style params and the gaze point. Brain, physics, input and her panels stay here.

The renderer's window is ours to manage: it covers the same monitor as the overlay window,
sits just under it, never takes focus or clicks (WS_EX_LAYERED | WS_EX_TRANSPARENT) and has
no taskbar button. Clicks still land on the overlay window, which asks `hit()`: Godot sends
a hull around her each frame. One renderer per project serves every puppet using it (both
forms point at the same body); it quits when the last one is closed or the link drops.
Link: local TCP, one JSON object per line, a random token in the first line from Godot.
"""
from __future__ import annotations

import ctypes
import json
import logging
import secrets
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer

from chibi_shared import config, paths

from . import win32

log = logging.getLogger(__name__)

PREFIX = "godot:"
MODEL = "raphael_teen.vrm"  # in the project's models/; exported by overlay3d/tools/export_vrm.py
DEFAULT_EXE = r"X:\Godot\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64.exe"
START_TIMEOUT_MS = 30_000  # first import of the VRM can take a while
QUIT_GRACE_MS = 500
RENDER_SCALE = 2.0  # [overlay] render_scale: supersampling for a clearer face (overlay3d/README.md: budgets)
MSAA = 2            # [overlay] msaa: 0, 2, 4 or 8
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
LWA_ALPHA = 0x2
WS_EX_APPWINDOW = 0x40000

user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


_job = None


def _tie_to_us(pid: int) -> None:
    """Put the renderer in a kill-on-close job of ours: it dies with this process however that
    ends (a crash or a kill skips the "quit" line, and Godot is slow to quit by itself)."""
    global _job
    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    if _job is None:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(LimitFlags=0x2000)  # KILL_ON_JOB_CLOSE
        job = k32.CreateJobObjectW(None, None)
        if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            log.warning("3D renderer: no job object; it may outlive a crashed overlay")
            return
        _job = job
    proc = k32.OpenProcess(0x0001 | 0x0100, False, pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    if not proc or not k32.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(proc)):
        log.warning("3D renderer: can't tie it to the overlay's lifetime")
    if proc:
        k32.CloseHandle(wintypes.HANDLE(proc))


def split(spec: str) -> tuple[str, str]:
    """`<project dir>[#<model file>]` -> (project dir, model file in its models/)."""
    project, _, model = spec.partition("#")
    return project, model or MODEL


def missing(spec: str) -> list[str]:
    """What the 3D body needs on disk that isn't there."""
    project, model = split(spec)
    p = Path(project)
    return [str(f) for f in (p / "project.godot", p / "models" / model) if not f.exists()]


def in_hull(pts: list[tuple[float, float]], x: float, y: float) -> bool:
    """Point in a convex polygon (any winding)."""
    if len(pts) < 3:
        return False
    sign = 0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        c = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        if c:
            if sign and (c > 0) != (sign > 0):
                return False
            sign = c
    return True


class Bridge:
    """One Godot renderer process and its link, shared by the puppets of one project."""
    _open: dict[str, Bridge] = {}

    @classmethod
    def get(cls, spec: str) -> Bridge:
        """The renderer for a project and model (one per model: switching variants restarts it)."""
        b = cls._open.get(spec)
        if b is None or b.failed:
            b = cls._open[spec] = cls(spec)
        b.users += 1
        return b

    def __init__(self, spec: str, exe: str | None = None):
        self.spec, self.users = spec, 0
        project, model = split(spec)
        self.token = secrets.token_urlsafe(16)
        self.hwnd = 0
        self.height_m = self.half_width_m = 0.0
        self.hull: list[tuple[float, float]] = []
        self.own: list[set[int]] = []  # Ground.own sets: her window counts as the overlay's own
        self.failed = ""  # why the renderer isn't available
        self.sock = None
        self._rx = b""
        self.server = QTcpServer()
        self.server.newConnection.connect(self._accept)
        if not self.server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            self._fail(f"can't listen: {self.server.errorString()}")
            return
        ocfg = config.load()["overlay"]
        exe = exe or ocfg.get("godot_exe") or DEFAULT_EXE
        self._focus = user32.GetForegroundWindow()  # Godot activates its window: handed back on hello
        cmd = [exe, "--path", project, "--", f"--model=res://models/{model}",
               f"--render-scale={float(ocfg.get('render_scale', RENDER_SCALE))}",
               f"--msaa={int(ocfg.get('msaa', MSAA))}",
               f"--renderer={self.server.serverPort()}", f"--token={self.token}"]
        try:
            paths.LOGS.mkdir(parents=True, exist_ok=True)
            with open(paths.LOGS / "godot3d.log", "w", encoding="utf-8") as out:  # the renderer's own log
                self.proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            self.proc = None
            self._fail(f"can't start {exe}: {e}")
            return
        _tie_to_us(self.proc.pid)
        log.info("3D renderer starting: pid %d, port %d", self.proc.pid, self.server.serverPort())
        QTimer.singleShot(START_TIMEOUT_MS, self._check_started)

    @property
    def ready(self) -> bool:
        return bool(self.hwnd) and not self.failed

    def _fail(self, why: str) -> None:
        if not self.failed:
            self.failed = why
            log.error("3D renderer: %s", why)

    def _check_started(self) -> None:
        if not self.hwnd:
            self._fail("no hello from Godot in time")
            self.close()

    def _accept(self) -> None:
        sock = self.server.nextPendingConnection()
        if self.sock is not None:  # one renderer per bridge
            sock.close()
            return
        self.sock = sock
        # one small line per frame: without this Windows batches them (Nagle) and she stutters
        sock.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(lambda: self._fail("renderer link closed") if self.users else None)

    def _read(self) -> None:
        self._rx += bytes(self.sock.readAll().data())
        *lines, self._rx = self._rx.split(b"\n")
        for line in lines:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not self.hwnd:
                if msg.get("t") != "hello" or not secrets.compare_digest(str(msg.get("token", "")), self.token):
                    self._fail("bad hello from the renderer")
                    self.sock.close()
                    return
                self.hwnd = int(msg["hwnd"])
                self.height_m, self.half_width_m = float(msg["height_m"]), float(msg["half_width_m"])
                for s in self.own:  # at once: the fullscreen watcher must never take it for a game
                    s.add(self.hwnd)
                self._own_window()
                log.info("3D renderer ready: hwnd %#x, %.3f m tall", self.hwnd, self.height_m)
            elif msg.get("t") == "hull":
                p = msg.get("pts", [])
                self.hull = list(zip(p[0::2], p[1::2]))

    def _own_window(self) -> None:
        """Click-through for good, no focus, no taskbar button (Godot sets WS_EX_APPWINDOW)."""
        win32.add_exstyle(self.hwnd, win32.WS_EX_LAYERED | win32.WS_EX_TRANSPARENT
                          | win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW)
        ex = win32.user32.GetWindowLongPtrW(self.hwnd, win32.GWL_EXSTYLE)
        win32.user32.SetWindowLongPtrW(self.hwnd, win32.GWL_EXSTYLE, ex & ~WS_EX_APPWINDOW)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindow(self.hwnd, SW_HIDE)  # re-show so the taskbar drops its button
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        if self._focus and user32.GetForegroundWindow() == self.hwnd:
            user32.SetForegroundWindow(self._focus)  # Kryo's typing goes back where it was

    def place(self, above: int, rect: tuple[int, int, int, int]) -> None:
        """Cover `rect` (desktop px), just under the overlay window `above`. One px short of the
        bottom: a window covering the whole monitor counts as a fullscreen app (to any overlay's
        fullscreen watcher, and to Windows' own game detection) whenever it's in front."""
        if self.ready:
            l, t, r, b = rect
            user32.SetWindowPos(self.hwnd, above, l, t, r - l, b - t - 1, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def show(self, on: bool) -> None:
        if self.ready:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if on else SW_HIDE)

    def send(self, msg: dict) -> None:
        if self.sock is not None and self.ready:
            self.sock.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())

    def release(self) -> None:
        self.users -= 1
        if self.users <= 0:
            self.close()

    def close(self) -> None:
        if Bridge._open.get(self.spec) is self:
            del Bridge._open[self.spec]
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_HIDE)  # gone now, not when Godot gets round to quitting
        if self.sock is not None:
            self.send({"t": "quit"})
            self.sock.flush()
            self.sock.close()
        self.server.close()
        proc = getattr(self, "proc", None)
        if proc is not None and proc.poll() is None:
            # Godot takes seconds to quit and a new renderer starts slowly beside it; it has
            # nothing to save, so it gets half a second
            QTimer.singleShot(QUIT_GRACE_MS, lambda: proc.poll() is None and proc.kill())
        log.info("3D renderer closed")


class GodotModel:
    """The live2d-model calls `Puppet` makes, turned into frames for the renderer."""

    def __init__(self, spec: str, widget=None, bridge: Bridge | None = None):
        self.widget = widget  # the overlay MonitorWindow: its hwnd and rect place the renderer
        self.bridge = bridge or Bridge.get(spec)
        ground = getattr(getattr(widget, "stage", None), "ground", None)
        if ground is not None and ground.own not in self.bridge.own:
            # ours, like the overlay window: not a fullscreen app to hide from, not a window to stand on
            self.bridge.own.append(ground.own)
            if self.bridge.hwnd:
                ground.own.add(self.bridge.hwnd)
        self.fb = (1, 1)
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.facing_left = False
        self.motion = "Idle"
        self.expression = ""
        self.params: dict[str, float] = {}
        self.gaze: tuple[float, float] | None = None
        self._last_feet: tuple[float, float, float] | None = None  # x, y, time: her velocity for Godot
        self._placed: tuple | None = None
        self._frames = 0
        self._closed = False

    @property
    def failed(self) -> str:
        return self.bridge.failed

    # --- what Puppet calls --------------------------------------------------------------------
    def Resize(self, w: int, h: int) -> None:
        self.fb = (w, h)

    def SetScale(self, s: float) -> None:
        self.scale = s

    def SetOffset(self, x: float, y: float) -> None:
        self.offset = (x, y)

    def SetScaleX(self, sx: float) -> None:
        self.facing_left = sx < 0

    def StartMotion(self, group: str, _index: int = 0, _priority=None) -> None:
        self.motion = group or "Idle"

    def StartRandomMotion(self, group: str, _priority=None) -> None:
        self.motion = group or "Idle"

    def IsMotionFinished(self) -> bool:
        return False  # clips.gd loops or holds by itself

    def SetExpression(self, name: str) -> None:
        self.expression = name

    def ResetExpression(self) -> None:
        self.expression = ""

    def SetSaveParamById(self, pid: str, value: float, _weight: float = 1.0) -> None:
        self.params[pid] = value

    def Drag(self, x: float, y: float) -> None:
        self.gaze = (x, y)

    def Update(self) -> None:
        self._sync_window()
        self.bridge.send(self.frame())
        self._frames += 1
        # Stage.params is the whole set each frame (eyes shut only while asleep, the head
        # tilt only while thinking...): a param it stops sending must not stick
        self.params = {}

    def Draw(self) -> None:
        pass  # Godot draws her in its own window

    # --- what the overlay window asks ---------------------------------------------------------
    def geom(self):
        """Her size for Puppet.configure (view units at scale 1: height 1), once Godot said it."""
        from .puppet import Geom
        b = self.bridge
        if not b.ready or b.height_m <= 0:
            return None
        return Geom(1.0, b.half_width_m / b.height_m, 0.0, 0.0)

    def hit(self, x: float, y: float) -> bool:
        """Window px inside the hull around her (from the renderer's last frame)."""
        return in_hull(self.bridge.hull, x, y)

    def set_visible(self, on: bool) -> None:
        self.bridge.show(on)
        if not on:
            self._placed = None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.bridge.release()

    # --- frames -------------------------------------------------------------------------------
    def frame(self) -> dict:
        """Puppet maps her feet to an offset in view units (1 = half the framebuffer height,
        y up from the centre) and her size to a scale (height = scale units): undo both."""
        w, h = self.fb
        u = h / 2
        feet = (w / 2 + self.offset[0] * u, h / 2 - self.offset[1] * u)
        # Godot draws on its own vsync, not in step with these frames: with her velocity it carries
        # her on between them instead of standing still one frame and jumping two the next
        now = time.monotonic()
        vel = (0.0, 0.0)
        if self._last_feet is not None and 0.0 < now - self._last_feet[2] < 0.1:
            dt = now - self._last_feet[2]
            vel = ((feet[0] - self._last_feet[0]) / dt, (feet[1] - self._last_feet[1]) / dt)
        self._last_feet = (feet[0], feet[1], now)
        return {"t": "frame", "feet": [round(feet[0], 1), round(feet[1], 1)],
                "vel": [round(vel[0], 1), round(vel[1], 1)], "h": round(self.scale * u, 1),
                "motion": self.motion, "expression": self.expression,
                "walking": self.motion == "Walk", "facing_left": self.facing_left,
                "params": {k: round(v, 3) for k, v in self.params.items()},
                "gaze": [round(self.gaze[0], 1), round(self.gaze[1], 1)] if self.gaze else None,
                "headset": str(getattr(getattr(self.widget, "stage", None), "headset", "")),  # "talk"/"music"/""
                "yaw": round(float(getattr(getattr(self.widget, "stage", None), "yaw", 0.0)), 1),  # middle-drag turn
                "visible": True}

    def _sync_window(self) -> None:
        """Keep the renderer on her monitor, under the overlay window (re-asserted each second:
        other topmost windows can come between)."""
        wd = self.widget
        if wd is None or not getattr(wd, "hwnd", 0):
            return
        key = (wd.hwnd, tuple(wd.rect_px))
        if key != self._placed or self._frames % 60 == 0:
            self.bridge.place(wd.hwnd, wd.rect_px)
            self._placed = key if self.bridge.ready else None
