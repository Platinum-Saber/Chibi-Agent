"""Client side of the agent's WebSocket: handshake, typed send/receive, reconnect."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable

import websockets

from . import paths
from .protocol import Hello, Message, Msg, Role, Welcome, decode, encode

log = logging.getLogger(__name__)


def read_run_file() -> tuple[int, str]:
    info = json.loads(paths.RUN_FILE.read_text(encoding="utf-8"))
    return info["port"], info["token"]


class AgentLink:
    """One connection from an overlay or voice process to the agent.

    `messages()` yields decoded messages and reconnects (with backoff) when the
    agent restarts; `send()` drops messages while disconnected instead of blocking.
    """

    def __init__(self, role: Role, on_connect: Callable[[], None] | None = None):
        self.role = role
        self.on_connect = on_connect  # after each handshake, e.g. to announce state
        self._ws = None
        self._closed = False

    async def _connect(self):
        port, token = read_run_file()
        ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=8 * 2**20)
        await ws.send(encode(Hello(role=self.role, token=token)))
        reply = decode(await asyncio.wait_for(ws.recv(), 5))
        if not isinstance(reply, Welcome):
            await ws.close()
            raise ConnectionError(f"agent refused the handshake: {reply}")
        return ws

    async def messages(self) -> AsyncIterator[Message]:
        delay = 0.25
        while not self._closed:
            try:
                self._ws = await self._connect()
                delay = 0.25
                log.info("connected to agent as %s", self.role)
                if self.on_connect:
                    self.on_connect()
                async for raw in self._ws:
                    yield decode(raw)
            except websockets.ConnectionClosed as e:
                if e.rcvd and e.rcvd.reason == "replaced":
                    log.warning("another %s process took over the link; stopping", self.role)
                    self._closed = True
                    return
                log.debug("agent link down (%s); retry in %.1fs", e, delay)
            except (OSError, ConnectionError, asyncio.TimeoutError, FileNotFoundError) as e:
                log.debug("agent link down (%s); retry in %.1fs", e, delay)
            self._ws = None
            if not self._closed:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

    async def send(self, msg: Msg) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(encode(msg))
            return True
        except websockets.ConnectionClosed:
            return False

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
