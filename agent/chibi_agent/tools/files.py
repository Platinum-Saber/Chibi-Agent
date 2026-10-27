"""Find, search inside, list, read, open, create, move, copy and rename files. No deleting in
v1, and nothing outside the allowed roots (config [tools].allowed_roots, default: the user
profile)."""
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


# --- content search, listings, reading, creating --------------------------------------------------
GREP_MAX_BYTES = 2_000_000
GREP_HITS = 30


def _is_text(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return b"\0" not in f.read(4096)
    except OSError:
        return False


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@tool("grep_files", "Find text inside files.",
      {"text": ("The text to look for", True), "folder": ("Folder to search in", True),
       "pattern": ("Optional file-name filter, e.g. '*.py'", False)})
def grep_files(text: str, folder: str, pattern: str = "", budget_s: float = 5.0) -> Result:
    base = _allowed(Path(folder))
    if not base.is_dir():
        return Result(f"{base} is not a folder.")
    needle, pat = text.lower(), (pattern or "*").lower()
    hits: list[str] = []
    files_seen = 0
    t0 = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            if not fnmatch.fnmatch(f.lower(), pat):
                continue
            p = Path(dirpath, f)
            try:
                if p.stat().st_size > GREP_MAX_BYTES or not _is_text(p):
                    continue
                files_seen += 1
                with p.open(encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if needle in line.lower():
                            hits.append(f"{p}:{n}: {line.strip()[:160]}")
                            if len(hits) >= GREP_HITS:
                                break
            except OSError:
                continue
            if len(hits) >= GREP_HITS or time.monotonic() - t0 > budget_s:
                break
        if len(hits) >= GREP_HITS or time.monotonic() - t0 > budget_s:
            break
    if not hits:
        return Result(f"'{text}' was not found in {files_seen} files under {base}.")
    more = " (stopped at the limit)" if len(hits) >= GREP_HITS else ""
    return Result(f"{len(hits)} matches{more}:\n" + "\n".join(hits), untrusted=True)


def _tree_size(p: Path, deadline: float) -> int | None:
    """Total bytes under `p`, or None if the time ran out."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(p):
        for f in filenames:
            try:
                total += os.stat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
        if time.monotonic() > deadline:
            return None
    return total


@tool("list_folder", "List a folder, with sizes and dates.",
      {"folder": ("Full folder path", True), "sort": ("name, size or date", False)})
def list_folder(folder: str, sort: str = "name", budget_s: float = 6.0) -> Result:
    base = _allowed(Path(folder))
    if not base.is_dir():
        return Result(f"{base} is not a folder.")
    sort = (sort or "name").lower()
    deadline = time.monotonic() + budget_s
    rows = []
    for e in base.iterdir():
        try:
            st = e.stat()
        except OSError:
            continue
        size = st.st_size if e.is_file() else (_tree_size(e, deadline) if sort == "size" else None)
        rows.append((e.is_dir(), e.name, size, st.st_mtime))
    if sort == "size":
        rows.sort(key=lambda r: -(r[2] or 0))
    elif sort == "date":
        rows.sort(key=lambda r: -r[3])
    else:
        rows.sort(key=lambda r: (not r[0], r[1].lower()))
    lines = [f"{'[folder] ' if d else ''}{name}  {_human(s) if s is not None else ''}  "
             f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(m))}".replace("    ", "  ")
             for d, name, s, m in rows[:60]]
    more = f"\n... and {len(rows) - 60} more" if len(rows) > 60 else ""
    return Result(f"{base} ({len(rows)} items):\n" + "\n".join(lines) + more, untrusted=True)


@tool("read_file", "Read a text file.",
      {"path": ("Full file path", True), "lines": ("How many lines (default 60)", False)})
def read_file(path: str, lines: str = "60") -> Result:
    p = _allowed(Path(path))
    if not p.is_file():
        return Result(f"{p} is not a file.")
    if not _is_text(p):
        return Result(f"{p.name} is not a text file.")
    try:
        n = max(1, min(400, int(lines or 60)))
    except ValueError:
        n = 60
    out, size = [], 0
    with p.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= n or size > 8000:
                out.append("...")
                break
            out.append(line.rstrip("\n"))
            size += len(line)
    return Result(f"{p}:\n" + "\n".join(out), untrusted=True)


@tool("create_folder", "Create a folder.",
      {"path": ("Full path of the new folder", True)}, side_effect=True,
      summary=lambda a: f"Create folder {a.get('path')}")
def create_folder(path: str) -> Result:
    p = _allowed(Path(path))
    if p.exists():
        return Result(f"{p} already exists.")
    p.mkdir(parents=True)
    return Result(f"Created {p}.")


@tool("create_file", "Create a new text file.",
      {"path": ("Full path of the new file", True), "text": ("What to write in it", False)},
      side_effect=True, summary=lambda a: f"Create {a.get('path')} ({len(a.get('text') or '')} chars)")
def create_file(path: str, text: str = "") -> Result:
    p = _allowed(Path(path))
    if p.exists():
        return Result(f"{p} already exists; I will not overwrite it.")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x", encoding="utf-8") as fh:  # "x": fails if it appeared meanwhile
        fh.write(text or "")
    return Result(f"Created {p}.")
