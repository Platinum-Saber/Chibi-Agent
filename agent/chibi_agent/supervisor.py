"""Starts and watches the child processes: Ollama, the overlay and the voice process.

A child that exits on its own is restarted with backoff (1 s doubling to 30 s,
reset after it stays up for a minute). Ollama is only started if nothing answers
on its URL already, and only that child gets OLLAMA_MODELS.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from chibi_shared import paths

log = logging.getLogger(__name__)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)  # Ollama is shared: it may outlive us


@dataclass
class Child:
    name: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    proc: asyncio.subprocess.Process | None = None
    stopping: bool = False


class KillOnExitJob:
    """Puts the agent itself in a Windows job object. Every child it starts lands
    in the job too, so when the agent dies (even by TerminateProcess) Windows
    kills them all; in M3 an overlay outlived its agent. Adding children one by
    one doesn't work: the venv python.exe is a launcher that has already spawned
    the real interpreter by then."""

    def __init__(self):
        import win32api
        import win32job
        self._job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= (win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                                                        | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
        win32job.SetInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation, info)
        win32job.AssignProcessToJobObject(self._job, win32api.GetCurrentProcess())


def venv_python(package_dir: Path) -> Path:
    return package_dir / ".venv" / "Scripts" / "python.exe"


async def ollama_up(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            return (await c.get(f"{url}/api/version")).status_code == 200
    except httpx.HTTPError:
        return False


class Supervisor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.children: list[Child] = []
        self._tasks: list[asyncio.Task] = []
        try:
            self.job: KillOnExitJob | None = KillOnExitJob()
        except Exception as e:  # pragma: no cover
            log.warning("no job object (%s): children may outlive a crashed agent", e)
            self.job = None

    def plan(self) -> list[Child]:
        out = []
        oc = self.cfg.get("ollama", {})
        if oc.get("start_if_down", True):
            exe = os.path.expandvars(oc.get("exe", "ollama"))
            out.append(Child("ollama", [exe, "serve"],
                             env={"OLLAMA_MODELS": oc.get("models_dir", ""),
                                  "OLLAMA_FLASH_ATTENTION": "1"}))
        for name in ("overlay", "voice"):
            if not self.cfg.get("processes", {}).get(name, True):
                continue
            pkg = paths.REPO / name
            py = venv_python(pkg)
            if not py.exists():
                log.warning("%s: no venv at %s (run `uv sync` in %s); skipping", name, py, pkg)
                continue
            out.append(Child(name, [str(py), "-m", f"chibi_{name}"], cwd=pkg))
        return out

    async def start(self) -> None:
        for child in self.plan():
            if child.name == "ollama" and await ollama_up(self.cfg["ollama"]["url"]):
                log.info("ollama already running; not starting another")
                continue
            self.children.append(child)
            self._tasks.append(asyncio.create_task(self._keep_alive(child)))

    async def _spawn(self, child: Child) -> None:
        env = {**os.environ, **{k: v for k, v in child.env.items() if v}}
        logf = open(paths.LOGS / f"{child.name}.log", "ab")
        child.proc = await asyncio.create_subprocess_exec(
            *child.argv, cwd=child.cwd, env=env, stdout=logf, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW | (BREAKAWAY if child.name == "ollama" else 0))
        log.info("started %s (pid %d)", child.name, child.proc.pid)

    async def _keep_alive(self, child: Child) -> None:
        delay = 1.0
        while not child.stopping:
            started = time.monotonic()
            try:
                await self._spawn(child)
            except OSError as e:
                log.error("could not start %s: %s", child.name, e)
                return
            code = await child.proc.wait()
            if child.stopping:
                return
            if time.monotonic() - started > 60:
                delay = 1.0
            log.warning("%s exited with %s; restarting in %.0fs", child.name, code, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def stop(self, grace: float = 3.0) -> None:
        """Children were already sent `quit` over the hub; kill what's left after `grace`."""
        for c in self.children:
            c.stopping = True
        live = [c.proc for c in self.children if c.proc and c.proc.returncode is None]
        if live:
            await asyncio.wait([asyncio.create_task(p.wait()) for p in live], timeout=grace)
            for p in live:
                if p.returncode is None:
                    p.kill()
        for t in self._tasks:
            t.cancel()
