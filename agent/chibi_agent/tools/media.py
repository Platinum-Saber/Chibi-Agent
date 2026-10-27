"""Media keys and volume. Side effects, but harmless and frequent: no confirmation."""
from __future__ import annotations

import ctypes

from . import Result, tool

user32 = ctypes.windll.user32
KEYS = {"play": 0xB3, "pause": 0xB3, "toggle": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _tap(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


@tool("media", "Pause or resume whatever music or video is playing, or skip tracks.", {"action": ("play, pause, next or previous", True)},
      side_effect=True, confirm=False)
def media(action: str) -> Result:
    a = action.lower().strip()
    a = "previous" if a.startswith("prev") or a == "back" else ("next" if a in ("skip", "next") else a)
    if a not in KEYS:
        return Result(f"Unknown media action '{action}'.")
    _tap(KEYS[a])
    return Result(f"Sent {a}.")


def _endpoint():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


@tool("set_volume", "Set or change the system volume.",
      {"level": ("0-100, or 'up', 'down', 'mute', 'unmute'", True)}, side_effect=True, confirm=False)
def set_volume(level: str) -> Result:
    ev = _endpoint()
    lv = level.lower().strip().rstrip("%")
    if lv in ("mute", "unmute"):
        ev.SetMute(lv == "mute", None)
        return Result(f"{lv.capitalize()}d.")
    cur = ev.GetMasterVolumeLevelScalar()
    if lv in ("up", "down"):
        new = min(1.0, max(0.0, cur + (0.1 if lv == "up" else -0.1)))
    else:
        try:
            new = min(100.0, max(0.0, float(lv))) / 100
        except ValueError:
            return Result(f"'{level}' is not a volume level.")
    ev.SetMasterVolumeLevelScalar(new, None)
    return Result(f"Volume {round(new * 100)}%.")
