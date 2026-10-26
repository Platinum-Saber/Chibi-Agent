"""Whisper's CUDA DLLs come from torch's wheel without importing torch (memory: ~0.6 GB private)."""
import subprocess
import sys

from chibi_voice import env


def test_cuda_dlls_load_without_importing_torch():
    # A fresh interpreter: this test process may already have torch from another test.
    code = ("import sys; from chibi_voice.env import load_cuda_dlls; ok = load_cuda_dlls(); "
            "import ctranslate2; print(ok, 'torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["True", "False"], out.stderr


def test_no_torch_wheel_means_cpu(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert env.load_cuda_dlls() is False
