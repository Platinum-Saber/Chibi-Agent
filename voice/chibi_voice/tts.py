"""Her voice: F5-TTS cloned from a reference clip (default ref_06, NFE 8, speed 0.90), or one
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


_CALM = [(re.compile(r"[!?]*!+[!?]*"), lambda m: "?" if "?" in m.group() else "."),
         (re.compile(r"\.{2,}|…"), lambda m: "."), (re.compile(r"\s+"), lambda m: " ")]


def calm(text: str) -> str:
    """Raphael speaks evenly: F5 reads '!' as excitement (pitch jumps, a smeared ending
    in the voice audition), so exclamations become full stops before synthesis."""
    for pat, rep in _CALM:
        text = pat.sub(rep, text)
    return text.strip()


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
        self.engine = "f5"
        self.kvoice = "bf_emma"
        self.model = None   # F5
        self.kokoro = None  # kokoro_onnx.Kokoro

    def tune(self, engine: str, voice: str, speed: float, nfe: int) -> None:
        """Switch voice; the caller (re)loads afterwards. Unknown files leave the old voice."""
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
        return voice_id(Path(self.ref), self.ref_text, self.speed, self.nfe, MODEL)

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
            samples, sr = k.create(calm(text), voice=self.kvoice, speed=self.speed, lang="en-us")
            return np.asarray(samples, dtype=np.float32), int(sr)
        model = self.model
        if model is None:
            raise TtsUnloaded("tts is unloaded")
        text = calm(text)
        # F5 print()s the reference and the text on every call; keep that out of the log.
        # (Logging holds its own stream, so log lines from other threads still get through.)
        with contextlib.redirect_stdout(io.StringIO()):
            wav, sr, _ = model.infer(self.ref, self.ref_text, text, nfe_step=self.nfe,
                                     speed=self.speed, show_info=lambda *a, **k: None,
                                     progress=_NoProgress)
        return np.asarray(wav, dtype=np.float32), int(sr)
