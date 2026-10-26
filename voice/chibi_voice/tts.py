"""Her voice: F5-TTS cloned from a reference clip (default voice_f, NFE 8, speed 0.90), or one
of Kokoro's preset voices (kokoro-onnx on the CPU, chosen in the Customize window). One
sentence per call."""
from __future__ import annotations

import contextlib
import gc
import io
import logging
import re
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL = "F5TTS_v1_Base"
RENDER = "tail1"  # how lines are rendered (short-line room below); part of the clip cache key

# F5 sizes a line by its bytes against the reference's (s/byte), with no slack, so short lines
# ("Let's dance.", "Hello, Saber.") lost their last sound (Saber, 2026-10-26). Lines under
# SHORT_S get TAIL_S more room; the silence that leaves is trimmed (keeping TAIL_KEEP_S).
SHORT_S = 2.5
TAIL_S = 0.5  # 0.35 still clipped the "s" of "Let's dance." a little
TAIL_KEEP_S = 0.12


def trim_tail(wav: np.ndarray, sr: int, floor_db: float = -45.0) -> np.ndarray:
    """Drop trailing silence below `floor_db` (re the peak), keeping TAIL_KEEP_S of it."""
    hop = max(1, int(sr * 0.01))
    if len(wav) < hop:
        return wav
    frames = np.sqrt(np.mean(wav[: len(wav) // hop * hop].reshape(-1, hop) ** 2, axis=1))
    loud = np.flatnonzero(frames > np.abs(wav).max() * 10 ** (floor_db / 20))
    if not len(loud):
        return wav
    return wav[: min(len(wav), (loud[-1] + 1) * hop + int(sr * TAIL_KEEP_S))]


_CALM = [(re.compile(r"[!?]*!+[!?]*"), lambda m: "?" if "?" in m.group() else "."),
         (re.compile(r"\.{2,}|…"), lambda m: "."), (re.compile(r"\s+"), lambda m: " ")]


def calm(text: str) -> str:
    """Raphael speaks evenly: F5 reads '!' as excitement (pitch jumps, a smeared ending
    in the voice audition), so exclamations become full stops before synthesis."""
    for pat, rep in _CALM:
        text = pat.sub(rep, text)
    return text.strip()


def _clock(m: re.Match) -> str:
    h, mm = m.group(1), m.group(2)
    return f"{h} o'clock" if mm == "00" else f"{h} oh {mm[1]}" if mm[0] == "0" else f"{h} {mm}"


def _money(m: re.Match) -> str:
    whole, cents = m.group(1), int(m.group(2))
    s = f"{whole} dollar{'' if whole == '1' else 's'}"
    return f"{s} {cents} cent{'' if cents == 1 else 's'}" if cents else s


def _point(m: re.Match) -> str:
    return m.group(1) + "".join(" point " + " ".join(part) for part in m.group(2).split(".")[1:])


_SPEAK = [(re.compile(r"\$(\d[\d,]*)\.(\d\d)\b"), _money),           # $4.99 -> 4 dollars 99 cents
          (re.compile(r"\b(\d{1,2}):(\d\d)\b"), _clock),               # 10:30 -> 10 30, 9:05 -> 9 oh 5
          (re.compile(r"(\d[\d,]*)((?:\.\d+)+)"), _point)]             # 3.14 -> 3 point 1 4, 2.1.3 too


def speakable(text: str) -> str:
    """Numbers as they're said. Both engines read the '.' in 3.5 as a full stop ("three. five",
    Kokoro's phonemes show it) and the ':' in 10:30 as a break; integers, 1,200 and 50% are fine."""
    for pat, rep in _SPEAK:
        text = pat.sub(rep, text)
    return text


class TtsUnloaded(RuntimeError):
    pass


class _NoProgress:
    """Stands in for the `tqdm` module F5 takes as `progress`, without the progress bars."""

    @staticmethod
    def tqdm(*args, **kwargs):
        from tqdm import tqdm
        return tqdm(*args, **{**kwargs, "disable": True})


KOKORO = "kokoro-v1.0"


def reference_text(wav: Path) -> str:
    """The transcript beside a reference clip: same stem .txt, else the stem without its last
    `_suffix` (ref_06_clean.wav -> ref_06.txt)."""
    for cand in (wav.with_suffix(".txt"), wav.with_name(wav.stem.rsplit("_", 1)[0] + ".txt")):
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"no transcript .txt beside {wav}")


class Tts:
    def __init__(self, vcfg: dict):
        self.default_ref = str(Path(vcfg["reference"]))
        self.default_ref_text = Path(vcfg["reference_text"]).read_text(encoding="utf-8").strip()
        self.ref, self.ref_text = self.default_ref, self.default_ref_text
        self.speed = float(vcfg.get("speed", 0.90))
        self.nfe = int(vcfg.get("nfe", 8))
        self.kokoro_dir = Path(vcfg.get("kokoro_dir", "")) if vcfg.get("kokoro_dir") else None
        self.f5_on = bool(vcfg.get("f5", True))  # config [voice] f5 = false: Kokoro speaks, F5 never loads
        self.engine = "f5" if self.f5_on else "kokoro"
        self.kvoice = "bf_emma"
        if not self.f5_on:
            self.speed = 1.0  # config's 0.90 is F5's; it drags in Kokoro
        self.model = None   # F5
        self.kokoro = None  # kokoro_onnx.Kokoro

    def tune(self, engine: str, voice: str, speed: float, nfe: int) -> None:
        """Switch voice; the caller (re)loads afterwards. Unknown files leave the old voice.
        With F5 off in config.toml, an F5 choice (saved or from Customize) becomes Kokoro."""
        if engine == "f5" and not self.f5_on:
            engine, voice, speed = "kokoro", "", max(float(speed), 1.0)
        if engine == "kokoro":
            self.kvoice = voice or self.kvoice
        else:
            if voice and Path(voice).exists():
                self.ref_text = reference_text(Path(voice))
                self.ref = str(Path(voice))
            elif not voice:
                self.ref, self.ref_text = self.default_ref, self.default_ref_text
        self.engine = engine
        self.speed = min(2.0, max(0.5, float(speed)))
        self.nfe = min(64, max(4, int(nfe)))

    def voice_key(self) -> str:
        """Identifies the voice for the clip cache (changing it re-renders the fixed lines)."""
        from .clips import voice_id
        if self.engine == "kokoro":
            return f"{KOKORO}:{self.kvoice}:{self.speed:g}"
        return voice_id(Path(self.ref), self.ref_text, self.speed, self.nfe, f"{MODEL}+{RENDER}")

    @property
    def loaded(self) -> bool:
        return (self.kokoro if self.engine == "kokoro" else self.model) is not None

    def load(self) -> None:
        if self.engine == "kokoro":
            self._load_kokoro()
            return
        if self.kokoro is not None:  # back to her own voice: drop Kokoro's ~0.3 GB
            self.kokoro = None
            gc.collect()
        if self.model is not None:
            return
        import torch

        from .env import patch_torchaudio
        patch_torchaudio()
        from f5_tts.api import F5TTS

        t0 = time.perf_counter()
        self.model = F5TTS(model=MODEL, device="cuda" if torch.cuda.is_available() else "cpu")
        # The first call also computes and caches the reference conditioning.
        self.synth("Warming up.")
        log.info("tts %s loaded in %.1fs", MODEL, time.perf_counter() - t0)

    def _load_kokoro(self) -> None:
        """Kokoro runs on the CPU (onnxruntime): F5's GPU memory is given back while it speaks."""
        if self.model is not None:
            self.unload_f5()
        if self.kokoro is not None:
            return
        if self.kokoro_dir is None:
            raise FileNotFoundError("config [voice] kokoro_dir is not set")
        from kokoro_onnx import Kokoro

        t0 = time.perf_counter()
        self.kokoro = Kokoro(str(self.kokoro_dir / f"{KOKORO}.onnx"), str(self.kokoro_dir / "voices-v1.0.bin"))
        log.info("tts %s loaded in %.1fs", KOKORO, time.perf_counter() - t0)

    def voices(self) -> list[str]:
        """Kokoro's voice ids (needs it loaded)."""
        return sorted(self.kokoro.get_voices()) if self.kokoro is not None else []

    def unload_f5(self) -> None:
        if self.model is None:
            return
        import torch

        self.model = None
        gc.collect()
        torch.cuda.empty_cache()
        log.info("tts %s unloaded", MODEL)

    def unload(self) -> None:
        self.unload_f5()
        if self.kokoro is not None:
            self.kokoro = None
            gc.collect()
            log.info("tts %s unloaded", KOKORO)

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        if self.engine == "kokoro":
            k = self.kokoro
            if k is None:
                raise TtsUnloaded("tts is unloaded")
            samples, sr = k.create(calm(speakable(text)), voice=self.kvoice, speed=self.speed, lang="en-us")
            return np.asarray(samples, dtype=np.float32), int(sr)
        model = self.model
        if model is None:
            raise TtsUnloaded("tts is unloaded")
        text = calm(speakable(text))
        # F5 print()s the reference and the text on every call; keep that out of the log.
        # (Logging holds its own stream, so log lines from other threads still get through.)
        with contextlib.redirect_stdout(io.StringIO()):
            fix = self._fix_duration(text)
            wav, sr, _ = model.infer(self.ref, self.ref_text, text, nfe_step=self.nfe,
                                     speed=self.speed, show_info=lambda *a, **k: None,
                                     progress=_NoProgress, fix_duration=fix)
        wav = np.asarray(wav, dtype=np.float32)
        return (trim_tail(wav, int(sr)) if fix is not None else wav), int(sr)

    def _fix_duration(self, text: str) -> float | None:
        """F5's total length (reference + line) with room for a short line's last sound, or None
        to let F5 size it. Mirrors F5's own estimate (f5_tts infer_batch_process), measured on
        the reference as F5 prepares it (cached by F5)."""
        n = len(text.encode("utf-8"))
        if n < 10:
            return None  # F5 already slows very short lines to 0.3x: they have room
        from f5_tts.infer.utils_infer import preprocess_ref_audio_text
        import soundfile as sf
        ref, ref_text = preprocess_ref_audio_text(self.ref, self.ref_text, show_info=lambda *a, **k: None)
        ref_s = sf.info(ref).duration
        est = ref_s / len(ref_text.encode("utf-8")) * n / self.speed
        return ref_s + est + TAIL_S if est < SHORT_S else None
