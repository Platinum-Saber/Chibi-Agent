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
from chibi_shared.protocol import Lip, Load, Msg, Ptt, Speak, SpeakState, Stop, Transcript, VoiceTune

from .clips import ALL_LINES, LINES, ClipCache
from .player import Player
from .speech import Item, Skip, SpeechQueue
from .stt import Recorder, Stt
from .tts import Tts

log = logging.getLogger(__name__)

# After a failed F5 load, a live sentence retries it at most this often (a reply's
# sentences would otherwise each wait out a ~15 s load that fails the same way).
TTS_RETRY_S = 30.0

# The last voice the Customize window chose. The overlay only sends it once it has connected,
# ~15 s in, so without this a start loads config.toml's F5 (40-100 s) only to swap it out.
LAST_VOICE = paths.LOCAL / "voice_tune.json"


def saved_voice(path: Path = LAST_VOICE) -> VoiceTune | None:
    try:
        return VoiceTune.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("ignoring unreadable %s", path, exc_info=True)
        return None


def save_voice(msg: VoiceTune, path: Path = LAST_VOICE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(msg.model_dump_json(include={"engine", "voice", "speed", "nfe"}), encoding="utf-8")
    except OSError:
        log.warning("could not save the voice choice to %s", path, exc_info=True)


class VoiceApp:
    def __init__(self, vcfg: dict, send, last_voice: Path = LAST_VOICE):
        self._send = send
        self._last_voice = last_voice
        self.tts = Tts(vcfg)
        if (saved := saved_voice(last_voice)) is not None:
            self.tts.tune(saved.engine, saved.voice, saved.speed, saved.nfe)
        self.stt = Stt(vcfg.get("stt_model", "small.en"))
        self.clips = ClipCache(paths.CLIPS, self.tts.voice_key(), ALL_LINES)
        self.recorder = Recorder()
        self.player = Player(on_lip=lambda rms: self._send(Lip(rms=round(rms, 3))))
        self.queue = SpeechQueue(self._render, self.player.play, self._emit)
        self._tts_pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self._stt_pool = ThreadPoolExecutor(1, thread_name_prefix="stt")
        self._bg: set[asyncio.Task] = set()
        self.loading: asyncio.Future | None = None
        self._tts_failed_at: float | None = None  # monotonic time of the last failed load
        self._tts_lazy = False  # F5 dropped for memory relief: reload it when speech needs it

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
            self._tts_lazy = False
            made = await self._on(self._tts_pool, self._ensure_clips)
            if made:
                log.info("rendered %d clips", len(made))
        except Exception:
            if not self.tts.loaded:
                self._tts_failed_at = time.monotonic()
            log.exception("tts load failed")
            return
        self._spawn(self._render_reactions())

    def _ensure_clips(self, lines: list[str] = LINES) -> list[str]:
        """Render missing clips (on the tts thread). The cache key is read here, beside the
        synth: a voice switch queued behind a load once had the old voice's cache filled with
        the new voice's audio, then rendered all ten clips again under the right key."""
        return ClipCache(paths.CLIPS, self.tts.voice_key(), lines).ensure(self.tts.synth)

    async def _render_reactions(self) -> None:
        """Her voice reactions, in the background after the openers: one tts job per line, so
        a live sentence waits behind at most one of them. Stops if the model goes (gaming mode)."""
        made = []
        for line in ALL_LINES[len(LINES):]:
            if not self.tts.loaded:
                break
            try:
                made += await self._on(self._tts_pool, self._ensure_clips, [line])
            except Exception as e:
                log.warning("reaction clip %r not rendered: %s", line, e)
                break
        if made:
            log.info("rendered %d reaction clips", len(made))

    async def _retry_tts(self) -> None:
        """A failed load (once: a CUDA error reading the checkpoint) left F5 unloaded and
        every live sentence silent until a restart. Retry it when speech needs it; an
        unload the agent asked for (gaming mode) is not a failure and stays unloaded."""
        failed = self._tts_failed_at
        if self.tts.loaded or failed is None or time.monotonic() - failed < TTS_RETRY_S:
            return
        log.info("tts failed to load earlier; retrying for live speech")
        await self.load_tts()

    async def retune(self, msg: VoiceTune) -> None:
        """A new voice from the Customize window: switch, load it, re-render the fixed lines.
        Switch and load are one job on the tts thread, so a test line sent right after waits
        for the new voice instead of hitting a half-switched engine."""
        def switch() -> bool:
            was_loaded = self.tts.model is not None or self.tts.kokoro is not None
            self.tts.tune(msg.engine, msg.voice, msg.speed, msg.nfe)
            if was_loaded:  # gaming mode's unload stays an unload
                self.tts.load()
            return was_loaded

        try:
            loaded = await self._on(self._tts_pool, switch)
        except Exception:
            log.exception("voice switch failed")
            self._tts_failed_at = time.monotonic()
            return
        self.clips = ClipCache(paths.CLIPS, self.tts.voice_key(), ALL_LINES)
        # What she really uses (an F5 choice becomes Kokoro while F5 is off): memrelief reads this.
        kokoro = self.tts.engine == "kokoro"
        save_voice(msg.model_copy(update={"engine": self.tts.engine, "speed": self.tts.speed,
                                          "voice": self.tts.kvoice if kokoro else msg.voice}), self._last_voice)
        log.info("voice -> %s %s (speed %.2f)", self.tts.engine,
                 self.tts.kvoice if self.tts.engine == "kokoro" else Path(self.tts.ref).name, self.tts.speed)
        if loaded:
            made = await self._on(self._tts_pool, self._ensure_clips)
            if made:
                log.info("rendered %d clips", len(made))
            self._spawn(self._render_reactions())

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
            if item.only_cached:
                raise Skip(f"no clip for {item.clip!r} yet")
            log.info("no clip for %r; synthesising it", item.clip)
        await self._retry_tts()
        if self._tts_lazy and not self.tts.loaded:
            log.info("tts was unloaded for memory relief; loading it for live speech")
            await self.load_tts()
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
            self.queue.submit(Item(msg.utt_id, msg.text, msg.clip, msg.only_cached))
        elif isinstance(msg, Stop):
            await self.queue.stop()
        elif isinstance(msg, VoiceTune):
            self._spawn(self.retune(msg))
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
                if tts and msg.reason == "memory":
                    self._spawn(self._relieve())
                elif tts:
                    self._tts_failed_at = None
                    self._tts_lazy = False
                    self._spawn(self._on(self._tts_pool, self.tts.unload))
        else:
            log.debug("ignoring %s", msg.t)

    async def _relieve(self) -> None:
        """Memory relief: drop F5 (~1 GB of VRAM, plus host memory) unless it is the voice in
        use right now; Kokoro is small and stays. A later sentence reloads F5 if needed."""
        if self.tts.model is None:
            log.info("memory relief: F5 is not loaded (%s voice); nothing to unload", self.tts.engine)
            return
        if self.tts.engine == "f5":
            self._tts_lazy = True
        await self._on(self._tts_pool, self.tts.unload_f5)

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
