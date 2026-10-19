"""Shared setup for the voice spike: model locations, timing and VRAM helpers."""
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", r"D:\Projects\Chibi-Agent-Project\ChibiAgent\hf")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import torch  # noqa: E402  (loads cuBLAS/cuDNN DLLs that ctranslate2 also needs)
import pynvml  # noqa: E402  (from nvidia-ml-py)
import soundfile as _sf  # noqa: E402
import torchaudio  # noqa: E402


def _load_with_soundfile(path, *args, **kwargs):
    # torchaudio >= 2.9 loads through torchcodec, which needs FFmpeg shared DLLs
    # this machine doesn't have. WAV/FLAC through soundfile is all we need.
    data, sr = _sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), sr


torchaudio.load = _load_with_soundfile

HERE = Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
KOKORO_DIR = Path(r"D:\Projects\Chibi-Agent-Project\ChibiAgent\models\kokoro")

pynvml.nvmlInit()
_gpu = pynvml.nvmlDeviceGetHandleByIndex(0)


def vram_used_mb() -> int:
    """Whole-GPU used memory, the same number nvidia-smi shows."""
    return pynvml.nvmlDeviceGetMemoryInfo(_gpu).used // (1024 * 1024)


class Timer:
    def __enter__(self):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self.s = time.perf_counter() - self.t0


def f5_example_ref() -> tuple[str, str]:
    """F5-TTS's bundled English reference clip and its transcript."""
    from importlib.resources import files
    wav = files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")
    return str(wav), "Some call me nature, others call me mother nature."


# Her chosen voice (docs/character.md -> Voice): ref_06, music removed, used raw.
RAPHAEL_SPEED = 0.90
RAPHAEL_NFE = 8


def raphael_ref() -> tuple[str, str]:
    refs = HERE / "samples" / "refs"
    return str(refs / "ref_06_vox.wav"), (refs / "ref_06.txt").read_text(encoding="utf-8")


LINES = {
    "short": "Notice. Your meeting starts in ten minutes.",
    "medium": "Answer. The file you asked about was last modified yesterday evening, "
              "and it is stored in your documents folder.",
    "long": "Report. You have two events today, three unread messages that look important, "
            "and one deadline on Friday. I recommend finishing the lab report first, "
            "since it carries the most weight. End of report.",
}

AUDITION = [
    "Notice. Master, you have a new message.",
    "Answer. The capital of Australia is Canberra, not Sydney.",
    "Understood. Opening the file now.",
    "Warning. Your battery is below ten percent.",
    "Report. Two events today, one deadline on Friday. End of report.",
]
