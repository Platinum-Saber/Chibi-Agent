"""Open applications (Start menu entries) and manage their windows."""
from __future__ import annotations

import ctypes
import difflib
import json
import subprocess
import time
from ctypes import wintypes

from . import Result, tool

user32 = ctypes.windll.user32
NO_WINDOW = subprocess.CREATE_NO_WINDOW
_apps: tuple[float, dict[str, str]] = (0.0, {})


def start_apps() -> dict[str, str]:
    """Start-menu name -> AppID (Win32 and Store apps), cached for 10 minutes."""
    global _apps
    if time.monotonic() - _apps[0] < 600 and _apps[1]:
        return _apps[1]
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
                         capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
    rows = json.loads(out or "[]")
    rows = rows if isinstance(rows, list) else [rows]
    _apps = (time.monotonic(), {r["Name"]: r["AppID"] for r in rows if r.get("Name")})
    return _apps[1]


def best_app(name: str) -> str | None:
    apps = start_apps()
    lower = {k.lower(): k for k in apps}
    q = name.lower().strip()
    if q in lower:
        return lower[q]
    starts = [k for lk, k in lower.items() if lk.startswith(q) or q in lk.split()]
    if starts:
        return min(starts, key=len)
    contains = [k for lk, k in lower.items() if q in lk]
    if contains:
        return min(contains, key=len)
    # "vs code" -> Visual Studio Code: the query's letters as initials of the name's words
    initials = q.replace(" ", "")
    acro = [k for lk, k in lower.items() if len(initials) >= 2
            and "".join(w[0] for w in lk.split() if w).startswith(initials[:2])
            and all(part in lk or len(part) <= 2 for part in q.split())]
    if acro:
        return min(acro, key=len)
    close = difflib.get_close_matches(q, list(lower), n=1, cutoff=0.6)
    return lower[close[0]] if close else None


@tool("open_app", "Open an application by name.", {"name": ("App name, e.g. 'Spotify'", True)},
      side_effect=True, summary=lambda a: f"Open {a.get('name')}")
def open_app(name: str) -> Result:
    match = best_app(name)
    if not match:
        return Result(f"No installed application matches '{name}'.")
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{start_apps()[match]}"], creationflags=NO_WINDOW)
    return Result(f"Opened {match}.")


def _find_window(title: str) -> int | None:
    q = title.lower()
    hits: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if q in buf.value.lower():
                hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return hits[0][0] if hits else None


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


@tool("focus_window", "Bring an open window to the front.", {"title": ("Part of the window title", True)},
      side_effect=True, summary=lambda a: f"Focus {a.get('title')}")
def focus_window(title: str) -> Result:
    hwnd = _find_window(title)
    if not hwnd:
        return Result(f"No open window matches '{title}'.")
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)  # a tap of Alt lets SetForegroundWindow through
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return Result(f"Focused '{_title(hwnd)}'.")


@tool("arrange_window", "Minimise, maximise, restore or snap a window left/right.",
      {"title": ("Part of the window title", True),
       "action": ("minimise, maximise, restore, left or right", True)},
      side_effect=True, summary=lambda a: f"{a.get('action')} {a.get('title')}")
def arrange_window(title: str, action: str) -> Result:
    hwnd = _find_window(title)
    if not hwnd:
        return Result(f"No open window matches '{title}'.")
    a = action.lower()
    if a.startswith("min"):
        user32.ShowWindow(hwnd, 6)
    elif a.startswith("max"):
        user32.ShowWindow(hwnd, 3)
    elif a.startswith("rest"):
        user32.ShowWindow(hwnd, 9)
    elif a in ("left", "right"):
        mon = user32.MonitorFromWindow(hwnd, 2)

        class MI(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        mi = MI(cbSize=ctypes.sizeof(MI))
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
        w = mi.rcWork
        half = (w.right - w.left) // 2
        user32.ShowWindow(hwnd, 9)
        x = w.left if a == "left" else w.left + half
        user32.MoveWindow(hwnd, x, w.top, half, w.bottom - w.top, True)
    else:
        return Result(f"Unknown action '{action}'.")
    return Result(f"{action} '{_title(hwnd)}'.")


@tool("close_window", "Close a window.",
      {"title": ("Part of the window title", True)},
      side_effect=True, summary=lambda a: f"Close the window '{a.get('title')}'")
def close_window(title: str) -> Result:
    hwnd = _find_window(title)
    if not hwnd:
        return Result(f"No open window matches '{title}'.")
    t = _title(hwnd)
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: the app handles unsaved work itself
    return Result(f"Asked '{t}' to close.")
