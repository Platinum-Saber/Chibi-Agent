"""Render the audition lines with each candidate voice, raw and with the Raphael FX chain.

Candidates:
  kokoro_<voice>   Kokoro stock voices directly (CPU, the fallback engine)
  f5_example       F5-TTS with its bundled reference clip
  f5_<kokoro voice> F5-TTS cloning a Kokoro stock voice (synthetic reference, no real person)
  f5_<name>        F5-TTS with recordings/ref_<name>.wav + .txt (your own or a consenting voice)

Output: out/audition/<candidate>/<n>_{raw,fx}.wav

Usage: python audition.py [--kokoro af_heart bf_emma ...]
"""
import argparse
import time

import numpy as np
import soundfile as sf
from pedalboard import Chorus, HighpassFilter, Limiter, Pedalboard, PeakFilter, Reverb

from common import AUDITION, HERE, KOKORO_DIR, OUT, f5_example_ref

KOKORO_DEFAULT = ["af_heart", "af_nicole", "bf_emma", "bf_isabella", "af_sky"]
REF_LINE = ("Analysis complete. I have reviewed every record available, "
            "and the result is certain. Shall I proceed, Master?")

# The Raphael timbre from character.md: clean low end, a little presence,
# a short room, a faint doubled voice, then a limiter.
FX = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=120),
    PeakFilter(cutoff_frequency_hz=4000, gain_db=2.5, q=0.8),
    Chorus(rate_hz=0.6, depth=0.12, centre_delay_ms=10, feedback=0.0, mix=0.15),
    Reverb(room_size=0.25, damping=0.6, wet_level=0.08, dry_level=0.92, width=0.6),
    Limiter(threshold_db=-1.0),
])


def save(dir_, i, wav, sr):
    dir_.mkdir(parents=True, exist_ok=True)
    wav = np.asarray(wav, dtype=np.float32)
    sf.write(dir_ / f"{i}_raw.wav", wav, sr)
    sf.write(dir_ / f"{i}_fx.wav", FX(wav[None, :], sr)[0], sr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kokoro", nargs="*", default=KOKORO_DEFAULT)
    args = ap.parse_args()
    root = OUT / "audition"
    refs = root / "_refs"
    refs.mkdir(parents=True, exist_ok=True)

    from kokoro_onnx import Kokoro
    kokoro = Kokoro(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin"))
    f5_refs = {"f5_example": f5_example_ref()}
    for v in args.kokoro:
        t0 = time.perf_counter()
        for i, line in enumerate(AUDITION, 1):
            wav, sr = kokoro.create(line, voice=v, speed=0.95, lang="en-us")
            save(root / f"kokoro_{v}", i, wav, sr)
        print(f"kokoro_{v}: {time.perf_counter() - t0:.1f}s for {len(AUDITION)} lines (CPU)")
        wav, sr = kokoro.create(REF_LINE, voice=v, speed=0.95, lang="en-us")
        ref = refs / f"{v}.wav"
        sf.write(ref, wav, sr)
        f5_refs[f"f5_{v}"] = (str(ref), REF_LINE)

    rec = HERE / "recordings"
    for wav in sorted(rec.glob("ref_*.wav")) if rec.exists() else []:
        txt = wav.with_suffix(".txt")
        if txt.exists():
            f5_refs[f"f5_{wav.stem[4:]}"] = (str(wav), txt.read_text(encoding="utf-8").strip())

    from f5_tts.api import F5TTS
    tts = F5TTS(model="F5TTS_v1_Base")
    for name, (ref, ref_text) in f5_refs.items():
        for i, line in enumerate(AUDITION, 1):
            wav, sr, _ = tts.infer(ref, ref_text, line, nfe_step=8, show_info=lambda *a: None)
            save(root / name, i, wav, sr)
        print(f"{name}: done")
    print(f"listen in {root}")


if __name__ == "__main__":
    main()
