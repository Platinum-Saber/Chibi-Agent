"""Read-only facts about the PC."""
from __future__ import annotations

import ctypes
import datetime as dt
from ctypes import wintypes

import psutil

from . import Result, tool

user32 = ctypes.windll.user32


def _fg_title() -> tuple[str, str]:
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        exe = psutil.Process(pid.value).name()
    except psutil.Error:
        exe = "?"
    return buf.value, exe


@tool("get_time", "The current date and time (you do not know it without this tool).")
def get_time() -> Result:
    now = dt.datetime.now()
    return Result(now.strftime("%A %d %B %Y, %H:%M"))


@tool("system_info", "Battery, CPU, RAM, GPU memory, disk.",
      {"what": ("battery, cpu, ram, vram, disk or all", False)})
def system_info(what: str = "all") -> Result:
    what = (what or "all").lower()
    out = []
    if what in ("battery", "all"):
        b = psutil.sensors_battery()
        if b:
            out.append(f"Battery {b.percent:.0f}%, {'charging' if b.power_plugged else 'on battery'}"
                       + (f", about {b.secsleft // 60} min left" if b.secsleft > 0 and not b.power_plugged else ""))
    if what in ("cpu", "all"):
        out.append(f"CPU {psutil.cpu_percent(interval=0.3):.0f}%")
    if what in ("ram", "all"):
        m = psutil.virtual_memory()
        out.append(f"RAM {m.used / 2**30:.1f} of {m.total / 2**30:.1f} GB used")
    if what in ("vram", "gpu", "all"):
        try:
            import pynvml
            pynvml.nvmlInit()
            mem = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0))
            out.append(f"GPU memory {mem.used / 2**30:.1f} of {mem.total / 2**30:.1f} GB used")
        except Exception:
            out.append("GPU memory unavailable")
    if what in ("disk", "all"):
        for p in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(p.mountpoint)
                out.append(f"Disk {p.mountpoint} {u.free / 2**30:.0f} GB free of {u.total / 2**30:.0f} GB")
            except OSError:
                pass
    return Result("; ".join(out) or "Nothing to report.")


@tool("focused_window", "The app and window in front.")
def focused_window() -> Result:
    title, exe = _fg_title()
    return Result(f"{exe}: {title}" if title else exe, untrusted=True)


@tool("running_apps", "Apps with open windows.")
def running_apps() -> Result:
    names: set[str] = set()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                names.add(psutil.Process(pid.value).name())
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(cb, 0)
    return Result(", ".join(sorted(names)))
