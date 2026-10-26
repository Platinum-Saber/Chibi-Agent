"""Memory relief (docs/architecture.md -> Memory relief): when physical RAM stays above the
threshold (70 %), she works out who holds it and gives some back, cheapest and safest first:

1. her own stack: F5 in the voice process (~3 GB private) once she hasn't spoken for a while,
   and her Ollama model (keep_alive 0) once no turn is under way;
2. working-set trims of idle background apps (low value: the pages fault back in);
3. the largest idle app with a window: she names it and offers to close it through the
   confirmation gate. A yes posts WM_CLOSE (the app handles unsaved work itself); nothing is
   ever killed.

System processes, other users' processes, the Claude app, the foreground app and her own
processes are never trimmed or offered. The standby list is never purged: it already counts
as available, and purging it needs admin rights.

Hysteresis: two samples in a row at or above the threshold make RAM "high"; it stays high until
it drops below threshold - hysteresis. While high she intervenes at most once per cooldown.

`python -m chibi_agent.memrelief --once --dry-run` runs one pass against this PC and logs every
decision without touching anything (the running Raphael included).
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import time
from collections import defaultdict
from ctypes import wintypes
from dataclasses import dataclass

import psutil

from chibi_shared.protocol import Bubble, Hud, Load, MoodReq

from .tools import Result, Tool

log = logging.getLogger(__name__)
MB = 2**20

# Never trimmed or offered, whatever they hold (lower-case exe names).
SYSTEM = frozenset(n.lower() for n in (
    "System", "Idle", "Registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "MsMpEng.exe", "MpDefenderCoreService.exe",
    "NisSrv.exe", "SecurityHealthService.exe", "MemCompression", "Memory Compression", "explorer.exe",
    "sihost.exe", "ctfmon.exe", "fontdrvhost.exe", "audiodg.exe", "SearchHost.exe", "SearchIndexer.exe",
    "StartMenuExperienceHost.exe", "ShellExperienceHost.exe", "RuntimeBroker.exe", "TextInputHost.exe",
    "WmiPrvSE.exe", "spoolsv.exe", "taskhostw.exe", "dllhost.exe", "conhost.exe", "WUDFHost.exe",
    "NVDisplay.Container.exe", "nvcontainer.exe", "NVIDIA Overlay.exe", "nvsphelper64.exe",
    "LockApp.exe", "SystemSettings.exe", "smartscreen.exe", "Widgets.exe", "WidgetService.exe"))

CLOSE_TOOL = Tool(
    "close_app", "Close an idle app to free memory.", {"app": ("App", True), "size": ("Memory it holds", True)},
    fn=lambda **_: Result(""), side_effect=True, confirm=True,
    summary=lambda a: f"Close {a.get('app')} to free about {a.get('size')}", timeout_s=10)


@dataclass
class Proc:
    pid: int
    name: str
    exe: str = ""
    cmd: str = ""
    ppid: int = 0
    private_mb: float = 0.0
    ws_mb: float = 0.0
    cpu_s: float = 0.0
    mine: bool = True  # runs as Kryo; other users' and SYSTEM's processes are skipped


# --- the PC ---------------------------------------------------------------------
def ram_percent() -> float:
    return psutil.virtual_memory().percent


def available_mb() -> float:
    return psutil.virtual_memory().available / MB


def snapshot() -> dict[int, Proc]:
    try:
        me = psutil.Process().username()
    except psutil.Error:
        me = None
    out = {}
    for p in psutil.process_iter(["name", "exe", "cmdline", "ppid", "username", "memory_info", "cpu_times"]):
        i = p.info
        mi, ct = i.get("memory_info"), i.get("cpu_times")
        out[p.pid] = Proc(p.pid, i.get("name") or "", i.get("exe") or "", " ".join(i.get("cmdline") or [])[:300],
                          i.get("ppid") or 0, getattr(mi, "private", 0) / MB if mi else 0.0,
                          mi.rss / MB if mi else 0.0, (ct.user + ct.system) if ct else 0.0,
                          me is not None and i.get("username") == me)
    return out


def window_pids() -> dict[int, list[int]]:
    """pid -> its visible, titled top-level windows."""
    user32 = ctypes.windll.user32
    out: dict[int, list[int]] = defaultdict(list)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out[pid.value].append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return dict(out)


def foreground_pid() -> int:
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def trim(pid: int) -> bool:
    """EmptyWorkingSet: the pages move to the standby/modified lists. No admin rights needed
    for Saber's own processes; anything else is access denied and left alone."""
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000 | 0x0100, False, pid)  # QUERY_LIMITED_INFORMATION | SET_QUOTA
    if not h:
        return False
    try:
        return bool(ctypes.windll.psapi.EmptyWorkingSet(wintypes.HANDLE(h)))
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


