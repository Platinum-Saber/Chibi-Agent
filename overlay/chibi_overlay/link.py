"""Bridges the agent's WebSocket (asyncio, own thread) to the Qt main thread."""
from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from chibi_shared.protocol import Msg
from chibi_shared.wsclient import AgentLink


class QtLink(QObject):
    received = Signal(object)  # a chibi_shared.protocol message

    def __init__(self):
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._link = AgentLink("overlay")
        self._thread = threading.Thread(target=self._run, name="agent-link", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._pump())

    async def _pump(self) -> None:
        async for msg in self._link.messages():
            self.received.emit(msg)  # queued to the Qt thread (cross-thread signal)

    def send(self, msg: Msg) -> None:
        asyncio.run_coroutine_threadsafe(self._link.send(msg), self._loop)

    def stop(self) -> None:
        asyncio.run_coroutine_threadsafe(self._link.close(), self._loop)
