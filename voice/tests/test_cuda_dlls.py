"""Whisper's CUDA DLLs come from NVIDIA's or torch's wheels without importing torch (memory: ~0.6 GB private)."""
import subprocess
import sys

from chibi_voice import env


def test_cuda_dlls_load_without_importing_torch():
    # A fresh interpreter: this test process may already have torch from another test.
    code = ("import sys; from chibi_voice.env import load_cuda_dlls; ok = load_cuda_dlls(); "
            "import ctranslate2; print(ok, 'torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["True", "False"], out.stderr


def test_no_cuda_wheel_means_cpu(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert env.cuda_dll_dirs() == [] and env.load_cuda_dlls() is False


def test_torch_comes_first_so_whisper_and_f5_share_one_copy(monkeypatch, tmp_path):
    from types import SimpleNamespace
    nv, torch = tmp_path / "nvidia", tmp_path / "torch"
    for d in (nv / "cublas" / "bin", nv / "cudnn" / "bin", torch / "lib"):
        d.mkdir(parents=True)
    specs = {"nvidia": SimpleNamespace(submodule_search_locations=[str(nv)], origin=None),
             "torch": SimpleNamespace(submodule_search_locations=None, origin=str(torch / "__init__.py"))}
    monkeypatch.setattr("importlib.util.find_spec", specs.get)
    assert env.cuda_dll_dirs() == [torch / "lib", nv / "cublas" / "bin", nv / "cudnn" / "bin"]
    specs["torch"] = None  # the shipped voice: no torch, NVIDIA's wheels only
    assert env.cuda_dll_dirs() == [nv / "cublas" / "bin", nv / "cudnn" / "bin"]
