"""Raphael.exe: start Raphael from the app folder (the install folder, or the repo).

First run (or after an update) it runs packaging/setup.ps1 in a console window, which builds the
Python environments and downloads her models; then it starts the agent, which starts Ollama,
the overlay and the voice. The agent keeps a single instance (mutex), so a second launch is
harmless. Built into Raphael.exe by packaging/build.ps1 (PyInstaller, --noconsole).
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

PACKAGES = ("agent", "overlay", "voice")
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NEW_CONSOLE = 0x00000010


def app_dir() -> Path:
    if getattr(sys, "frozen", False):  # Raphael.exe sits in the app folder
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def version(root: Path) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


def marker(ver: str) -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "ChibiAgent" / f"setup-{ver}.done"


def needs_setup(root: Path) -> bool:
    venvs_ok = all((root / p / ".venv" / "Scripts" / "python.exe").exists() for p in PACKAGES)
    return not venvs_ok or not marker(version(root)).exists()


def message(text: str, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Raphael", 0x10 if error else 0x40)


def run_setup(root: Path) -> bool:
    script = root / "packaging" / "setup.ps1"
    if not script.exists():
        message(f"Setup script missing:\n{script}", error=True)
        return False
    code = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                           cwd=root, creationflags=NEW_CONSOLE)
    return code == 0


def start_agent(root: Path) -> None:
    pyw = root / "agent" / ".venv" / "Scripts" / "pythonw.exe"
    subprocess.Popen([str(pyw), "-m", "chibi_agent"], cwd=root / "agent", creationflags=DETACHED,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    root = app_dir()
    if needs_setup(root) and not run_setup(root):
        message("Raphael's setup did not finish. See %LOCALAPPDATA%\ChibiAgent\logs\setup.log, "
                "then start Raphael again.", error=True)
        return 1
    start_agent(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
