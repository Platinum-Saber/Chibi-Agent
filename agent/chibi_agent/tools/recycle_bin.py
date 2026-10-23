"""The Recycle Bin through Windows' Shell (namespace 10): see what's in it, open it, restore an
item. Emptying it deletes files for good, which v1 doesn't do (scope.md): she opens the bin and
Kryo empties it himself."""
from __future__ import annotations

import os

from . import Result, tool

BIN = 10  # ShellSpecialFolderConstants.ssfBITBUCKET
# Details columns of a Recycle Bin item (Windows 10/11): original location, date deleted, size
COL_FROM, COL_DELETED, COL_SIZE = 1, 2, 3


def _shell():
    import win32com.client  # pywin32, as files._index_search uses
    return win32com.client.Dispatch("Shell.Application")


def _clean(s) -> str:
    """Explorer wraps dates in invisible left-to-right marks; drop them."""
    return str(s or "").replace("‎", "").replace("‏", "")


def items(shell=None) -> list[dict]:
    """Name, original folder, date deleted, size (text) and bytes of each item in the bin."""
    ns = (shell or _shell()).Namespace(BIN)
    out = []
    for it in ns.Items():
        try:
            size_b = int(it.Size)
        except (TypeError, ValueError, AttributeError):
            size_b = 0
        col = lambda c: _clean(ns.GetDetailsOf(it, c))  # noqa: E731
        out.append({"name": it.Name, "from": col(COL_FROM),
                    "deleted": col(COL_DELETED), "size": col(COL_SIZE),
                    "bytes": size_b, "item": it})
    return out


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@tool("recycle_bin", "List the Recycle Bin.")
def recycle_bin(shell=None) -> Result:
    try:
        rows = items(shell)
    except Exception as e:  # COM unavailable
        return Result(f"I couldn't read the Recycle Bin: {e}", failed=True)
    if not rows:
        return Result("The Recycle Bin is empty.")
    total = sum(r["bytes"] for r in rows)
    lines = [f"{r['name']}  {r['size']}  from {r['from']}  deleted {r['deleted']}" for r in rows[:40]]
    more = f"\n... and {len(rows) - 40} more" if len(rows) > 40 else ""
    return Result(f"{len(rows)} items, {_human(total)} in all:\n" + "\n".join(lines) + more +
                  "\n(I can open the bin or restore an item; emptying it is for Kryo.)", untrusted=True)


@tool("recycle_bin_action", "Open the Recycle Bin, or restore an item.",
      {"action": ("open or restore", True), "name": ("Item name, for restore", False)},
      side_effect=True,
      summary=lambda a: "Open the Recycle Bin" if (a.get("action") or "").lower() == "open"
      else f"Restore '{a.get('name')}' from the Recycle Bin")
def recycle_bin_action(action: str, name: str = "", shell=None) -> Result:
    action = (action or "").lower()
    if action == "open":
        os.startfile("shell:RecycleBinFolder")  # noqa: S606 (confirmed by Kryo)
        return Result("Opened the Recycle Bin. Kryo can empty it from there.")
    if action != "restore":
        return Result("Use action 'open' or 'restore'. Emptying the bin is for Kryo to do.")
    if not name:
        return Result("Which item? Give its name from the Recycle Bin list.")
    rows = items(shell)
    match = [r for r in rows if r["name"].lower() == name.lower()] or \
            [r for r in rows if name.lower() in r["name"].lower()]
    if not match:
        return Result(f"Nothing called '{name}' is in the Recycle Bin.")
    if len(match) > 1:
        return Result("Several items match: " + ", ".join(r["name"] for r in match[:8]) + ". Which one?")
    it = match[0]["item"]
    for verb in it.Verbs():  # the "Restore" verb (its text is localised; English "R&estore")
        if "restore" in verb.Name.replace("&", "").lower():
            verb.DoIt()
            return Result(f"Restored {match[0]['name']} to {match[0]['from']}.")
    return Result(f"Windows offered no Restore for {match[0]['name']}.", failed=True)
