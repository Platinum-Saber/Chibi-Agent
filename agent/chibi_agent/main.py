"""Agent entry point: hub, supervisor, then (from M1) the orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from chibi_shared import config, paths
from chibi_shared.protocol import Quit

from . import tools
from .control import Controller
from .google_auth import GoogleAuth
from .hotkey import HoldHotkey
from .tools import files
from .tools.runner import Gate, Runner
from .llm import Ollama
from .memory import Memory
from .memory.store import Store
from .orchestrator import Orchestrator
from .schedulers import Reminders
from .vram import VramManager
from .server import Hub
from .supervisor import Supervisor

log = logging.getLogger("chibi_agent")


async def run(stop: asyncio.Event | None = None, without: list[str] = ()) -> None:
    paths.ensure()
    cfg = config.load()
    for name in without:
        cfg.setdefault("processes", {})[name] = False
    hub = Hub()
    await hub.start()
    sup = Supervisor(cfg)
    await sup.start()
    llm = Ollama(cfg["ollama"])
    asyncio.create_task(llm.warm())
    asyncio.create_task(_check_models(llm, cfg["ollama"]))
    tools.load_all()
    files.configure(cfg.get("tools", {}))
    store = Store(paths.DATA / "memory.db")
    memory = Memory(cfg["ollama"], store, llm=llm)
    vram = VramManager(hub, llm)
    orch = Orchestrator(hub, llm, Runner(Gate(hub)), memory, vram)
    reminders = Reminders(store, orch.announce)
    tools.CTX.memory, tools.CTX.reminders = memory, reminders
    tools.CTX.google = GoogleAuth()
    reminders.start()
    miner = asyncio.create_task(_mine_memories(memory))
    stop = stop or asyncio.Event()
    Controller(hub, orch, vram, memory, stop.set, google=tools.CTX.google)
    hotkey = HoldHotkey(cfg["hotkeys"]["push_to_talk"], asyncio.get_running_loop(),
                        orch.ptt_down, orch.ptt_up)
    hotkey.start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C arrives as KeyboardInterrupt instead
            pass
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        hotkey.stop()
        reminders.stop()
        miner.cancel()
        try:  # close today's conversation into memory before leaving
            await asyncio.wait_for(memory.extract_due(force=True), 30)
        except Exception as e:
            log.warning("memory extraction at exit skipped: %s", e)
        await memory.close()
        try:  # Ollama is shared (often the Ollama app's server), so it stays; her model doesn't
            await asyncio.wait_for(llm.unload(), 5)
        except Exception as e:
            log.warning("could not unload the LLM at exit: %s", e)
        await llm.close()
        for role in ("overlay", "voice"):
            await hub.send(role, Quit())
        await sup.stop()
        await hub.stop()


async def _check_models(llm: Ollama, ocfg: dict) -> None:
    """Say so in the log if the Ollama answering on our port can't see her models."""
    wanted = [ocfg["model"], ocfg.get("embed_model", "")]
    for _ in range(30):  # a server the supervisor just spawned needs a moment
        try:
            missing = await llm.missing_models([w for w in wanted if w])
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        log.error("Ollama did not answer at %s", ocfg["url"])
        return
    if missing:
        log.error("Ollama at %s can't see %s. Another Ollama (likely the Ollama app) is serving "
                  "without OLLAMA_MODELS=%s: set that user environment variable and restart the "
                  "Ollama app, or quit it so Raphael starts her own.", ocfg["url"], ", ".join(missing),
                  ocfg.get("models_dir", ""))


async def _mine_memories(memory: Memory) -> None:
    """Every minute, turn conversations that have gone quiet into facts and summaries."""
    while True:
        await asyncio.sleep(60)
        try:
            await memory.extract_due()
        except Exception:
            log.exception("memory extraction failed")


def single_instance() -> object | None:
    """A named mutex: a second agent would fight the first for the mic, the speakers and
    the hotkey (it happened during M3 testing). Returns the handle to keep, or None."""
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.CreateMutexW(None, False, r"Local\ChibiAgent.agent")
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main() -> None:
    ap = argparse.ArgumentParser(prog="chibi_agent")
    ap.add_argument("--without", action="append", choices=["overlay", "voice"], default=[],
                    help="don't start this child process (e.g. to drive it from a test client)")
    args = ap.parse_args()
    lock = single_instance()
    if lock is None:
        raise SystemExit("Raphael is already running (another Chibi-Agent holds the lock).")
    paths.ensure()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(paths.LOGS / "agent.log", encoding="utf-8")])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run(without=args.without))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
