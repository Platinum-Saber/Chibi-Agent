"""F5-TTS in her voice (ref_06, NFE 8, speed 0.90, raw). One sentence per call."""
from __future__ import annotations

import contextlib
import gc
import io
import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL = "F5TTS_v1_Base"


class TtsUnloaded(RuntimeError):
    pass


class _NoProgress:
    """Stands in for the `tqdm` module F5 takes as `progress`, without the progress bars."""

    @staticmethod
    def tqdm(*args, **kwargs):
        from tqdm import tqdm
        return tqdm(*args, **{**kwargs, "disable": True})


class Tts:
    def __init__(self, vcfg: dict):
        self.ref = str(Path(vcfg["reference"]))
        self.ref_text = Path(vcfg["reference_text"]).read_text(encoding="utf-8").strip()
        self.speed = float(vcfg.get("speed", 0.90))
        self.nfe = int(vcfg.get("nfe", 8))
        self.model = None

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:
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

    def unload(self) -> None:
        if self.model is None:
            return
        import torch

        self.model = None
        gc.collect()
        torch.cuda.empty_cache()
        log.info("tts unloaded")

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        model = self.model
        if model is None:
            raise TtsUnloaded("tts is unloaded")
        # F5 print()s the reference and the text on every call; keep that out of the log.
        # (Logging holds its own stream, so log lines from other threads still get through.)
        with contextlib.redirect_stdout(io.StringIO()):
            wav, sr, _ = model.infer(self.ref, self.ref_text, text, nfe_step=self.nfe,
                                     speed=self.speed, show_info=lambda *a, **k: None,
                                     progress=_NoProgress)
        return np.asarray(wav, dtype=np.float32), int(sr)
