"""Which apps are making sound right now: Windows' per-app audio meters (Core Audio, plain ctypes COM).

Some players never appear in Windows' media sessions (GSMTC): classic VLC 3, MPC-HC/BE, mpv,
PotPlayer... For those, MediaWatcher asks here which processes are producing sound on the
default output, and reads the track from the player's window title. Windows only.
"""
from __future__ import annotations

import ctypes
import logging
import re
from ctypes import POINTER, byref, c_float, c_int, c_void_p, wintypes

log = logging.getLogger(__name__)

# Desktop players that don't publish to Windows' media sessions; exe -> its window-title suffix.
PLAYERS = {
    "vlc.exe": " - VLC media player",
    "mpc-hc64.exe": " - MPC-HC", "mpc-hc.exe": " - MPC-HC",
    "mpc-be64.exe": " - MPC-BE", "mpc-be.exe": " - MPC-BE",
    "mpv.exe": " - mpv",
    "potplayermini64.exe": " - PotPlayer", "potplayermini.exe": " - PotPlayer",
    "smplayer.exe": " - SMPlayer", "kmplayer.exe": " - KMPlayer", "wmplayer.exe": " - Windows Media Player",
}
_MEDIA_EXT = re.compile(r"\.(?:f\d+\.)?(?:mp4|mkv|webm|avi|mov|wmv|flv|m4v|mp3|m4a|flac|wav|ogg|opus|aac|wma)$|\.f\d+$",
                        re.IGNORECASE)


def track_title(window_title: str, exe: str) -> str:
    """A player's window title -> the track: no player suffix, no file extension (or yt-dlp's .f397)."""
    t = window_title.strip()
    suffix = PLAYERS.get(exe.lower(), "")
    if suffix and t.lower().endswith(suffix.lower()):
        t = t[: -len(suffix)]
    t = _MEDIA_EXT.sub("", t.strip())
    return t.strip(" -")


# --- Core Audio through ctypes ---------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p("{" + s + "}"), byref(self))


CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioSessionManager2 = "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"
IID_IAudioSessionControl2 = "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"
IID_IAudioMeterInformation = "C02216F6-8C67-4B5B-9D00-D008E73E0064"
CLSCTX_ALL = 23


def _release(obj: c_void_p) -> None:
    if obj:
        ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents[2])(obj)


def _qi(obj: c_void_p, iid: str) -> c_void_p:
    out = c_void_p()
    hr = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))(
        ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents[0])(obj, byref(GUID(iid)), byref(out))
    return out if hr == 0 else c_void_p()


def sounding_pids(threshold: float = 0.005) -> dict[int, float]:
    """Process id -> current output peak (0..1) for every app making sound on the default speakers."""
    ole32 = ctypes.oledll.ole32
    try:
        ole32.CoInitializeEx(None, 0)  # MTA; already initialised is fine
    except OSError:
        pass
    enum, dev, mgr, sessions = c_void_p(), c_void_p(), c_void_p(), c_void_p()
    peaks: dict[int, float] = {}
    try:
        ole32.CoCreateInstance(byref(GUID(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                               byref(GUID(IID_IMMDeviceEnumerator)), byref(enum))
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia, &dev)
        ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_int, c_int, POINTER(c_void_p))(
            ctypes.cast(enum, POINTER(POINTER(c_void_p))).contents[4])(enum, 0, 1, byref(dev))
        # IMMDevice::Activate(IID_IAudioSessionManager2, CLSCTX_ALL, NULL, &mgr)
        ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(
            ctypes.cast(dev, POINTER(POINTER(c_void_p))).contents[3])(
            dev, byref(GUID(IID_IAudioSessionManager2)), CLSCTX_ALL, None, byref(mgr))
        # IAudioSessionManager2::GetSessionEnumerator
        ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(c_void_p))(
            ctypes.cast(mgr, POINTER(POINTER(c_void_p))).contents[5])(mgr, byref(sessions))
        count = c_int()
        ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(c_int))(
            ctypes.cast(sessions, POINTER(POINTER(c_void_p))).contents[3])(sessions, byref(count))
        for i in range(count.value):
            ctl = c_void_p()
            ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_int, POINTER(c_void_p))(
                ctypes.cast(sessions, POINTER(POINTER(c_void_p))).contents[4])(sessions, i, byref(ctl))
            ctl2, meter = _qi(ctl, IID_IAudioSessionControl2), _qi(ctl, IID_IAudioMeterInformation)
            try:
                if ctl2 and meter:
                    pid, peak = wintypes.DWORD(), c_float()
                    ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(wintypes.DWORD))(
                        ctypes.cast(ctl2, POINTER(POINTER(c_void_p))).contents[14])(ctl2, byref(pid))
                    ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(c_float))(
                        ctypes.cast(meter, POINTER(POINTER(c_void_p))).contents[3])(meter, byref(peak))
                    if pid.value and peak.value > threshold:
                        peaks[pid.value] = max(peaks.get(pid.value, 0.0), float(peak.value))
            finally:
                for o in (meter, ctl2, ctl):
                    _release(o)
    except OSError as e:
        log.debug("audio sessions unavailable: %s", e)
    finally:
        for o in (sessions, mgr, dev, enum):
            _release(o)
    return peaks


# --- processes and windows ------------------------------------------------------------------------
_k32, _u32 = ctypes.windll.kernel32, ctypes.windll.user32


def exe_of(pid: int) -> str:
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        _k32.CloseHandle(h)


def window_title_of(pid: int) -> str:
    """The title of the process's visible top-level window with the longest title."""
    best = [""]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, byref(owner))
        if owner.value == pid and _u32.IsWindowVisible(hwnd):
            n = _u32.GetWindowTextLengthW(hwnd)
            if n > len(best[0]):
                buf = ctypes.create_unicode_buffer(n + 1)
                _u32.GetWindowTextW(hwnd, buf, n + 1)
                best[0] = buf.value
        return True

    _u32.EnumWindows(each, 0)
    return best[0]


def playing_players() -> list[tuple[str, str]]:
    """(exe, track title) for every known desktop player that is making sound now."""
    out = []
    for pid in sounding_pids():
        exe = exe_of(pid)
        if exe.lower() in PLAYERS:
            out.append((exe, track_title(window_title_of(pid), exe)))
    return out
