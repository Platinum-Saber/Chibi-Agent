"""Tray commands and app state: mute, gaming mode, memory viewer, settings, autostart, quit.

The agent owns this state and sends `State` to the overlay whenever it changes
(and when the overlay connects) so the tray's check marks stay true.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from chibi_shared import paths
from chibi_shared.protocol import Command, Fullscreen, MemoryItems, Message, Role, State

log = logging.getLogger(__name__)
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT = STARTUP / "Raphael (Chibi-Agent).lnk"
USER_CONFIG_HEADER = """# Your Chibi-Agent settings. Anything here overrides the defaults in the repo's
# config.toml (copy a [section] and the keys you want to change). Restart Raphael after editing.
"""


class Controller:
    def __init__(self, hub, orch, vram, memory, quit_cb: Callable[[], None]):
        self.hub, self.orch, self.vram, self.memory, self.quit_cb = hub, orch, vram, memory, quit_cb
        vram.on_change = self.push_state
        hub.on_message(self.on_message)
        hub.on_connect(self._connected)

    async def _connected(self, role: Role) -> None:
        if role == "overlay":
            await self.push_state()

    async def push_state(self) -> None:
        await self.hub.send("overlay", State(muted=self.orch.muted, gaming=self.vram.gaming,
                                             autostart=SHORTCUT.exists()))

    async def on_message(self, role: Role, msg: Message) -> None:
        if isinstance(msg, Fullscreen):
            await self.vram.set_fullscreen(msg.exe if msg.active else "")
        elif isinstance(msg, Command):
            await self.command(msg.name, msg.arg)

    async def command(self, name: str, arg: str) -> None:
        log.info("tray: %s %s", name, arg)
        if name in ("mute", "unmute"):
            self.orch.muted = name == "mute"
        elif name in ("gaming_on", "gaming_off"):
            await self.vram.set_manual(name == "gaming_on")
            return  # set_manual pushes the state itself
        elif name == "memory_list":
            await self.hub.send("overlay", MemoryItems(items=self.memory.store.all_facts()))
            return
        elif name == "memory_delete":
            ids = [int(x) for x in arg.split(",") if x.strip().isdigit()]
            self.memory.forget(ids)
            await self.hub.send("overlay", MemoryItems(items=self.memory.store.all_facts()))
            return
        elif name == "open_settings":
            open_user_config()
            return
        elif name in ("autostart_on", "autostart_off"):
            set_autostart(name == "autostart_on")
        elif name == "quit":
            self.quit_cb()
            return
        await self.push_state()


def open_user_config() -> None:
    cfg = paths.USER_CONFIG
    if not cfg.exists():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(USER_CONFIG_HEADER, encoding="utf-8")
    os.startfile(cfg)  # noqa: S606 (Kryo clicked "Settings" in the tray)


def set_autostart(on: bool) -> None:
    """A shortcut in the Startup folder, made only when Kryo ticks the tray option."""
    if not on:
        SHORTCUT.unlink(missing_ok=True)
        return
    import win32com.client
    agent_dir = Path(__file__).resolve().parents[1]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    venv_pythonw = agent_dir / ".venv" / "Scripts" / "pythonw.exe"
    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(SHORTCUT))
    link.TargetPath = str(venv_pythonw if venv_pythonw.exists() else pythonw)
    link.Arguments = "-m chibi_agent"
    link.WorkingDirectory = str(agent_dir)
    link.Description = "Raphael, the Chibi-Agent desktop companion"
    link.Save()
