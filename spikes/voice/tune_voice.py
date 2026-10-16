"""Cleaner versions of her cloned voice: less echo and high-frequency noise, effect kept.

  base: as now (ref_06, raw)
  A:    output clean-up (gate the echo tails, soften 6-9 kHz hiss, gentle top cut)
  B:    cleaned reference (spectral noise reduction + EQ), re-cloned, raw output
  C:    B + A

Writes out/audition_tuned/<variant>/<n>.wav and samples/refs/ref_06_clean.wav.
Run with the voice venv:  ..\\..\\voice\\.venv\\Scripts\\python tune_voice.py
"""
import sys
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf
from pedalboard import (HighpassFilter, HighShelfFilter, Limiter, LowpassFilter, NoiseGate, Pedalboard,
                        PeakFilter)

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "voice"))
from chibi_shared import config  # noqa: E402
from chibi_voice.tts import Tts  # noqa: E402

LINES = [
    "Notice. Master, you have a new message.",
    "Answer. The capital of Australia is Canberra, not Sydney.",
    "Understood. Opening the file now.",
    "Warning! Master, your battery is critically low!",
    "Shall I proceed, Master? The analysis is complete, and the result is certain.",
    "Report. Two events today, one deadline on Friday. End of report.",
]

OUTPUT_FX = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=80),
    NoiseGate(threshold_db=-42, ratio=3.0, attack_ms=2, release_ms=140),  # trims echo tails/hiss between words
    PeakFilter(cutoff_frequency_hz=7000, gain_db=-4.0, q=1.2),           # harsh sibilance / hiss band
    HighShelfFilter(cutoff_frequency_hz=8500, gain_db=-5.0),
    LowpassFilter(cutoff_frequency_hz=10500),
    Limiter(threshold_db=-1.0),
])
REF_EQ = Pedalboard([HighpassFilter(cutoff_frequency_hz=80), PeakFilter(cutoff_frequency_hz=7000, gain_db=-3.0, q=1.0),
                     LowpassFilter(cutoff_frequency_hz=10000)])


def clean_reference(src: Path, dst: Path) -> None:
    y, sr = sf.read(src, dtype="float32")
    # Stationary noise profile from the quietest 10 % of frames; partial reduction keeps her timbre.
    y = nr.reduce_noise(y=y, sr=sr, stationary=True, prop_decrease=0.75, n_fft=1024)
    y = REF_EQ(y[None, :], sr)[0]
    sf.write(dst, y / max(1e-6, np.abs(y).max()) * 0.89, sr)


def main() -> None:
    vc = config.load()["voice"]
    ref, ref_txt = Path(vc["reference"]), vc["reference_text"]
    clean = HERE / "samples" / "refs" / "ref_06_clean.wav"
    clean_reference(ref, clean)
    out = HERE / "out" / "audition_tuned"
    for variant, ref_wav, fx in (("base", ref, None), ("A", ref, OUTPUT_FX),
                                 ("B", clean, None), ("C", clean, OUTPUT_FX)):
        tts = Tts({**vc, "reference": str(ref_wav), "reference_text": ref_txt})
        tts.load()
        d = out / variant
        d.mkdir(parents=True, exist_ok=True)
        for i, line in enumerate(LINES, 1):
            wav, sr = tts.synth(line)
            if fx is not None:
                wav = fx(wav[None, :], sr)[0]
            sf.write(d / f"{i}.wav", wav, sr)
        tts.unload()
        print(variant, "done")
    print("listen in", out)


if __name__ == "__main__":
    main()
