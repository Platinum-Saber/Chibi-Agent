"""Make a clean Kokoro voice sound like Raphael instead of cloning her noisy clips.

1. Measure her demucs'd lines (samples/refs/ref_*_vox.wav): median pitch, pitch spread (how flat
   she speaks), speaking rate, timbre (MFCC mean) and long-term spectrum.
2. Render the same transcripts with every English female Kokoro voice, score each against her,
   then try 50/50 and 70/30 blends of the best three (Kokoro voices are style vectors: mixable).
3. Close the rest with DSP: speed to her rate, pitch shift to her median, a matching EQ
   (her long-term spectrum / the voice's, 1/3-octave smoothed, +-8 dB), then the character.md
   Raphael FX chain at two strengths.

Output (outside git): ChibiAgent/voice/tune_kokoro/
  scores.csv, raphael_style.npy (the blend), eq_db.csv
  <n>_<line>/{0_her_ref?, 1_bf_emma_now, 2_best_raw, 3_matched, 4_matched_fx, 5_matched_inner}.wav
CPU only, no playback; the running Raphael is untouched.
Run with the spike venv:  .venv\\Scripts\\python tune_kokoro.py
"""
import csv
import ctypes
import itertools
import shutil
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from pedalboard import (Chorus, Delay, HighpassFilter, Limiter, Pedalboard, PeakFilter, PitchShift, Reverb)
from scipy.signal import fftconvolve, firwin2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "voice"))
from chibi_voice.tts import calm, speakable  # noqa: E402

from common import KOKORO_DIR  # noqa: E402

REFS = HERE / "samples" / "refs"
OUT = Path(r"D:\Projects\Chibi-Agent-Project\ChibiAgent\voice\tune_kokoro")
SR = 24000
FMIN, FMAX = 120.0, 500.0
BANDS = np.geomspace(100, 10000, 21)  # 1/3-octave-ish centres for the matching EQ

LINES = [
    "Notice. Master, you have a new message.",
    "Answer. The capital of Australia is Canberra, not Sydney.",
    "Understood. Opening the file now.",
    "Warning. Your battery is below ten percent.",
    "Report. Two events today, one deadline on Friday. End of report.",
    "Understood, Sir. There are 3.5 hours until the next meeting at 10:30.",
]
FX = {  # docs/character.md -> Voice 5, light; and a stronger "inner voice"
    "fx": Pedalboard([HighpassFilter(120), PeakFilter(4000, 2.5, 0.8),
                      Chorus(rate_hz=0.6, depth=0.12, centre_delay_ms=10, feedback=0.0, mix=0.12),
                      Reverb(room_size=0.25, damping=0.6, wet_level=0.08, dry_level=0.92, width=0.6),
                      Limiter(-1.0)]),
    "inner": Pedalboard([HighpassFilter(140), PeakFilter(4000, 3.0, 0.8),
                         Delay(delay_seconds=0.012, feedback=0.0, mix=0.18),
                         Chorus(rate_hz=0.4, depth=0.2, centre_delay_ms=8, feedback=0.0, mix=0.2),
                         Reverb(room_size=0.45, damping=0.5, wet_level=0.16, dry_level=0.88, width=0.9),
                         Limiter(-1.0)]),
}


def load(p: Path) -> np.ndarray:
    y, sr = sf.read(p, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    return librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y


def features(ys: list[np.ndarray], texts: list[str]) -> dict:
    f0s, mfccs, specs, rate = [], [], [], []
    for y, text in zip(ys, texts):
        f0, voiced, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=SR, frame_length=1024)
        f0 = f0[voiced & ~np.isnan(f0)]
        f0s.append(12 * np.log2(f0 / 440.0))  # semitones re A4
        m = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=20)
        rms = librosa.feature.rms(y=y)[0][: m.shape[1]]
        loud = rms > 0.1 * rms.max()
        mfccs.append(m[1:, loud].mean(axis=1))
        S = np.abs(librosa.stft(y, n_fft=2048)) ** 2
        specs.append(S[:, rms[: S.shape[1]] > 0.1 * rms.max()].mean(axis=1))
        speech = loud.sum() * 512 / SR
        rate.append(sum(c.isalpha() for c in text) / max(speech, 0.1))
    st = np.concatenate(f0s)
    return {"f0": float(np.median(st)), "spread": float(np.std(st)), "rate": float(np.mean(rate)),
            "mfcc": np.mean(mfccs, axis=0), "spec": np.mean(specs, axis=0)}


def distance(a: dict, b: dict) -> float:
    """Semitones of pitch, semitones of pitch spread, timbre (MFCC distance / 20) and rate."""
    return (abs(a["f0"] - b["f0"]) + abs(a["spread"] - b["spread"])
            + np.linalg.norm(a["mfcc"] - b["mfcc"]) / 20 + 3 * abs(np.log(a["rate"] / b["rate"])))


def band_db(spec: np.ndarray) -> np.ndarray:
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    out = []
    for c in BANDS:
        sel = (freqs > c / 2 ** (1 / 6)) & (freqs < c * 2 ** (1 / 6))
        out.append(10 * np.log10(spec[sel].mean() + 1e-12))
    return np.array(out)


