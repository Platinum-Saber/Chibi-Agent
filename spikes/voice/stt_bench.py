"""faster-whisper latency, VRAM and word error rate: small.en vs distil-large-v3, CUDA vs CPU.

Inputs: out/tts_*.wav (made by tts_bench.py, transcript known) and any
recordings/<name>.wav with a matching recordings/<name>.txt.

Usage: python stt_bench.py [--runs 5]
"""
import argparse
import csv
import gc
import statistics

import jiwer
import soundfile as sf
import torch

from common import AUDITION, HERE, OUT, Timer, vram_used_mb

MODELS = ["small.en", "distil-large-v3"]
DEVICES = [("cuda", "int8_float16"), ("cpu", "int8")]


def clips():
    # Whole audition lines (made by audition.py) in two different voices.
    for voice in ("f5_example", "kokoro_bf_emma"):
        for i, text in enumerate(AUDITION, 1):
            wav = OUT / "audition" / voice / f"{i}_raw.wav"
            if wav.exists():
                yield f"{voice}_{i}", wav, text
    rec = HERE / "recordings"
    for wav in sorted(rec.glob("*.wav")) if rec.exists() else []:
        txt = wav.with_suffix(".txt")
        if txt.exists():
            yield wav.stem, wav, txt.read_text(encoding="utf-8").strip()


def load16k(path):
    # Decode ourselves: faster-whisper's PyAV path breaks on the installed av version,
    # and the real app feeds it 16 kHz mono buffers from the mic anyway.
    import torchaudio.functional as AF
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = torch.from_numpy(data.mean(axis=1))
    return AF.resample(mono, sr, 16000).numpy() if sr != 16000 else mono.numpy()


def norm(s: str) -> str:
    return jiwer.RemovePunctuation()(s.lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    from faster_whisper import WhisperModel

    inputs = [(n, load16k(w), r, sf.info(str(w)).duration) for n, w, r in clips()]
    rows = []
    for model_name in MODELS:
        for device, ctype in DEVICES:
            base = vram_used_mb()
            with Timer() as t_load:
                m = WhisperModel(model_name, device=device, compute_type=ctype,
                                 cpu_threads=8)
            vram = vram_used_mb() - base if device == "cuda" else 0
            m.transcribe(inputs[0][1], language="en", beam_size=1)  # warm-up
            for name, wav, ref, dur in inputs:
                times, hyp = [], ""
                for _ in range(args.runs):
                    with Timer() as t:
                        segs, _ = m.transcribe(wav, language="en", beam_size=1,
                                               vad_filter=True)
                        hyp = " ".join(s.text for s in segs)
                    times.append(t.s)
                row = dict(model=model_name, device=device, clip=name, audio_s=round(dur, 2),
                           latency_s=round(statistics.median(times), 3),
                           wer=round(jiwer.wer(norm(ref), norm(hyp)), 3),
                           vram_mb=vram, load_s=round(t_load.s, 1))
                rows.append(row)
                print(row, "|", hyp.strip())
            del m
            gc.collect()
            torch.cuda.empty_cache()
    with open(OUT / "stt_bench.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
