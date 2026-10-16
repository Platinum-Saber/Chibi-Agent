"""F5-TTS speed on this GPU: first sentence, whole line, real-time factor, VRAM.

Usage: python tts_bench.py [--ref WAV --ref-text TEXT] [--runs 5]
"""
import argparse
import csv
import re
import statistics

import soundfile as sf

from common import LINES, OUT, Timer, f5_example_ref, vram_used_mb


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref")
    ap.add_argument("--ref-text")
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    ref, ref_text = (args.ref, args.ref_text) if args.ref else f5_example_ref()

    base = vram_used_mb()
    from f5_tts.api import F5TTS

    with Timer() as t_load:
        tts = F5TTS(model="F5TTS_v1_Base")
    loaded = vram_used_mb()
    print(f"load {t_load.s:.1f}s, VRAM +{loaded - base} MB")

    def say(text, nfe):
        # F5's preprocess caches the reference conditioning after the first call.
        wav, sr, _ = tts.infer(ref, ref_text, text, nfe_step=nfe, show_info=lambda *a: None)
        return wav, sr

    say("Warming up.", 8)
    rows, peak = [], loaded
    for nfe in (8, 16):
        for name, line in LINES.items():
            firsts, totals, rtfs = [], [], []
            for _ in range(args.runs):
                parts = sentences(line)
                with Timer() as t1:
                    wav0, sr = say(parts[0], nfe)
                total_audio = len(wav0) / sr
                with Timer() as trest:
                    for p in parts[1:]:
                        w, _ = say(p, nfe)
                        total_audio += len(w) / sr
                total = t1.s + trest.s
                firsts.append(t1.s)
                totals.append(total)
                rtfs.append(total_audio / total)
                peak = max(peak, vram_used_mb())
            sf.write(OUT / f"tts_{name}_nfe{nfe}.wav", wav0, sr)
            row = dict(nfe=nfe, line=name, first_s=statistics.median(firsts),
                       total_s=statistics.median(totals), x_realtime=statistics.median(rtfs))
            rows.append(row)
            print(row)
    with open(OUT / "tts_bench.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"peak VRAM over baseline: {peak - base} MB (baseline {base} MB)")


if __name__ == "__main__":
    main()
