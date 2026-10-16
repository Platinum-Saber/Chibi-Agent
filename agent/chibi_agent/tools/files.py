"""Find, open, move, copy and rename files. No deleting in v1, and nothing outside
the allowed roots (config [tools].allowed_roots, default: the user profile)."""
from __future__ import annotations

import fnmatch
import os
import shutil
import time
from pathlib import Path

from . import Result, tool

ALLOWED_ROOTS: list[Path] = [Path.home()]
SEARCH_ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive"]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "AppData", "$RECYCLE.BIN"}


def configure(cfg: dict) -> None:
    roots = cfg.get("allowed_roots")
    if roots:
        ALLOWED_ROOTS[:] = [Path(os.path.expandvars(os.path.expanduser(r))).resolve() for r in roots]


def _allowed(p: Path) -> Path:
    rp = Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()
    if not any(rp == r or r in rp.parents for r in ALLOWED_ROOTS):
        raise PermissionError(f"{rp} is outside the folders I may touch.")
    return rp


def _index_search(query: str, folder: Path | None, limit: int) -> list[Path] | None:
    """Windows Search index (fast); None if unavailable."""
    try:
        import win32com.client
    except ImportError:
        return None
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        q = query.replace("'", "''")
        scope = f" AND SCOPE='file:{folder}'" if folder else ""
        rs, _ = conn.Execute(
            f"SELECT TOP {limit} System.ItemPathDisplay FROM SystemIndex "
            f"WHERE System.FileName LIKE '%{q}%'{scope} ORDER BY System.DateModified DESC")
        out = []
        while not rs.EOF:
            out.append(Path(rs.Fields.Item("System.ItemPathDisplay").Value))
            rs.MoveNext()
        conn.Close()
        return out
    except Exception:
        return None


def _walk_search(query: str, roots: list[Path], limit: int, budget_s: float = 4.0) -> list[Path]:
    pat = query.lower()
    glob = any(c in pat for c in "*?")
    hits: list[tuple[float, Path]] = []
    t0 = time.monotonic()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                fl = f.lower()
                if (fnmatch.fnmatch(fl, pat) if glob else pat in fl):
                    p = Path(dirpath, f)
                    try:
                        hits.append((p.stat().st_mtime, p))
                    except OSError:
                        pass
            if time.monotonic() - t0 > budget_s:
                break
    return [p for _, p in sorted(hits, reverse=True)[:limit]]


@tool("search_files", "Find files by name, newest first.",
      {"query": ("Part of the file name, e.g. 'resume' or '*.pdf'", True),
       "folder": ("Optional folder to search in", False)})
def search_files(query: str, folder: str = "") -> Result:
    base = _allowed(Path(folder)) if folder else None
    hits = None if "*" in query or "?" in query else _index_search(query, base, 15)
    if not hits:  # unavailable, or the folder isn't indexed

        roots = [base] if base else [p for p in (Path.home() / r for r in SEARCH_ROOTS) if p.exists()]
        hits = _walk_search(query, roots, 15)
    hits = [h for h in hits if any(r in h.parents for r in ALLOWED_ROOTS)]
    if not hits:
        return Result(f"No files found matching '{query}'.")
    return Result("\n".join(str(h) for h in hits), untrusted=True)


@tool("open_path", "Open a file or folder.",
      {"path": ("Full path", True)}, side_effect=True,
      summary=lambda a: f"Open {Path(a.get('path', '')).name or a.get('path')}")
def open_path(path: str) -> Result:
    p = _allowed(Path(path))
    if not p.exists():
        return Result(f"{p} does not exist.")
    os.startfile(p)  # noqa: S606 (confirmed by the user)
    return Result(f"Opened {p}.")


def _target(source: Path, destination: str) -> Path:
    d = _allowed(Path(destination))
    return d / source.name if d.is_dir() else d


@tool("move_file", "Move or rename a file or folder.",
      {"source": ("Current full path", True), "destination": ("New full path or a folder", True)},
      side_effect=True, summary=lambda a: f"Move {a.get('source')} to {a.get('destination')}")
def move_file(source: str, destination: str) -> Result:
    s = _allowed(Path(source))
    if not s.exists():
        return Result(f"{s} does not exist.")
    t = _target(s, destination)
    if t.exists():
        return Result(f"{t} already exists; I will not overwrite it.")
    shutil.move(str(s), str(t))
    return Result(f"Moved to {t}.")


@tool("copy_file", "Copy a file or folder.",
      {"source": ("Full path", True), "destination": ("New full path or a folder", True)},
      side_effect=True, summary=lambda a: f"Copy {a.get('source')} to {a.get('destination')}")
def copy_file(source: str, destination: str) -> Result:
    s = _allowed(Path(source))
    if not s.exists():
        return Result(f"{s} does not exist.")
    t = _target(s, destination)
    if t.exists():
        return Result(f"{t} already exists; I will not overwrite it.")
    (shutil.copytree if s.is_dir() else shutil.copy2)(str(s), str(t))
    return Result(f"Copied to {t}.")
