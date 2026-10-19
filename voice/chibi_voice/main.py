"""The voice process: push-to-talk STT, the F5 sentence queue, clips and lip RMS.

All model work runs on two single-thread pools (one per model, so calls into a model
never overlap and a load/unload waits behind queued work); audio I/O runs on
PortAudio's threads. The asyncio loop only routes messages.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from chibi_shared import paths
from chibi_shared.protocol import Lip, Load, Msg, Ptt, Speak, SpeakState, Stop, Transcript

from .clips import ClipCache, voice_id
from .player import Player
from .speech import Item, SpeechQueue
from .stt import Recorder, Stt
from .tts import MODEL, Tts

log = logging.getLogger(__name__)

# After a failed F5 load, a live sentence retries it at most this often (a reply's
# sentences would otherwise each wait out a ~15 s load that fails the same way).
TTS_RETRY_S = 30.0


class VoiceApp:
    def __init__(self, vcfg: dict, send):
        self._send = send
        self.tts = Tts(vcfg)
        self.stt = Stt(vcfg.get("stt_model", "small.en"))
        self.clips = ClipCache(paths.CLIPS, voice_id(Path(self.tts.ref), self.tts.ref_text,
                                                     self.tts.speed, self.tts.nfe, MODEL))
        self.recorder = Recorder()
        self.player = Player(on_lip=lambda rms: self._send(Lip(rms=round(rms, 3))))
        self.queue = SpeechQueue(self._render, self.player.play, self._emit)
        self._tts_pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self._stt_pool = ThreadPoolExecutor(1, thread_name_prefix="stt")
        self._bg: set[asyncio.Task] = set()
        self.loading: asyncio.Future | None = None
        self._tts_failed_at: float | None = None  # monotonic time of the last failed load

    # --- plumbing ---------------------------------------------------------------
    async def _on(self, pool: ThreadPoolExecutor, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(pool, fn, *args)

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    async def _emit(self, utt_id: str, state: str) -> None:
        await self._send(SpeakState(utt_id=utt_id, state=state))

    # --- models -------------------------------------------------------------------
    async def load_stt(self, device: str = "cuda") -> None:
        try:
            await self._on(self._stt_pool, self.stt.load, device)
        except Exception:
            log.exception("stt load failed")

    async def load_tts(self) -> None:
        try:
            await self._on(self._tts_pool, self.tts.load)
            self._tts_failed_at = None
            made = await self._on(self._tts_pool, self.clips.ensure, self.tts.synth)
            if made:
                log.info("rendered %d clips", len(made))
        except Exception:
            if not self.tts.loaded:
                self._tts_failed_at = time.monotonic()
            log.exception("tts load failed")

    async def _retry_tts(self) -> None:
        """A failed load (once: a CUDA error reading the checkpoint) left F5 unloaded and
        every live sentence silent until a restart. Retry it when speech needs it; an
        unload the agent asked for (gaming mode) is not a failure and stays unloaded."""
        failed = self._tts_failed_at
        if self.tts.loaded or failed is None or time.monotonic() - failed < TTS_RETRY_S:
            return
        log.info("tts failed to load earlier; retrying for live speech")
        await self.load_tts()

    def start(self) -> None:
        try:
            self.player.open()  # opened once, so the first clip starts within ~0.1 s
        except Exception:
            log.exception("no audio output; will retry on the first sentence")
        self.queue.start()
        self.loading = asyncio.gather(self.load_stt(), self.load_tts())

    # --- speaking -------------------------------------------------------------------
    async def _render(self, item: Item) -> tuple[np.ndarray, int]:
        if item.clip:
            path = self.clips.lookup(item.clip)
            if path is not None:
                import soundfile as sf
                data, sr = await asyncio.to_thread(sf.read, str(path), dtype="float32")
                return data, sr
            log.info("no clip for %r; synthesising it", item.clip)
        await self._retry_tts()
        return await self._on(self._tts_pool, self.tts.synth, item.text or item.clip)

    # --- listening ------------------------------------------------------------------
    async def transcribe(self, audio: np.ndarray) -> tuple[str, int]:
        t0 = time.perf_counter()
        try:
            text = await self._on(self._stt_pool, self.stt.transcribe, audio)
        except Exception:
            log.exception("transcription failed")
            text = ""
        return text, int((time.perf_counter() - t0) * 1000)

    async def _ptt_up(self) -> None:
        audio = await asyncio.to_thread(self.recorder.stop)
        text, ms = await self.transcribe(audio)
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        db = 20 * np.log10(max(float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0, 1e-9))
        # Loudness and mic name: an empty transcript from 2 s of audio means the mic was silent
        # (peak near 0: muted, or another app holds it) or too quiet (rms below ~-50 dBFS).
        log.info("transcript (%.1fs audio, peak %.3f, rms %.0f dBFS, mic %s, %d ms): %r",
                 audio.size / 16000, peak, db, getattr(self.recorder, "device", "?"), ms, text)
        await self._send(Transcript(text=text, ms=ms))

    # --- messages -------------------------------------------------------------------
    async def handle(self, msg: Msg) -> None:
        if isinstance(msg, Ptt):
            if msg.down:
                await asyncio.to_thread(self.recorder.start)
            elif self.recorder.recording:
                self._spawn(self._ptt_up())
        elif isinstance(msg, Speak):
            self.queue.submit(Item(msg.utt_id, msg.text, msg.clip))
        elif isinstance(msg, Stop):
            await self.queue.stop()
        elif isinstance(msg, Load):
            stt, tts = msg.what in ("stt", "all"), msg.what in ("tts", "all")
            if msg.t == "load":
                if stt:
                    self._spawn(self.load_stt("cuda"))
                if tts:
                    self._spawn(self.load_tts())
            else:
                if stt:
                    self._spawn(self._on(self._stt_pool, self.stt.unload))
                if tts:
                    self._tts_failed_at = None
                    self._spawn(self._on(self._tts_pool, self.tts.unload))
        else:
            log.debug("ignoring %s", msg.t)

    async def close(self) -> None:
        await self.queue.close()
        self.player.close()
        if self.recorder.recording:
            self.recorder.stop()
        for t in list(self._bg):
            t.cancel()
        for pool in (self._tts_pool, self._stt_pool):
            pool.shutdown(wait=False, cancel_futures=True)


async def run(vcfg: dict) -> None:
    from chibi_shared.protocol import Quit
    from chibi_shared.wsclient import AgentLink

    link = AgentLink("voice")
    app = VoiceApp(vcfg, link.send)
    app.start()
    try:
        async for msg in link.messages():
            if isinstance(msg, Quit):
                log.info("quit")
                break
            await app.handle(msg)
    finally:
        await app.close()
        await link.close()
