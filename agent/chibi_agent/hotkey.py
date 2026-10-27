"""Global hold-to-talk hotkey through a low-level keyboard hook (pynput).

Works from any window, games included. The hook runs on its own thread; the
callbacks are handed to the asyncio loop. Key repeat while held is ignored.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from pynput import keyboard

log = logging.getLogger(__name__)

_MODS = {
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
}


def parse(combo: str) -> tuple[set[str], str]:
    """'alt+1' -> ({'alt'}, '1')."""
    parts = [p.strip().lower() for p in combo.split("+")]
    return set(parts[:-1]), parts[-1]


def _char(key) -> str | None:
    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None and (48 <= key.vk <= 57 or 65 <= key.vk <= 90):
            return chr(key.vk).lower()  # vk survives Alt/Ctrl, where .char doesn't
        return key.char.lower() if key.char else None
    return getattr(key, "name", None)


class HoldHotkey:
    """Calls on_down when the combo goes down and on_up when its main key is released."""

    def __init__(self, combo: str, loop: asyncio.AbstractEventLoop,
                 on_down: Callable[[], None], on_up: Callable[[], None]):
        self.mods, self.key = parse(combo)
        self.loop, self.on_down, self.on_up = loop, on_down, on_up
        self.held_mods: set[str] = set()
        self.active = False
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def start(self) -> None:
        self._listener.start()
        log.info("hold-to-talk on %s", "+".join([*sorted(self.mods), self.key]))

    def stop(self) -> None:
        self._listener.stop()

    def _mod_of(self, key) -> str | None:
        return next((m for m, keys in _MODS.items() if key in keys), None)

    def _press(self, key) -> None:
        mod = self._mod_of(key)
        if mod:
            self.held_mods.add(mod)
            return
        if not self.active and _char(key) == self.key and self.mods <= self.held_mods:
            self.active = True
            self.loop.call_soon_threadsafe(self.on_down)

    def _release(self, key) -> None:
        mod = self._mod_of(key)
        if mod:
            self.held_mods.discard(mod)
            return
        if self.active and _char(key) == self.key:
            self.active = False
            self.loop.call_soon_threadsafe(self.on_up)
