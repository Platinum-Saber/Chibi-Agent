"""Keep only Great Sage/Raphael's lines, merge them into 6-10 s clips, rank by cleanliness.

Speaker filter: resemblyzer embeddings compared with a seed centroid built from the
opening of the compilation (0-57 s, all skill announcements). Cleanliness: speech
level vs. the noise floor in the gaps right around the clip (music/SFX raise it).

Usage: python pick_refs.py samples/compilation.wav [--top 8]
Writes samples/refs/ref_NN.wav + .txt and samples/refs/index.tsv
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from resemblyzer import VoiceEncoder, preprocess_wav

SEED = (0.0, 57.5)
MIN_SIM = 0.80


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    y, sr = sf.read(a.wav, dtype="float32")
    segs = json.loads(Path(a.wav.replace(".wav", "_segments.json")).read_text(encoding="utf-8"))
    enc = VoiceEncoder("cpu")

    def emb(s, e):
        return enc.embed_utterance(preprocess_wav(y[int(s * sr):int(e * sr)], source_sr=sr))

    seed = [s for s in segs if s["start"] >= SEED[0] and s["end"] <= SEED[1] and s["end"] - s["start"] > 1.5]
    centroid = np.mean([emb(s["start"], s["end"]) for s in seed], axis=0)
    centroid /= np.linalg.norm(centroid)
    for s in segs:
        s["sim"] = float(emb(s["start"], s["end"]) @ centroid) if s["end"] - s["start"] > 0.6 else 0.0
    sage = [s for s in segs if s["sim"] >= MIN_SIM and s["logprob"] > -0.6 and s["no_speech"] < 0.3]
    print(f"{len(sage)}/{len(segs)} segments look like her "
          f"({sum(s['end'] - s['start'] for s in sage) / 60:.1f} min)")

    # merge neighbours (gap <= 0.8 s) into 6-10 s clips
    clips, cur = [], []
    for s in sage:
        if cur and (s["start"] - cur[-1]["end"] > 0.8 or s["end"] - cur[0]["start"] > 10.0):
            clips.append(cur)
            cur = []
        cur.append(s)
    if cur:
        clips.append(cur)
    cands = []
    for c in clips:
        st, en = c[0]["start"], c[-1]["end"]
        if not 6.0 <= en - st <= 10.0:
            continue
        speech = y[int(st * sr):int(en * sr)]
        pad = np.concatenate([y[max(0, int((st - .5) * sr)):int((st - .05) * sr)],
                              y[int((en + .05) * sr):int((en + .5) * sr)]])
        snr = rms_db(speech) - rms_db(pad) if len(pad) else 0
        cands.append(dict(start=st, end=en, text=" ".join(x["text"] for x in c),
                          sim=float(np.mean([x["sim"] for x in c])), snr=snr))
    cands.sort(key=lambda c: (c["snr"] + 40 * c["sim"]), reverse=True)
    out = Path(a.wav).parent / "refs"
    out.mkdir(exist_ok=True)
    with open(out / "index.tsv", "w", encoding="utf-8") as idx:
        idx.write("ref\tstart\tend\tsim\tsnr_db\ttext\n")
        for i, c in enumerate(cands[:a.top], 1):
            seg = y[int((c["start"] - .05) * sr):int((c["end"] + .15) * sr)]
            sf.write(out / f"ref_{i:02d}.wav", seg, sr)
            (out / f"ref_{i:02d}.txt").write_text(c["text"], encoding="utf-8")
            line = f"ref_{i:02d}\t{c['start']:.1f}\t{c['end']:.1f}\t{c['sim']:.2f}\t{c['snr']:.1f}\t{c['text']}"
            idx.write(line + "\n")
            print(line)
    print(f"{len(cands)} candidate clips of 6-10 s")


if __name__ == "__main__":
    main()
