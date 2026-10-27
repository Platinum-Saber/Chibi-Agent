"""Transcribe the compilation and list candidate reference clips.

Writes samples/segments.json: [{start, end, text, lang_prob, no_speech, logprob}, ...]
Usage: python segment.py samples/compilation.wav [--model distil-large-v3]
"""
import argparse
import json

import soundfile as sf
import torch  # noqa: F401
import torchaudio.functional as AF

import common  # noqa: F401  (env + DLLs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--model", default="distil-large-v3")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    y, sr = sf.read(a.wav, dtype="float32")
    y16 = AF.resample(torch.from_numpy(y), sr, 16000).numpy()
    m = WhisperModel(a.model, device="cuda", compute_type="int8_float16")
    segs, info = m.transcribe(y16, beam_size=5, vad_filter=True, word_timestamps=True,
                              vad_parameters={"min_silence_duration_ms": 400},
                              condition_on_previous_text=False)
    print(f"language {info.language} p={info.language_probability:.2f}, {info.duration:.0f}s")
    out = []
    for s in segs:
        out.append(dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip(),
                        no_speech=round(s.no_speech_prob, 3), logprob=round(s.avg_logprob, 3),
                        words=[(round(w.start, 2), round(w.end, 2), w.word, round(w.probability, 2))
                               for w in (s.words or [])]))
    with open(a.wav.replace(".wav", "_segments.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"{len(out)} segments")
    for s in out[:40]:
        print(f"{s['start']:7.1f}-{s['end']:7.1f} {s['text']}")


if __name__ == "__main__":
    main()
