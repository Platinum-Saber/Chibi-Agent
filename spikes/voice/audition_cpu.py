"""Audition CPU voice cloners against her reference clip: Kyutai Pocket TTS and Chatterbox Nano.

Off-screen and CPU only: no GPU, no agent connection, no playback, below-normal priority, so
the running Raphael is untouched. Each engine has its own venv (their torch pins differ):

  uv venv --python 3.11 spikes/voice/pocket/.venv
  uv pip install --python spikes/voice/pocket/.venv pocket-tts scipy soundfile --extra-index-url https://download.pytorch.org/whl/cpu
  uv venv --python 3.11 spikes/voice/chatterbox/.venv
  uv pip install --python spikes/voice/chatterbox/.venv chatterbox-tts soundfile --extra-index-url https://download.pytorch.org/whl/cpu

  spikes/voice/pocket/.venv/Scripts/python spikes/voice/audition_cpu.py pocket
  spikes/voice/chatterbox/.venv/Scripts/python spikes/voice/audition_cpu.py chatterbox

Output (outside git, beside the reference): ChibiAgent/voice/audition_cpu/<engine>/<n>_<label>.wav,
plus timings.csv. The number lines render twice: as the LLM writes them, and through `speakable()`.
"""
import contextlib
import csv
import ctypes
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", r"D:\Projects\Chibi-Agent-Project\ChibiAgent\hf")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # the 4060 belongs to Raphael

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "voice"))  # chibi_voice.tts: speakable(), calm()
from chibi_voice.tts import calm, speakable  # noqa: E402

VOICE = Path(r"D:\Projects\Chibi-Agent-Project\ChibiAgent\voice")
REF = VOICE / "ref_06_clean.wav"  # config.toml's reference (10.1 s, 24 kHz mono)
OUT = VOICE / "audition_cpu"

AUDITION = [  # spikes/voice/common.py's audition lines, then numbers
    ("notice", "Notice. Master, you have a new message."),
    ("answer", "Answer. The capital of Australia is Canberra, not Sydney."),
    ("understood", "Understood. Opening the file now."),
    ("warning", "Warning. Your battery is below ten percent."),
    ("report", "Report. Two events today, one deadline on Friday. End of report."),
    ("numbers", "Understood, Sir. There are 3.5 hours until the next meeting at 10:30."),
    ("money", "The plan costs $4.99 a month, and version 2.1.3 is out."),
]


def pocket():
    import torch
    from pocket_tts import TTSModel
    model = TTSModel.load_model()
    t0 = time.perf_counter()
    state = model.get_state_for_audio_prompt(str(REF))
    print(f"pocket: voice prompt in {time.perf_counter() - t0:.1f}s")
    return lambda text: (model.generate_audio(state, text).numpy(), model.sample_rate), torch


def chatterbox():
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    model = ChatterboxTurboTTS.from_pretrained(device="cpu", nano=True)
    return lambda text: (model.generate(text, audio_prompt_path=str(REF)).squeeze(0).numpy(), model.sr), torch


def main():
    global REF
    engine = sys.argv[1] if len(sys.argv) > 1 else ""
    if engine not in ("pocket", "chatterbox"):
        sys.exit("usage: audition_cpu.py pocket|chatterbox [reference.wav]")
    if len(sys.argv) > 2:  # another voice to clone; its clips go to <engine>_<stem>/
        REF = Path(sys.argv[2])
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # below normal
    t0 = time.perf_counter()
    synth, torch = {"pocket": pocket, "chatterbox": chatterbox}[engine]()
    torch.set_num_threads(8)
    print(f"{engine}: loaded in {time.perf_counter() - t0:.1f}s on {torch.get_num_threads()} threads")
    out = OUT / (engine if len(sys.argv) <= 2 else f"{engine}_{REF.stem}")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    jobs = [(f"{i}_{label}", text) for i, (label, text) in enumerate(AUDITION, 1)]
    jobs += [(f"{i}_{label}_spoken", calm(speakable(text))) for i, (label, text) in enumerate(AUDITION, 1)
             if speakable(text) != text]
    # Pocket updates its voice state in place on its own threads: torch's inference mode breaks that.
    with contextlib.nullcontext() if engine == "pocket" else torch.inference_mode():
        synth("Warming up.")
        for name, text in jobs:
            t = time.perf_counter()
            wav, sr = synth(text)
            secs = time.perf_counter() - t
            wav = np.asarray(wav, dtype=np.float32).reshape(-1)
            sf.write(out / f"{name}.wav", wav, sr)
            dur = len(wav) / sr
            rows.append((name, f"{secs:.2f}", f"{dur:.2f}", f"{secs / dur:.2f}", text))
            print(f"  {name}: {secs:.1f}s for {dur:.1f}s audio (RTF {secs / dur:.2f})")
    with open(out / "timings.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("clip", "synth_s", "audio_s", "rtf", "text"), *rows])
    print(f"listen in {out}")


if __name__ == "__main__":
    main()
