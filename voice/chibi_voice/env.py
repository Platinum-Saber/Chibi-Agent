"""Process setup that has to happen before the model libraries import."""
from __future__ import annotations

import os
from pathlib import Path

# The Hub repos her models load from (F5, its vocoder, Whisper as "Systran/faster-whisper-<size>").
HUB_REPOS = ["SWivid/F5-TTS", "charactr/vocos-mel-24khz"]


def cached(hf_home: str, repos: list[str]) -> bool:
    """Every repo already has a snapshot in HF_HOME's hub cache."""
    hub = Path(hf_home) / "hub"
    return all(any((hub / f"models--{r.replace('/', '--')}" / "snapshots").glob("*")) for r in repos)


def configure(vcfg: dict) -> None:
    """Model downloads go to HF_HOME; call before importing torch or the models.
    Once every model is cached the Hub goes offline: its per-file HEAD checks cost ~20 s of
    a cold start and fail without internet. A missing model leaves it online to download."""
    if vcfg.get("hf_home"):
        os.environ.setdefault("HF_HOME", vcfg["hf_home"])
        repos = HUB_REPOS + [f"Systran/faster-whisper-{vcfg.get('stt_model', 'small.en')}"]
        if cached(vcfg["hf_home"], repos):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
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
