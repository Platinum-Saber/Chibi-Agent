"""Tray commands and app state: mute, gaming mode, memory viewer, settings, autostart,
Google sign-in, quit.

The agent owns this state and sends `State` to the overlay whenever it changes
(and when the overlay connects) so the tray's check marks stay true.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from chibi_shared import paths
from chibi_shared.protocol import Bubble, Command, Fullscreen, MemoryItems, Message, Role, State

from .google_auth import short

log = logging.getLogger(__name__)
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT = STARTUP / "Raphael (Chibi-Agent).lnk"
USER_CONFIG_HEADER = """# Your Chibi-Agent settings. Anything here overrides the defaults in the repo's
# config.toml (copy a [section] and the keys you want to change). Restart Raphael after editing.
"""


class Controller:
    def __init__(self, hub, orch, vram, memory, quit_cb: Callable[[], None], google=None):
        self.hub, self.orch, self.vram, self.memory, self.quit_cb = hub, orch, vram, memory, quit_cb
        self.google = google  # chibi_agent.google_auth.GoogleAuth
        self._signing_in: asyncio.Task | None = None
        vram.on_change = self.push_state
        hub.on_message(self.on_message)
        hub.on_connect(self._connected)

    async def _connected(self, role: Role) -> None:
        if role == "overlay":
            await self.push_state()

    async def push_state(self) -> None:
        await self.hub.send("overlay", State(muted=self.orch.muted, gaming=self.vram.gaming,
                                             autostart=SHORTCUT.exists(),
                                             google_accounts=self.google.accounts() if self.google else []))

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
        elif name == "google_signin" and self.google:
            if not (self._signing_in and not self._signing_in.done()):
                self._signing_in = asyncio.create_task(self._sign_in())
            return
        elif name == "google_signout" and self.google:
            self.google.sign_out(arg or None)
        elif name == "quit":
            self.quit_cb()
            return
        await self.push_state()

    async def _sign_in(self) -> None:
        """Kryo finishes the sign-in in the browser; she says how it went."""
        try:
            email = await self.google.sign_in()
            await self._tell("Confirmed.", f"{short(email)} is connected, Kryo.")
        except Exception as e:
            log.warning("google sign-in failed: %s", e)
            await self._tell("Warning.", f"The Google sign-in did not work. {e}")
        await self.push_state()

    async def _tell(self, marker: str, line: str) -> None:
        await self.hub.send("overlay", Bubble(text=f"{marker} {line}", done=True))
        await self.orch._say(marker, first=True)
        await self.orch._say(line, first=False)


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
