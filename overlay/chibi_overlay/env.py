"""What she stands on and listens to: monitors, the focused window's title bar, media.

All rects are virtual-desktop physical px (the process is per-monitor DPI aware
through Qt), right/bottom exclusive.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import threading
from ctypes import wintypes

from .body.physics import Rect

log = logging.getLogger(__name__)
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _r(rc: wintypes.RECT) -> Rect:
    return Rect(rc.left, rc.top, rc.right, rc.bottom)


def monitors() -> list[tuple[Rect, Rect, bool]]:
    """[(monitor rect, work area, is_primary)]."""
    out = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        out.append((_r(mi.rcMonitor), _r(mi.rcWork), bool(mi.dwFlags & 1)))
        return 1

    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return out


_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow"}


def foreground_rect(own: set[int]) -> Rect | None:
    """The focused top-level window's visible frame, if she could stand on it.

    None for the desktop/taskbar, our own windows, minimised or maximised windows
    (a maximised title bar sits under the screen top) and tiny popups.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd in own or user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        return None
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    if buf.value in _SKIP_CLASSES:
        return None
    rc = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rc), ctypes.sizeof(rc)):  # EXTENDED_FRAME_BOUNDS
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
    r = _r(rc)
    if r.right - r.left < 200 or r.bottom - r.top < 120:
        return None
    return r


class Ground:
    """floor_y(x) for the physics: the work-area bottom (taskbar top) of the
    monitor under x, or the focused window's top edge when she's above it."""

    def __init__(self, own: set[int]):
        self.own = own
        self.mons = monitors()
        self.window: Rect | None = None
        self.feet_y = 0.0  # set by the stage each frame (where her feet are now)

    def refresh(self) -> None:
        self.window = foreground_rect(self.own)

    def monitor_at(self, x: float, y: float) -> Rect:
        """The monitor whose rect holds (x, y), else the nearest one."""
        for mon, _, _ in self.mons:
            if mon.left <= x < mon.right and mon.top <= y <= mon.bottom:
                return mon
        return min((m for m, _, _ in self.mons),
                   key=lambda m: max(m.left - x, 0, x - m.right) + max(m.top - y, 0, y - m.bottom))

    def work_area_at(self, x: float) -> Rect:
        for mon, work, _ in self.mons:
            if mon.left <= x < mon.right:
                return work
        return min((w for _, w, _ in self.mons), key=lambda w: min(abs(x - w.left), abs(x - w.right)))

    def __call__(self, x: float) -> float:
        floor = self.work_area_at(x).bottom
        w = self.window
        if w and w.left + 8 <= x <= w.right - 8 and self.feet_y <= w.top + 2 and w.top < floor:
            return w.top
        return floor

    def home(self) -> tuple[float, float]:
        """Her spot: the right part of the primary monitor's floor."""
        work = next((w for _, w, p in self.mons if p), self.mons[0][1])
        return work.right - (work.right - work.left) * 0.12, work.bottom


class MediaWatcher:
    """Polls Windows media sessions (GSMTC) every 2 s on its own thread."""

    def __init__(self):
        self.playing = False
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="media", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)
        except ImportError:
            log.info("winrt media control not installed; no dancing")
            return

        async def poll():
            mgr = await Manager.request_async()
            while not self._stop.is_set():
                try:
                    self.playing = any(s.get_playback_info().playback_status == Status.PLAYING
                                       for s in mgr.get_sessions())
                except OSError:
                    self.playing = False
                await asyncio.sleep(2)

        asyncio.run(poll())


kernel32 = ctypes.windll.kernel32


def _exe_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(h)


def fullscreen_app(own: set[int]) -> str | None:
    """The exe of a fullscreen app in front (a game, a video, a presentation), else None.

    Fullscreen = the focused top-level window covers its whole monitor, taskbar
    included. The desktop and shell windows also cover the monitor, so they don't count.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd in own:
        return None
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    if buf.value in _SKIP_CLASSES:
        return None
    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    if rc.left <= m.left and rc.top <= m.top and rc.right >= m.right and rc.bottom >= m.bottom:
        return _exe_name(hwnd) or "?"
    return None
