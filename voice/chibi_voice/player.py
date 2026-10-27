"""Plays buffers through the default output and reports lip RMS at 60 Hz while they play.

One output stream stays open (opening one costs ~85 ms, and the default 'high'
latency another ~180 ms on MME), playing silence between sentences. PortAudio pulls
samples on its own thread (the callback); the asyncio side hands it a buffer, then
samples the precomputed RMS curve on a 60 Hz clock, shifted by the output latency
so the mouth matches what is heard.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

import numpy as np
import sounddevice as sd

from .lipsync import FPS, block_size, levels

log = logging.getLogger(__name__)

SR = 24000  # F5's output rate; anything else is resampled to it
OnLip = Callable[[float], Awaitable[object]]


def _resample(audio: np.ndarray, sr: int, to: int) -> np.ndarray:
    n = int(round(len(audio) * to / sr))
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


class Player:
    def __init__(self, on_lip: OnLip | None = None, sr: int = SR):
        self._on_lip = on_lip
        self.sr = sr
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._buf: np.ndarray | None = None
        self._pos = 0
        self._on_drained: Callable[[], None] | None = None

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            log.debug("output status: %s", status)
        drained = None
        with self._lock:
            buf = self._buf
            if buf is None:
                outdata.fill(0)
                return
            chunk = buf[self._pos:self._pos + frames]
            outdata[:len(chunk), 0] = chunk
            outdata[len(chunk):, 0] = 0
            self._pos += frames
            if self._pos >= len(buf):
                self._buf, drained, self._on_drained = None, self._on_drained, None
        if drained is not None:
            drained()

    def open(self) -> None:
        if self._stream is not None and self._stream.active:
            return
        if self._stream is not None:
            self._stream.close()
        self._stream = sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32",
                                       blocksize=block_size(self.sr), latency="low",
                                       callback=self._callback)
        self._stream.start()
        log.info("output stream open: %s, %.0f ms latency",
                 sd.query_devices(kind="output")["name"], self._stream.latency * 1000)

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.abort()
            stream.close()

    @property
    def latency(self) -> float:
        return self._stream.latency if self._stream is not None else 0.0

    def _clear(self) -> None:
        with self._lock:
            self._buf, self._on_drained = None, None

    async def play(self, audio: np.ndarray, sr: int,
                   on_start: Callable[[], Awaitable[None]] | None = None) -> None:
        loop = asyncio.get_running_loop()
        audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        if sr != self.sr:
            audio = _resample(audio, sr, self.sr)
        if audio.size == 0:
            return
        lip = levels(audio, self.sr)
        drained = loop.create_future()
        try:
            self.open()
        except sd.PortAudioError:
            self._stream = None
            raise
        with self._lock:
            self._buf, self._pos = audio, 0
            self._on_drained = lambda: loop.call_soon_threadsafe(
                lambda: drained.done() or drained.set_result(None))
        t0 = loop.time() + self.latency
        try:
            if on_start is not None:
                await on_start()
            # Done once the last sample has left the speaker, not just the buffer.
            end = asyncio.ensure_future(drained)
            period = 1 / FPS
            tick = loop.time()
            while True:
                now = loop.time()
                if end.done() and now >= t0 + len(audio) / self.sr:
                    break
                if self._on_lip is not None:
                    i = int((now - t0) * FPS)
                    await self._on_lip(float(lip[i]) if 0 <= i < len(lip) else 0.0)
                tick += period
                await asyncio.sleep(max(0.0, tick - loop.time()))
                if not end.done() and loop.time() - t0 > len(audio) / self.sr + 2.0:
                    raise RuntimeError("output stream stalled")
        except BaseException:
            self._clear()
            raise
        finally:
            if self._on_lip is not None:
                await self._on_lip(0.0)
