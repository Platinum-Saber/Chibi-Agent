"""The IPC hub: a loopback WebSocket server the overlay and voice processes connect to.

On start it picks a free port, makes a random token and writes both to run.json
(under %LOCALAPPDATA%, which only this user and SYSTEM can read). A client must
send `hello` with that token and the protocol version as its first frame.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

import websockets
from pydantic import ValidationError

from chibi_shared import paths
from chibi_shared.protocol import VERSION, Hello, Lip, Message, Msg, Role, Welcome, decode, encode

log = logging.getLogger(__name__)
Handler = Callable[[Role, Message], Awaitable[None]]


class Hub:
    def __init__(self, run_file: Path = paths.RUN_FILE):
        self.run_file = run_file
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self.clients: dict[Role, websockets.ServerConnection] = {}
        self.connected: dict[Role, asyncio.Event] = {"overlay": asyncio.Event(), "voice": asyncio.Event()}
        self._handlers: list[Handler] = []
        self._server = None

    def on_message(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        self._server = await websockets.serve(self._serve, "127.0.0.1", 0, max_size=8 * 2**20)
        self.port = self._server.sockets[0].getsockname()[1]
        self.run_file.parent.mkdir(parents=True, exist_ok=True)
        self.run_file.write_text(json.dumps({"port": self.port, "token": self.token}), encoding="utf-8")
        log.info("hub listening on 127.0.0.1:%d", self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.run_file.unlink(missing_ok=True)

    async def send(self, role: Role, msg: Msg) -> bool:
        ws = self.clients.get(role)
        if ws is None:
            return False
        try:
            await ws.send(encode(msg))
            return True
        except websockets.ConnectionClosed:
            return False

    async def _serve(self, ws: websockets.ServerConnection) -> None:
        try:
            first = decode(await asyncio.wait_for(ws.recv(), 5))
        except (asyncio.TimeoutError, ValidationError, websockets.ConnectionClosed):
            await ws.close(1008, "bad handshake")
            return
        if not (isinstance(first, Hello) and secrets.compare_digest(first.token, self.token)
                and first.version == VERSION):
            log.warning("rejected a client: bad token or version")
            await ws.close(1008, "unauthorised")
            return
        role = first.role
        old = self.clients.get(role)
        if old is not None:
            await old.close(1000, "replaced")
        self.clients[role] = ws
        self.connected[role].set()
        await ws.send(encode(Welcome()))
        log.info("%s connected", role)
        try:
            async for raw in ws:
                try:
                    msg = decode(raw)
                except ValidationError as e:
                    log.warning("bad message from %s: %s", role, e)
                    continue
                if isinstance(msg, Lip):  # voice -> overlay, 60 Hz: relay without fan-out
                    await self.send("overlay", msg)
                    continue
                for h in self._handlers:
                    try:
                        await h(role, msg)
                    except Exception:
                        log.exception("handler failed on %s", msg.t)
        except websockets.ConnectionClosed:
            pass
        finally:
            if self.clients.get(role) is ws:
                del self.clients[role]
                self.connected[role].clear()
                log.info("%s disconnected", role)
