"""Process setup that has to happen before the model libraries import."""
from __future__ import annotations

import contextlib
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


# What ctranslate2 (Whisper) needs from CUDA 12: cuBLAS and cuDNN 9 (runtime first: the others import it).
CUDA_DLLS = ("cudart64_12.dll", "cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll")


def cuda_dll_dirs() -> list[Path]:
    """Where those DLLs may be: torch's wheel first when F5 is installed, so Whisper and F5
    share one copy (Whisper on NVIDIA's wheels and F5 on torch's loaded cuBLAS, cuDNN and the
    runtime twice: +0.3-0.6 GB private, measured 2026-10-27); else NVIDIA's own wheels
    (nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-cuda-runtime-cu12: the shipped voice)."""
    import importlib.util

    dirs = []
    spec = importlib.util.find_spec("torch")
    if spec is not None and spec.origin is not None:
        dirs.append(Path(spec.origin).parent / "lib")
    spec = importlib.util.find_spec("nvidia")
    for root in (spec.submodule_search_locations or []) if spec else []:
        dirs += [Path(root) / pkg / "bin" for pkg in ("cuda_runtime", "cublas", "cudnn")]
    return [d for d in dirs if d.is_dir()]


def load_cuda_dlls() -> bool:
    """Load the CUDA DLLs Whisper needs without importing torch. `import torch` also maps
    torch_cuda, cuSPARSE, cuFFT, cuSOLVER and the rest of cuDNN, which Kokoro + Whisper never
    use: 0.6 GB more private and 0.3 GB more working set (measured 2026-10-25, memory relief).
    F5 imports torch itself later. False: a DLL wasn't found or failed to load (Whisper then
    runs on the CPU)."""
    import ctypes
    import logging

    dirs = cuda_dll_dirs()
    for d in dirs:  # cuDNN loads its sub-libraries (cudnn_ops64_9...) from these later
        with contextlib.suppress(OSError):
            os.add_dll_directory(str(d))
    try:
        for name in CUDA_DLLS:
            found = next((d / name for d in dirs if (d / name).exists()), None)
            if found is None:
                raise OSError(f"{name} not in {', '.join(map(str, dirs)) or 'any CUDA wheel'}")
            ctypes.WinDLL(str(found))
    except OSError as e:
        logging.getLogger(__name__).warning("CUDA DLLs for Whisper did not load: %s", e)
        return False
    return True


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