def match_eq(her: dict, voice: dict) -> tuple[np.ndarray, np.ndarray]:
    """Linear-phase FIR that bends the voice's long-term spectrum toward hers (level-matched)."""
    d = band_db(her["spec"]) - band_db(voice["spec"])
    d -= np.median(d)
    d = np.clip(np.convolve(d, [0.25, 0.5, 0.25], mode="same"), -8, 8)
    freqs = np.concatenate([[0], BANDS, [SR / 2]])
    gains = 10 ** (np.concatenate([[d[0]], d, [d[-1]]]) / 20)
    return firwin2(1025, freqs, gains, fs=SR), d


def main() -> None:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    from kokoro_onnx import Kokoro
    k = Kokoro(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin"))
    refs = sorted(REFS.glob("ref_*_vox.wav"))
    texts = [(REFS / f"{p.stem[:6]}.txt").read_text(encoding="utf-8").strip() for p in refs]
    her = features([load(p) for p in refs], texts)
    print(f"her: pitch {her['f0']:+.1f} st re A4 ({440 * 2 ** (her['f0'] / 12):.0f} Hz), "
          f"spread {her['spread']:.2f} st, {her['rate']:.1f} letters/s")

    probe = texts[:4]  # four of her own lines, so content matches

    def measure(style, speed=1.0):
        ys = [k.create(calm(speakable(t)), voice=style, speed=speed, lang="en-us")[0] for t in probe]
        return features(ys, probe)

    names = [v for v in k.get_voices() if v[:2] in ("af", "bf")]
    scores = {}
    for v in names:
        f = measure(v)
        scores[v] = (distance(her, f), f)
        print(f"  {v:12s} d={scores[v][0]:.2f} pitch {f['f0']:+.1f} spread {f['spread']:.2f} rate {f['rate']:.1f}")
    top = sorted(scores, key=lambda v: scores[v][0])[:3]
    styles = {v: k.get_voice_style(v) for v in top}
    for a, b in itertools.combinations(top, 2):
        for w in (0.5, 0.7):
            name = f"{a}*{w:g}+{b}*{1 - w:g}"
            styles[name] = w * styles[a] + (1 - w) * styles[b]
            f = measure(styles[name])
            scores[name] = (distance(her, f), f)
            print(f"  {name:28s} d={scores[name][0]:.2f} pitch {f['f0']:+.1f} spread {f['spread']:.2f}")
    best = min(styles, key=lambda v: scores[v][0])
    style = styles[best]
    bf = scores[best][1]
    speed = float(np.clip(her["rate"] / bf["rate"], 0.8, 1.2))
    shift = float(np.clip(her["f0"] - bf["f0"], -3, 3))
    matched = measure(style, speed)
    fir, eq_db = match_eq(her, matched)
    print(f"best: {best} (d={scores[best][0]:.2f}); speed {speed:.2f}, pitch {shift:+.2f} st")

    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "raphael_style.npy", style)
    with open(OUT / "scores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["voice", "distance", "pitch_st", "spread_st", "letters_per_s"])
        w.writerow(["HER", 0, f"{her['f0']:.2f}", f"{her['spread']:.2f}", f"{her['rate']:.2f}"])
        for v, (d, ft) in sorted(scores.items(), key=lambda kv: kv[1][0]):
            w.writerow([v, f"{d:.3f}", f"{ft['f0']:.2f}", f"{ft['spread']:.2f}", f"{ft['rate']:.2f}"])
    with open(OUT / "eq_db.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("hz", "db"), *[(f"{c:.0f}", f"{g:+.1f}") for c, g in zip(BANDS, eq_db)]])

    pitch = Pedalboard([PitchShift(semitones=shift)]) if abs(shift) >= 0.3 else None
    for i, line in enumerate(LINES, 1):
        d = OUT / f"{i}_{line.split('.')[0].split(',')[0].lower()}"
        d.mkdir(exist_ok=True)
        text = calm(speakable(line))
        sf.write(d / "1_bf_emma_now.wav", k.create(text, voice="bf_emma", speed=1.0, lang="en-us")[0], SR)
        sf.write(d / "2_best_raw.wav", k.create(text, voice=style, speed=1.0, lang="en-us")[0], SR)
        y = k.create(text, voice=style, speed=speed, lang="en-us")[0].astype(np.float32)
        if pitch is not None:
            y = pitch(y[None, :], SR)[0]
        y = fftconvolve(y, fir)[512:512 + len(y)].astype(np.float32)
        y *= 0.89 / max(1e-6, np.abs(y).max())
        sf.write(d / "3_matched.wav", y, SR)
        for n, (tag, fx) in enumerate(FX.items(), 4):
            sf.write(d / f"{n}_matched_{tag}.wav", fx(y[None, :], SR)[0], SR)
    for p in refs[:3]:  # her, for A/B
        shutil.copy(p, OUT / f"0_her_{p.stem}.wav")
    print(f"listen in {OUT}")


if __name__ == "__main__":
    main()