def close_windows(hwnds: list[int]) -> None:
    for hwnd in hwnds:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: the app handles unsaved work


def saved_engine() -> str:
    """"f5" or "kokoro": the voice the Customize window last chose (voice/chibi_voice/main.py
    LAST_VOICE); config.toml's F5 when there is none."""
    import json

    from chibi_shared import paths
    try:
        return json.loads((paths.LOCAL / "voice_tune.json").read_text(encoding="utf-8")).get("engine", "f5")
    except (OSError, ValueError):
        return "f5"


def ws_mb(pid: int) -> float | None:
    try:
        return psutil.Process(pid).memory_info().rss / MB
    except psutil.Error:
        return None


# --- who may be touched ---------------------------------------------------------------
def _descendants(procs: dict[int, Proc], roots: set[int]) -> set[int]:
    kids: dict[int, list[int]] = defaultdict(list)
    for p in procs.values():
        if p.ppid != p.pid:
            kids[p.ppid].append(p.pid)
    out, todo = set(roots), list(roots)
    while todo:
        for k in kids.get(todo.pop(), ()):
            if k not in out:
                out.add(k)
                todo.append(k)
    return out


def own_stack(procs: dict[int, Proc], me: int | None = None) -> set[int]:
    """Her own processes (this agent, its children, the chibi_* pythons, Ollama, Godot):
    stage 1 handles them; stages 2 and 3 never touch them."""
    me = os.getpid() if me is None else me
    roots = {me}
    for p in procs.values():
        n, c = p.name.lower(), p.cmd.lower()
        if "chibi_" in c or "chibi.py" in c or n.startswith("ollama") or n.startswith("godot"):
            roots.add(p.pid)
    pid = procs[me].ppid if me in procs else 0
    while pid in procs and "python" in procs[pid].name.lower():  # chibi.py / uv launcher above us
        roots.add(pid)
        pid = procs[pid].ppid
    return _descendants(procs, roots)


def is_claude(p: Proc) -> bool:
    e = p.exe.lower()
    return p.name.lower() == "claude.exe" or "\\windowsapps\\claude_" in e or "anthropicclaude" in e


def protected(procs: dict[int, Proc], fg: int) -> dict[int, str]:
    """pid -> why it is never trimmed or offered."""
    why: dict[int, str] = {}
    for pid in _descendants(procs, {p.pid for p in procs.values() if is_claude(p)}):
        why[pid] = "Claude app"
    fg_name = procs[fg].name.lower() if fg in procs else None
    fg_roots = {p.pid for p in procs.values() if fg_name and p.name.lower() == fg_name}
    for pid in _descendants(procs, fg_roots):
        why.setdefault(pid, "foreground")
    for p in procs.values():
        if p.name.lower() in SYSTEM or p.pid <= 4:
            why.setdefault(p.pid, "system")
        elif not p.mine:
            why.setdefault(p.pid, "not Saber's")
    return why


def _gb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def _app(name: str) -> str:
    return name[:-4] if name.lower().endswith(".exe") else name


