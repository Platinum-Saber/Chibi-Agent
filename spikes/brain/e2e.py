"""End of speech -> first audio, with STT, the LLM and F5-TTS all on the GPU.

Runs in the voice venv (it needs torch/F5/whisper):
  ..\\voice\\.venv\\Scripts\\python e2e.py [--turns 10]

Spoken questions are synthesised once with Kokoro (a stand-in for Master's mic).
Two timings per turn:
  plain:  first audio = F5 render of the first sentence (opener included)
  cached: the opener ("Answer." etc.) plays from a pre-rendered clip as soon as
          the LLM emits it; F5 renders the next sentence meanwhile
Then the gaming-mode check: unload everything and time how fast VRAM comes back.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "voice"))
from common import KOKORO_DIR, OUT as VOICE_OUT, RAPHAEL_NFE, RAPHAEL_SPEED, Timer, raphael_ref, vram_used_mb  # noqa: E402

import httpx  # noqa: E402
import numpy as np  # noqa: E402

from tools import persona  # noqa: E402

URL = "http://127.0.0.1:11434"
MODEL = "qwen3.5:4b"
MARKERS = ("Answer.", "Notice.", "Understood.", "Confirmed.", "Warning.")
QUESTIONS = [
    "Raphael, what is the capital of Japan?",
    "Good morning. How are you today?",
    "Give me one tip for staying focused while studying.",
    "What does a GPU do, in one sentence?",
    "Tell me something interesting about slimes.",
    "How many minutes are in a day?",
    "Should I drink coffee this late at night?",
    "What is the difference between RAM and storage?",
    "Recommend a short break activity.",
    "What is two hundred times four?",
]


def first_sentences(stream):
    """Yield (sentence, t_emitted) as the LLM streams."""
    buf = ""
    for piece in stream:
        buf += piece
        while True:
            m = re.search(r"(?<=[.?!])\s", buf)
            if not m:
                break
            yield buf[:m.start()].strip(), time.perf_counter()
            buf = buf[m.end():]
    if buf.strip():
        yield buf.strip(), time.perf_counter()


def llm_stream(text):
    body = {"model": MODEL, "stream": True, "think": False, "keep_alive": "120s",
            "options": {"num_ctx": 8192},
            "messages": [{"role": "system", "content": persona()}, {"role": "user", "content": text}]}
    with httpx.stream("POST", f"{URL}/api/chat", json=body, timeout=300) as r:
        for line in r.iter_lines():
            if line:
                msg = json.loads(line)
                yield msg.get("message", {}).get("content", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=10)
    args = ap.parse_args()
    base = vram_used_mb()

    import torchaudio.functional as AF
    import torch
    from faster_whisper import WhisperModel
    from f5_tts.api import F5TTS
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin"))
    asks = []
    for q in QUESTIONS[:args.turns]:
        wav, sr = kokoro.create(q, voice="am_michael", speed=1.0, lang="en-us")
        asks.append(AF.resample(torch.from_numpy(np.asarray(wav, np.float32)), sr, 16000).numpy())

    stt = WhisperModel("small.en", device="cuda", compute_type="int8_float16")
    tts = F5TTS(model="F5TTS_v1_Base")
    ref, ref_text = raphael_ref()
    say = lambda s: tts.infer(ref, ref_text, s, nfe_step=RAPHAEL_NFE, speed=RAPHAEL_SPEED, show_info=lambda *a: None)[0]  # noqa: E731
    say("Warming up.")
    stt.transcribe(asks[0], language="en", beam_size=1)
    list(llm_stream("Hello."))
    print(f"all loaded: VRAM {vram_used_mb()} MB (baseline {base} MB)")

    rows, peak = [], 0
    for i, audio in enumerate(asks):
        t_end = time.perf_counter()  # Master lets go of push-to-talk
        segs, _ = stt.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        text = " ".join(s.text for s in segs).strip()
        t_stt = time.perf_counter()
        sents = first_sentences(llm_stream(text))
        s1, t_s1 = next(sents)
        if s1 in MARKERS:
            # cached path: opener clip plays now; render the next sentence
            t_opener = t_s1
            s2, t_s2 = next(sents, ("", t_s1))
            with Timer() as tr:
                say(s2) if s2 else None
            cached = t_opener - t_end
            cached_next = t_s2 + tr.s - t_end
            # plain path: F5 renders "Answer. <sentence>" in one go
            with Timer() as tp:
                say(f"{s1} {s2}")
            plain = t_s2 - t_end + tp.s
        else:
            with Timer() as tp:
                say(s1)
            plain = t_s1 - t_end + tp.s
            cached = cached_next = plain
        list(sents)  # drain
        peak = max(peak, vram_used_mb())
        rows.append(dict(stt=t_stt - t_end, llm_first=t_s1 - t_stt, plain=plain,
                         cached_opener=cached, cached_next=cached_next))
        print(f"{i}: '{text}' -> '{s1}' | stt {rows[-1]['stt']:.2f}s llm {rows[-1]['llm_first']:.2f}s "
              f"| first audio plain {plain:.2f}s, cached opener {cached:.2f}s (next ready {cached_next:.2f}s)")

    med = {k: statistics.median(r[k] for r in rows) for k in rows[0]}
    print("median:", {k: round(v, 2) for k, v in med.items()})
    print(f"plain <= 1.5s in {sum(r['plain'] <= 1.5 for r in rows)}/{len(rows)}; "
          f"cached opener <= 1.5s in {sum(r['cached_opener'] <= 1.5 for r in rows)}/{len(rows)}; "
          f"next sentence ready before ~0.8s opener clip ends: "
          f"{sum(r['cached_next'] - r['cached_opener'] <= 0.8 for r in rows)}/{len(rows)}")
    print(f"peak VRAM {peak} MB = baseline {base} + {peak - base} MB")

    # gaming mode: drop the LLM and the voice models
    t0 = time.perf_counter()
    for m in (MODEL, "nomic-embed-text"):
        httpx.post(f"{URL}/api/generate", json={"model": m, "keep_alive": 0}, timeout=60)
    del tts, stt
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    while vram_used_mb() > base + 400 and time.perf_counter() - t0 < 30:
        time.sleep(0.1)
    print(f"gaming mode: VRAM {vram_used_mb()} MB after {time.perf_counter() - t0:.1f}s "
          f"(this process still holds its CUDA context; the real voice process exits)")
    (VOICE_OUT.parent.parent / "brain" / "out").mkdir(exist_ok=True)
    with open(HERE / "out" / "e2e.json", "w") as f:
        json.dump(dict(rows=rows, median=med, peak=peak, base=base), f, indent=1)


if __name__ == "__main__":
    main()
