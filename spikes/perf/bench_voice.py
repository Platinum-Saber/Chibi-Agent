"""Voice benchmark: Whisper (STT), Kokoro and F5 in one process, as the voice process runs them.
  python bench_voice.py <label> <wheels|torch> <out.json>
wheels: Whisper's CUDA DLLs from NVIDIA's wheels (v0.1.1 as shipped); torch: from torch's lib."""
import json
import subprocess
import sys
import time
from pathlib import Path

label, order, out = sys.argv[1], sys.argv[2], sys.argv[3]
import os  # noqa: E402

PID = os.getpid()
R = {"label": label, "dll_order": order, "stages": {}}


def gpu_mem() -> dict:
    ps = (f"$c = Get-Counter '\\GPU Process Memory(pid_{PID}_*)\\Dedicated Usage','\\GPU Process Memory(pid_{PID}_*)\\Shared Usage' -ErrorAction SilentlyContinue;"
          "$d = ($c.CounterSamples | ? Path -match 'dedicated' | Measure-Object CookedValue -Sum).Sum;"
          "$s = ($c.CounterSamples | ? Path -match 'shared' | Measure-Object CookedValue -Sum).Sum;"
          "Write-Output ('{0} {1}' -f [math]::Round($d/1MB), [math]::Round($s/1MB))")
    d, s = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
    import ctypes
    import ctypes.wintypes as w

    class PMC(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return {"vram_mb": int(d), "shared_gpu_mb": int(s), "private_mb": pmc.PrivateUsage // 2**20,
            "working_set_mb": pmc.WorkingSetSize // 2**20}


def cuda_copies() -> dict:
    ps = (f"(Get-Process -Id {PID}).Modules | ? ModuleName -match '^(cublasLt64_12|cublas64_12|cudart64_12|cudnn64_9)\\.dll$' |"
          " % {{ $_.ModuleName + '|' + $_.FileName }}")
    lines = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.splitlines()
    copies: dict = {}
    for ln in lines:
        name, path = ln.split("|", 1)
        copies.setdefault(name, []).append(path.split("site-packages\\")[-1])
    return copies


def stage(name, **extra):
    R["stages"][name] = {**gpu_mem(), **extra}
    print(name, R["stages"][name], flush=True)


from chibi_shared import config  # noqa: E402
from chibi_voice import env  # noqa: E402

cfg = config.load()["voice"]
env.configure(cfg)
if order == "torch":  # the fix: torch's copy first when F5 (torch) is installed
    real = env.cuda_dll_dirs
    env.cuda_dll_dirs = lambda: sorted(real(), key=lambda d: 0 if d.parts[-2] == "torch" else 1)
stage("start")

import numpy as np  # noqa: E402

from chibi_voice.player import _resample  # noqa: E402
from chibi_voice.stt import SR, Stt  # noqa: E402
from chibi_voice.tts import Tts  # noqa: E402

t0 = time.perf_counter()
stt = Stt(cfg.get("stt_model", "small.en"))
stt.load("cuda")
stage("whisper_loaded", load_s=round(time.perf_counter() - t0, 2), device=stt.device)

kcfg = {**cfg, "f5": False}
kok = Tts(kcfg)
t0 = time.perf_counter()
kok.load()
k_load = time.perf_counter() - t0
lines = ["Answer. I have opened Spotify for you, Saber.",
         "Notice. You have two meetings this afternoon, the first at three.",
         "Confirmed. The file has been moved to your Documents folder."]
k = []
clips = []
for ln in lines:
    t0 = time.perf_counter()
    a, sr = kok.synth(ln)
    dt = time.perf_counter() - t0
    k.append({"text_chars": len(ln), "synth_s": round(dt, 3), "audio_s": round(len(a) / sr, 2), "rtf": round(dt / (len(a) / sr), 3)})
    clips.append(_resample(a, sr, SR))
stage("kokoro_loaded", load_s=round(k_load, 2), synth=k)

w = []
for c in clips:
    t0 = time.perf_counter()
    text = stt.transcribe(c)
    w.append({"audio_s": round(len(c) / SR, 2), "transcribe_s": round(time.perf_counter() - t0, 3), "text": text})
R["whisper"] = w
print("whisper", w, flush=True)

t0 = time.perf_counter()
import torch  # noqa: E402,F401
t_imp = time.perf_counter() - t0
f5 = Tts(cfg)
t0 = time.perf_counter()
f5.load()  # includes its warm-up sentence
stage("f5_loaded", torch_import_s=round(t_imp, 2), load_s=round(time.perf_counter() - t0, 2), engine=f5.engine)
f = []
for ln in lines:
    t0 = time.perf_counter()
    a, sr = f5.synth(ln)
    dt = time.perf_counter() - t0
    f.append({"text_chars": len(ln), "synth_s": round(dt, 3), "audio_s": round(len(a) / sr, 2), "rtf": round(dt / (len(a) / sr), 3)})
R["f5"] = f
print("f5", f, flush=True)
w2 = []
for c in clips:  # Whisper again, now beside F5
    t0 = time.perf_counter()
    stt.transcribe(c)
    w2.append(round(time.perf_counter() - t0, 3))
R["whisper_with_f5_loaded_s"] = w2
stage("all_loaded", cuda_copies=cuda_copies())
Path(out).write_text(json.dumps(R, indent=1), encoding="utf-8")
hold = float(sys.argv[4]) if len(sys.argv) > 4 else 0
if hold:  # keep F5 + Whisper resident while another benchmark runs beside it
    Path(out + ".ready").write_text("1")
    time.sleep(hold)