class MemoryRelief:
    def __init__(self, hub, llm, orch, vram, cfg: dict, *, dry_run: bool = False,
                 sample=ram_percent, available=available_mb, snap=snapshot, windows=window_pids,
                 foreground=foreground_pid, trim_fn=trim, close_fn=close_windows, ws=ws_mb,
                 sleep=asyncio.sleep, clock=time.monotonic, engine=None):
        self.hub, self.llm, self.orch, self.vram = hub, llm, orch, vram
        self.dry_run = dry_run
        self.threshold = float(cfg.get("threshold", 70))
        self.low = self.threshold - float(cfg.get("hysteresis", 5))
        self.interval_s = float(cfg.get("interval_s", 20))
        self.cooldown_s = float(cfg.get("cooldown_s", 600))
        self.voice_idle_s = float(cfg.get("voice_idle_s", 180))
        self.llm_idle_s = float(cfg.get("llm_idle_s", 60))
        self.own = bool(cfg.get("own_stack", True))
        self.trim_on = bool(cfg.get("trim_working_sets", True))
        self.trim_min_mb = float(cfg.get("trim_min_mb", 300))
        self.offer_on = bool(cfg.get("offer_close", True))
        self.embed_model = cfg.get("embed_model", "")  # main passes [ollama] embed_model
        self.close_min_mb = float(cfg.get("close_min_mb", 700))
        self.settle_s = float(cfg.get("settle_s", 5))   # also the window that decides "idle"
        self.idle_cpu = float(cfg.get("idle_cpu", 0.02))  # CPU seconds per second (2 % of a core)
        self.decline_quiet_s = float(cfg.get("decline_quiet_s", 3600))
        self.sample, self.available, self.snap, self.windows = sample, available, snap, windows
        self.foreground, self.trim_fn, self.close_fn, self.ws = foreground, trim_fn, close_fn, ws
        self.sleep, self.clock = sleep, clock
        self._engine = engine or saved_engine
        self.high = False
        self.above = 0
        self.last_run = float("-inf")
        self.tts_released_at: float | None = None  # F5 unloaded by us, not reloaded since
        self.declined: dict[str, float] = {}       # app -> when Kryo said no
        self._task: asyncio.Task | None = None

    # --- lifecycle -----------------------------------------------------------------
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="memrelief")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            await self.sleep(self.interval_s)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("memrelief: pass failed")

    # --- state ---------------------------------------------------------------------
    def _last_active(self) -> float:
        return getattr(self.orch, "last_active", float("-inf")) if self.orch is not None else float("-inf")

    def voice_engine(self) -> str:
        """The engine the Customize window chose (voice_tune.json, shared with the voice process)."""
        return self._engine() if self._engine else "f5"

    @property
    def tts_released(self) -> bool:
        """Unloaded by us and not spoken since (a reminder reloads F5 in the voice process)."""
        return self.tts_released_at is not None and self._last_active() <= self.tts_released_at

    async def on_ptt(self) -> None:
        """Saber is talking to her: bring her voice back while he speaks."""
        if self.tts_released:
            log.info("memrelief: PTT, reloading the voice model")
            self.tts_released_at = None
            await self.hub.send("voice", Load(t="load", what="tts"))

    async def tick(self) -> dict | None:
        pct = self.sample()
        if pct < self.threshold:
            self.above = 0
            if self.high and pct < self.low:
                log.info("memrelief: RAM %.0f%%, back under %.0f%%", pct, self.low)
                self.high = False
            return None
        self.above += 1
        if not self.high and self.above >= 2:
            log.info("memrelief: RAM %.0f%% (threshold %.0f%%)", pct, self.threshold)
            self.high = True
        if not self.high or self.clock() - self.last_run < self.cooldown_s:
            return None
        if self.orch is not None and self.orch.busy:
            return None  # mid-turn: try again on the next sample
        if self.vram is not None and self.vram.gaming:
            return None  # gaming mode already dropped her models
        self.last_run = self.clock()
        return await self.relieve(pct)

    # --- one intervention -------------------------------------------------------------
    async def relieve(self, pct: float) -> dict:
        avail0 = self.available()
        done: list[str] = []
        items: list[str] = []
        procs = self.snap()
        mine = own_stack(procs)
        top = sorted(procs.values(), key=lambda p: -p.private_mb)[:8]
        log.info("memrelief: RAM %.0f%%, %s available. Top private: %s", pct, _gb(avail0),
                 ", ".join(f"{p.name}[{p.pid}] {p.private_mb:.0f}" for p in top))

        # 1. her own stack
        targets: dict[int, float] = {}
        if self.own:
            idle = self.clock() - self._last_active()
            voice = [p for p in procs.values() if "chibi_voice" in p.cmd]
            if not voice:
                log.info("memrelief: [own] no voice process")
            elif self.voice_engine() != "f5":
                log.info("memrelief: [own] %s voice in use: F5 is not loaded. The voice process's %.0f MB "
                         "private is Whisper's CUDA stack (stays; its working set is trimmed below if idle)",
                         self.voice_engine(), sum(p.private_mb for p in voice))
            elif self.tts_released:
                log.info("memrelief: [own] voice model already unloaded")
            elif idle < self.voice_idle_s:
                log.info("memrelief: [own] voice active %.0fs ago (< %.0fs): keeping F5", idle, self.voice_idle_s)
            else:
                mb = sum(p.private_mb for p in voice)
                log.info("memrelief: [own] voice idle %s, process holds %.0f MB private: unloading F5%s",
                         "since start" if idle == float("inf") else f"{idle:.0f}s", mb, self._dry)
                if not self.dry_run:
                    await self.hub.send("voice", Load(t="unload", what="tts", reason="memory"))
                    self.tts_released_at = self.clock()
                targets.update({p.pid: p.private_mb for p in voice})
                done.append("unloaded my voice model")
            await self._llm_stage(idle, procs, targets, done)
            if targets and not self.dry_run:
                await self.sleep(self.settle_s)
                after = self.snap()
                for pid, before in targets.items():
                    now = after[pid].private_mb if pid in after else 0.0
                    log.info("memrelief: [own] %s[%d] private %.0f -> %.0f MB", procs[pid].name, pid, before, now)
                    if before - now >= 10:
                        items.append(f"{_app(procs[pid].name)}: {before:.0f} -> {now:.0f} MB")
                procs = after  # fresh numbers for the next stages
            pct = self.sample()
            if pct < self.low:
                return await self._finish(pct, avail0, done, items)

        # 2 and 3 need an idle window: CPU time over settle_s
        prev = procs
        await self.sleep(self.settle_s)
        procs = self.snap()
        fg = self.foreground()
        guard = protected(procs, fg)
        mine = own_stack(procs)
        window = max(self.settle_s, 1e-6)

        def idle_proc(p: Proc) -> bool:
            q = prev.get(p.pid)
            return q is not None and (p.cpu_s - q.cpu_s) / window <= self.idle_cpu

        free = [p for p in procs.values() if p.pid not in guard and p.pid not in mine]
        big_guarded = sorted((p for p in procs.values() if p.pid in guard and p.private_mb >= self.trim_min_mb),
                             key=lambda p: -p.private_mb)
        for p in big_guarded[:6]:
            log.info("memrelief: [skip] %s[%d] %.0f MB: %s", p.name, p.pid, p.private_mb, guard[p.pid])

        # 2. trim idle background working sets. Her voice process joins once she has been quiet
        # for voice_idle_s: its working set is mostly cuBLAS/CUDA DLL pages (file-backed, so
        # dropped without a pagefile write and soft-faulted back from standby at the next PTT).
        if self.trim_on:
            trimmed, total = 0, 0.0
            quiet = self.own and self.clock() - self._last_active() >= self.voice_idle_s
            voice = [p for p in procs.values() if quiet and "chibi_voice" in p.cmd]
            for p in sorted(free + voice, key=lambda p: -p.ws_mb):
                if p.ws_mb < self.trim_min_mb:
                    break
                if p not in voice and not idle_proc(p):  # her audio stream keeps the voice at ~3 % CPU
                    log.info("memrelief: [trim] %s[%d] ws %.0f MB busy: skipped", p.name, p.pid, p.ws_mb)
                    continue
                if self.dry_run:
                    log.info("memrelief: [trim] %s[%d] ws %.0f MB idle: would trim%s", p.name, p.pid, p.ws_mb, self._dry)
                    continue
                if not self.trim_fn(p.pid):
                    log.info("memrelief: [trim] %s[%d] access denied", p.name, p.pid)
                    continue
                now = self.ws(p.pid) or 0.0
                log.info("memrelief: [trim] %s[%d] ws %.0f -> %.0f MB", p.name, p.pid, p.ws_mb, now)
                trimmed += 1
                total += max(0.0, p.ws_mb - now)
            if trimmed:
                done.append(f"trimmed {trimmed} idle app{'s' if trimmed > 1 else ''}")
                items.append(f"Trimmed {trimmed}: {_gb(total)} of working set")
            pct = self.sample()
            if pct < self.low:
                return await self._finish(pct, avail0, done, items)

        # 3. offer to close the largest idle app with a window
        if self.offer_on:
            await self._offer(pct, procs, free, idle_proc, done, items)
            pct = self.sample()
        return await self._finish(pct, avail0, done, items)

    @property
    def _dry(self) -> str:
        return " (dry run)" if self.dry_run else ""

    async def _llm_stage(self, idle: float, procs: dict[int, Proc], targets: dict[int, float],
                         done: list[str]) -> None:
        """Her Ollama models: the chat model (keep_alive 120 s) and the embedding model, whose
        runner holds ~1.2 GB for its 30 min keep-alive. Both reload by themselves on the next turn."""
        try:
            loaded = await self.llm.loaded()
        except Exception as e:
            log.info("memrelief: [own] could not ask Ollama what is loaded: %s", e)
            return
        base = lambda n: n.removesuffix(":latest")  # noqa: E731
        names = {base(n.get("name", "")) for n in loaded}
        log.info("memrelief: [own] Ollama has loaded: %s", ", ".join(sorted(names)) or "nothing")
        mine = [(base(self.llm.model), "the language model")]
        if self.embed_model:
            mine.append((base(self.embed_model), "the embedding model"))
        for model, what in mine:
            if model not in names:
                continue
            if idle < self.llm_idle_s:
                log.info("memrelief: [own] last turn %.0fs ago (< %.0fs): keeping %s", idle, self.llm_idle_s, model)
                continue
            m = next(x for x in loaded if base(x.get("name", "")) == model)
            log.info("memrelief: [own] %s loaded (%.0f MB, %.0f MB in VRAM), idle: unloading (keep_alive 0)%s",
                     model, m.get("size", 0) / MB, m.get("size_vram", 0) / MB, self._dry)
            if not self.dry_run:
                if model == base(self.llm.model):
                    await self.llm.unload()
                else:
                    await self.llm.unload_embed(self.embed_model)
            done.append(f"unloaded {what}")
        if any(d.startswith("unloaded the") for d in done):
            targets.update({p.pid: p.private_mb for p in procs.values()
                            if p.name.lower().startswith(("ollama", "llama-server"))})

    async def _offer(self, pct: float, procs: dict[int, Proc], free: list[Proc], idle_proc,
                     done: list[str], items: list[str]) -> None:
        groups: dict[str, list[Proc]] = defaultdict(list)
        for p in free:
            groups[p.name].append(p)
        wins = self.windows()
        now = self.clock()
        cands = []
        for name, ps in groups.items():
            mb = sum(p.private_mb for p in ps)
            if mb < self.close_min_mb:
                continue
            hwnds = [h for p in ps for h in wins.get(p.pid, ())]
            if not hwnds:
                log.info("memrelief: [offer] %s %.0f MB has no window: not offered", name, mb)
            elif not all(idle_proc(p) for p in ps):
                log.info("memrelief: [offer] %s %.0f MB is busy: not offered", name, mb)
            elif now - self.declined.get(name, float("-inf")) < self.decline_quiet_s:
                log.info("memrelief: [offer] %s %.0f MB: Saber declined recently", name, mb)
            else:
                cands.append((mb, name, hwnds))
        if not cands:
            log.info("memrelief: [offer] no large idle app to offer")
            return
        mb, name, hwnds = max(cands)
        app = _app(name)
        question = f"{app} holds {_gb(mb)} and has been idle. Shall I close it, Sir?"
        log.info("memrelief: [offer] %s (%d windows): %s%s", name, len(hwnds), question, self._dry)
        if self.dry_run:
            return
        gate = getattr(getattr(self.orch, "runner", None), "gate", None)
        if gate is None:
            log.info("memrelief: [offer] no confirmation gate: not asking")
            return
        await self.hub.send("overlay", Bubble(text=f"Notice. Memory is at {pct:.0f} percent. {question}", done=True))
        await self._speak(["Notice.", f"Memory is at {pct:.0f} percent.", question])
        ok = await gate.ask(CLOSE_TOOL, {"app": app, "size": _gb(mb)})
        if not ok:
            log.info("memrelief: [offer] Saber declined (or no answer): %s stays", name)
            self.declined[name] = self.clock()
            return
        log.info("memrelief: [offer] Saber said yes: WM_CLOSE to %s", name)
        self.close_fn(hwnds)
        done.append(f"asked {app} to close")
        items.append(f"Closed {app}: {_gb(mb)}")

    async def _speak(self, sentences: list[str]) -> None:
        """Her own words, unless we just unloaded F5: then only the clip marker, so the report
        doesn't load the voice model straight back (the bubble has the full text)."""
        if self.orch is None:
            return
        for i, s in enumerate(sentences if not self.tts_released else sentences[:1]):
            await self.orch._say(s, first=i == 0)

    async def _finish(self, pct: float, avail0: float, done: list[str], items: list[str]) -> dict:
        freed = max(0.0, self.available() - avail0)
        report = {"done": done, "freed_mb": round(freed), "percent": pct, "items": items}
        log.info("memrelief: done: %s; %s freed, RAM now %.0f%%", "; ".join(done) or "nothing to release",
                 _gb(freed), pct)
        if not done or self.dry_run:
            return report  # nothing to say: the log has it
        line = f"I {', '.join(done[:-1]) + ' and ' + done[-1] if len(done) > 1 else done[0]}: " \
               f"about {_gb(freed)} freed. Memory is now at {pct:.0f} percent."
        await self.hub.send("overlay", MoodReq(mood="working", ttl_ms=6000))
        await self.hub.send("overlay", Hud(title="Memory relief", items=(items or done)[:6]))
        await self.hub.send("overlay", Bubble(text=f"Notice. {line}", done=True))
        await self._speak(["Notice.", line])
        asyncio.get_running_loop().call_later(12, lambda: asyncio.create_task(
            self.hub.send("overlay", Hud(title="", items=[]))))
        return report


