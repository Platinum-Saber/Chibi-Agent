"""Fit an FX chain that gives a clean voice (voice_f) the sound of a processed one (voice_d).

Measured on the two clips (Kryo's picks, 2026-10-26): d has filled gaps (reverb), squeezed dynamics
(compression), a thin low end and a darker top. Grid-search compressor + reverb so processed f
matches d's level statistics, then a matching EQ (1/3-octave long-term spectrum ratio, +-10 dB).
Optional pitch shift: d sits ~2 semitones above f.

  .venv\\Scripts\\python fit_fx.py [clean.wav] [target.wav]

Writes ChibiAgent/voice/fit_fx/: fx.json (the fitted chain), eq_db.csv, and
voice_f_{fx,fx_pitch}.wav plus the target for A/B. CPU only; Raphael untouched.
"""
import itertools
import json
import shutil
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from pedalboard import Compressor, HighpassFilter, Limiter, LowpassFilter, Pedalboard, PitchShift, Reverb
from scipy.signal import fftconvolve, firwin2

SR = 24000
P = Path(r"C:\Users\User\Music\Ringing Tones")
OUT = Path(r"D:\Projects\Chibi-Agent-Project\ChibiAgent\voice\fit_fx")
BANDS = np.geomspace(80, 10000, 22)


def load(p: Path) -> np.ndarray:
    y, sr = sf.read(p, dtype="float32", always_2d=True)
    y = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=SR)
    return y / max(1e-6, np.abs(y).max()) * 0.89


def level_stats(y: np.ndarray) -> np.ndarray:
    """Gap fill and dynamics over the spoken span: 10th/50th percentile and spread of the level, dB re 95th."""
    db = 20 * np.log10(librosa.feature.rms(y=y, frame_length=512, hop_length=128)[0] + 1e-9)
    on = np.flatnonzero(db > db.max() - 30)
    db = db[on[0]:on[-1] + 1]
    db -= np.percentile(db, 95)
    return np.array([np.percentile(db, 10), np.percentile(db, 50), db.std()])


def ltas_db(y: np.ndarray) -> np.ndarray:
    S = np.abs(librosa.stft(y, n_fft=2048)) ** 2
    rms = librosa.feature.rms(S=np.sqrt(S))[0]
    lt = S[:, rms > 0.05 * rms.max()].mean(axis=1)
    fr = librosa.fft_frequencies(sr=SR, n_fft=2048)
    return np.array([10 * np.log10(lt[(fr > c / 2 ** (1 / 6)) & (fr < c * 2 ** (1 / 6))].mean() + 1e-12) for c in BANDS])


def chain(thr, ratio, room, wet) -> Pedalboard:
    return Pedalboard([Compressor(threshold_db=thr, ratio=ratio, attack_ms=5, release_ms=80),
                       Reverb(room_size=room, damping=0.5, wet_level=wet, dry_level=1.0 - wet / 2, width=0.0)])


def eq_fir(target: np.ndarray, got: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = target - got
    d -= np.median(d)
    d = np.clip(np.convolve(d, [0.25, 0.5, 0.25], mode="same"), -10, 10)
    freqs = np.concatenate([[0], BANDS, [SR / 2]])
    return firwin2(1025, freqs, 10 ** (np.concatenate([[d[0]], d, [d[-1]]]) / 20), fs=SR), d


def apply(y, fx, fir):
    y = fx(y[None, :], SR)[0]
    y = fftconvolve(y, fir)[512:512 + len(y)]
    y = Limiter(threshold_db=-1.0)(y[None, :].astype(np.float32), SR)[0]
    return y / max(1e-6, np.abs(y).max()) * 0.89


def main() -> None:
    clean = Path(sys.argv[1]) if len(sys.argv) > 1 else P / "voice_f.wav"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else P / "voice_d.wav"
    f, d = load(clean), load(target)
    want = level_stats(d)
    print(f"target level stats (p10, p50, spread dB): {np.round(want, 1)};  clean: {np.round(level_stats(f), 1)}")
    best = None
    for thr, ratio, room, wet in itertools.product([-24, -18, -12, -6], [1, 2, 4], [0.5, 0.7, 0.85, 0.95], [0.2, 0.3, 0.4, 0.5, 0.6]):
        got = level_stats(chain(thr, ratio, room, wet)(f[None, :], SR)[0])
        err = float(np.abs(got - want) @ [1.0, 1.0, 1.5])
        if best is None or err < best[0]:
            best = (err, thr, ratio, room, wet, got)
    err, thr, ratio, room, wet, got = best
    print(f"fitted: compressor {thr} dB {ratio}:1, reverb room {room} wet {wet}  -> {np.round(got, 1)} (err {err:.1f})")
    fx = chain(thr, ratio, room, wet)
    pitch = float(np.clip(12 * np.log2(np.nanmedian(librosa.pyin(d, fmin=80, fmax=600, sr=SR)[0])
                                       / np.nanmedian(librosa.pyin(f, fmin=80, fmax=600, sr=SR)[0])), -4, 4))
    fir, eq = eq_fir(ltas_db(d), ltas_db(fx(f[None, :], SR)[0]))
    print("eq dB: " + " ".join(f"{c:.0f}:{g:+.0f}" for c, g in zip(BANDS, eq)))
    OUT.mkdir(parents=True, exist_ok=True)
    sf.write(OUT / "1_voice_f_fx.wav", apply(f, fx, fir), SR)
    sf.write(OUT / "2_voice_f_fx_pitch.wav", apply(PitchShift(semitones=pitch)(f[None, :], SR)[0], fx, fir), SR)
    shutil.copy(clean, OUT / "0_voice_f_clean.wav")
    shutil.copy(target, OUT / "3_voice_d_target.wav")
    (OUT / "fx.json").write_text(json.dumps({
        "compressor": {"threshold_db": thr, "ratio": ratio, "attack_ms": 5, "release_ms": 80},
        "reverb": {"room_size": room, "damping": 0.5, "wet_level": wet, "dry_level": 1.0 - wet / 2},
        "eq_bands_hz": [round(float(c)) for c in BANDS], "eq_db": [round(float(g), 1) for g in eq],
        "pitch_semitones": round(pitch, 2)}, indent=2), encoding="utf-8")
    print(f"pitch shift for the _pitch variant: {pitch:+.2f} st; listen in {OUT}")


if __name__ == "__main__":
    main()
