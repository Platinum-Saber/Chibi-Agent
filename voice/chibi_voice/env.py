"""Process setup that has to happen before the model libraries import."""
from __future__ import annotations

import os


def configure(vcfg: dict) -> None:
    """Model downloads go to F: (HF_HOME); call before importing torch or the models."""
    if vcfg.get("hf_home"):
        os.environ.setdefault("HF_HOME", vcfg["hf_home"])
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


_patched = False


def patch_torchaudio() -> None:
    """torchaudio >= 2.9 loads audio through torchcodec, which needs FFmpeg shared DLLs
    this machine doesn't have. F5 only loads the WAV reference, so soundfile does it."""
    global _patched
    if _patched:
        return
    import soundfile as sf
    import torch
    import torchaudio

    def load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), sr

    torchaudio.load = load
    _patched = True
