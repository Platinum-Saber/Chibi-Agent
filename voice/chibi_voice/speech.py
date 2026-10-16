"""The sentence queue: FIFO, renders sentence N+1 while N plays, `stop` cancels it all.

Two tasks share it: the renderer turns queued items into audio (one ahead of the
player) and the player plays them in order. Rendering and playback are injected so
the queue can be tested without a GPU or a sound card.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Item:
    utt_id: str
    text: str
    clip: str | None = None


Render = Callable[[Item], Awaitable[tuple[np.ndarray, int]]]
# play(audio, sr, on_start): returns when playback ends; cancelling it stops the sound.
Play = Callable[[np.ndarray, int, Callable[[], Awaitable[None]]], Awaitable[None]]
Emit = Callable[[str, str], Awaitable[None]]  # (utt_id, "start" | "end" | "cancel")


class SpeechQueue:
    def __init__(self, render: Render, play: Play, emit: Emit):
        self._render = render
        self._play = play
        self._emit = emit
        self._pending: asyncio.Queue[Item] = asyncio.Queue()
        self._ready: asyncio.Queue[tuple[Item, np.ndarray, int]] = asyncio.Queue(maxsize=1)
        self._open: dict[str, None] = {}  # utt_ids not yet ended, in submit order
        self._tasks: list[asyncio.Task] = []

    @property
    def busy(self) -> bool:
        return bool(self._open)

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._render_loop(), name="speech-render"),
                       asyncio.create_task(self._play_loop(), name="speech-play")]

    def submit(self, item: Item) -> None:
        self._open[item.utt_id] = None
        self._pending.put_nowait(item)

    async def _render_loop(self) -> None:
        while True:
            item = await self._pending.get()
            try:
                audio, sr = await self._render(item)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("could not render %s %r: %s", item.utt_id, item.text, e)
                await self._finish(item.utt_id, "cancel")
                continue
            await self._ready.put((item, audio, sr))

    async def _play_loop(self) -> None:
        while True:
            item, audio, sr = await self._ready.get()

            async def started(utt_id: str = item.utt_id) -> None:
                await self._emit(utt_id, "start")

            try:
                await self._play(audio, sr, started)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("could not play %s: %s", item.utt_id, e)
                await self._finish(item.utt_id, "cancel")
                continue
            await self._finish(item.utt_id, "end")

    async def _finish(self, utt_id: str, state: str) -> None:
        if utt_id in self._open:
            del self._open[utt_id]
            await self._emit(utt_id, state)

    async def _halt(self) -> list[str]:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        for q in (self._pending, self._ready):
            while not q.empty():
                q.get_nowait()
        ids = list(self._open)
        self._open.clear()
        return ids

    async def stop(self) -> None:
        """Barge-in: stop the current sentence, drop the rest, `cancel` each of them."""
        for utt_id in await self._halt():
            await self._emit(utt_id, "cancel")
        self.start()

    async def close(self) -> None:
        await self._halt()