# --- dry run on this PC -------------------------------------------------------------
class _LogHub:
    async def send(self, role, msg) -> bool:
        log.info("memrelief: (no hub here) would send %s %s", role, msg.model_dump(exclude={"id", "ts"}))
        return True


async def _main(args) -> None:
    from chibi_shared import config
    from .llm import Ollama

    cfg = config.load()
    mcfg = {"embed_model": cfg["ollama"].get("embed_model", ""), **cfg.get("memory_relief", {})}
    if args.threshold is not None:
        mcfg["threshold"] = args.threshold
    llm = Ollama(cfg["ollama"])
    relief = MemoryRelief(_LogHub(), llm, None, None, mcfg, dry_run=not args.act)
    if args.trim:  # real trims (low risk: pages fault back in); stage 1 and offers stay dry
        relief.dry_run = False
        relief.own = False
        relief.offer_on = False
    pct = relief.sample()
    log.info("memrelief: RAM %.1f%% (threshold %.0f%%, re-arm under %.0f%%); her activity unknown here: "
             "treated as idle", pct, relief.threshold, relief.low)
    if pct < relief.threshold and not args.force:
        log.info("memrelief: under the threshold: nothing to do (--force runs a pass anyway)")
    else:
        await relief.relieve(pct)
    await llm.close()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="chibi_agent.memrelief", description=__doc__.split("\n\n")[0])
    ap.add_argument("--once", action="store_true", help="one pass (the only mode)")
    ap.add_argument("--dry-run", action="store_true", default=True, help="log decisions, touch nothing (default)")
    ap.add_argument("--trim", action="store_true", help="really trim idle working sets (stage 2 only)")
    ap.add_argument("--act", action="store_true",
                    help="really act: unload her idle Ollama models, trim; offers are only logged (no gate here)")
    ap.add_argument("--force", action="store_true", help="run a pass even under the threshold")
    ap.add_argument("--threshold", type=float)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
