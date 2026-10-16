"""`python -m chibi_voice --selftest`: no agent needed. Loads both models, plays the
"Answer." clip, one F5 sentence and two queued ones, then transcribes 3 s of mic audio,
printing the timings."""
from __future__ import annotations

import asyncio
import functools
import sys
import time

from chibi_shared.protocol import Lip, Msg, SpeakState

from .main import VoiceApp
from .player import _resample
from .speech import Item

# F5 output is muted by swapping sys.stdout while it runs; write past that.
print = functools.partial(print, file=sys.__stdout__, flush=True)  # noqa: A001


def _vram_mb() -> int | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml.nvmlDeviceGetMemoryInfo(h).used // 2**20
    except Exception:
        return None


async def selftest(vcfg: dict) -> None:
    states: dict[tuple[str, str], float] = {}
    lips: list[float] = []
    changed = asyncio.Event()

    async def send(msg: Msg) -> bool:
        now = time.perf_counter()
        if isinstance(msg, Lip):
            lips.append(now)
        elif isinstance(msg, SpeakState):
            states[(msg.utt_id, msg.state)] = now
            changed.set()
        return True

    async def done(utt_id: str) -> str:
        while True:
            for s in ("end", "cancel"):
                if (utt_id, s) in states:
                    return s
            changed.clear()
            await changed.wait()

    vram0 = _vram_mb()
    app = VoiceApp(vcfg, send)
    print(f"clips missing before start: {len(app.clips.missing())}")
    t0 = time.perf_counter()
    app.start()
    await app.loading
    print(f"models + clips ready in {time.perf_counter() - t0:.1f}s "
          f"(stt on {app.stt.device}, tts loaded={app.tts.loaded}); "
          f"VRAM {vram0} -> {_vram_mb()} MB")

    async def say(utt_id: str, text: str, clip: str | None = None) -> None:
        lips.clear()
        t = time.perf_counter()
        app.queue.submit(Item(utt_id, text, clip))
        result = await done(utt_id)
        start = states.get((utt_id, "start"))
        if start is None:
            print(f"  {utt_id}: {result} without starting")
            return
        end = states[(utt_id, result)]
        print(f"  {utt_id}: start after {(start - t) * 1000:.0f} ms "
              f"(+{app.player.latency * 1000:.0f} ms output latency), "
              f"played {end - start:.2f}s, {len(lips) / max(end - start, 1e-3):.0f} lip msg/s")

    print("speaking:")
    await say("clip", "Answer.", clip="Answer.")
    await say("f5", "The capital of Japan is Tokyo, Master.")

    t = time.perf_counter()
    app.queue.submit(Item("q1", "Your meeting starts in ten minutes."))
    app.queue.submit(Item("q2", "I recommend leaving now."))
    await done("q2")
    s1, e1, s2 = states[("q1", "start")], states[("q1", "end")], states[("q2", "start")]
    print(f"  queue: q1 start after {(s1 - t) * 1000:.0f} ms, "
          f"gap q1 end -> q2 start {(s2 - e1) * 1000:.0f} ms")

    line = "Please remind me to call my mother at six tomorrow evening."
    audio, sr = await app._on(app._tts_pool, app.tts.synth, line)
    text, ms = await app.transcribe(_resample(audio, sr, 16000))
    print(f"  stt ({app.stt.device}) on {len(audio) / sr:.1f}s of her speech: {ms} ms -> {text!r}")

    print("recording 3 s: say something now...")
    await asyncio.to_thread(app.recorder.start)
    await asyncio.sleep(3)
    audio = await asyncio.to_thread(app.recorder.stop)
    text, ms = await app.transcribe(audio)
    print(f"  stt ({app.stt.device}) {ms} ms for {audio.size / 16000:.1f}s audio: {text!r}")
    await app.close()
