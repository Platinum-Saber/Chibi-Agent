"""PowerShell commands, shown in full and confirmed first. No elevation, no deleting."""
from __future__ import annotations

import re
import subprocess

from . import Result, tool

BLOCKED = re.compile(
    r"(?ix)\b(remove-item|rm|rmdir|del|erase|rd|format-volume|clear-disk|remove-partition|"
    r"stop-computer|restart-computer|reg\s+delete|bcdedit|cipher\s+/w|clear-recyclebin|"
    r"emptyrecyclebin|shemptyrecyclebin)\b|-verb\s+runas|sudo\b")


@tool("run_shell", "Run PowerShell (not cmd syntax).",
      {"command": ("The full command line", True)},
      side_effect=True, summary=lambda a: f"Run: {a.get('command')}", timeout_s=35)
def run_shell(command: str) -> Result:
    if BLOCKED.search(command):
        return Result("That command deletes data, needs elevation or shuts the PC down; "
                      "that ability has not been granted in this version.")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                           capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Result("The command ran longer than 30 s and was stopped.")
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
    return Result(f"exit code {p.returncode}\n{out.strip()}", untrusted=True)
