"""Agent entry point: hub, supervisor, then (from M1) the orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from chibi_shared import config, paths
from chibi_shared.protocol import Quit

from . import tools
from .hotkey import HoldHotkey
from .tools import files
from .tools.runner import Gate, Runner
from .llm import Ollama
from .orchestrator import Orchestrator
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
    tools.load_all()
    files.configure(cfg.get("tools", {}))
    orch = Orchestrator(hub, llm, Runner(Gate(hub)))
    hotkey = HoldHotkey(cfg["hotkeys"]["push_to_talk"], asyncio.get_running_loop(),
                        orch.ptt_down, orch.ptt_up)
    hotkey.start()
    stop = stop or asyncio.Event()
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
        await llm.close()
        for role in ("overlay", "voice"):
            await hub.send(role, Quit())
        await sup.stop()
        await hub.stop()


def main() -> None:
    ap = argparse.ArgumentParser(prog="chibi_agent")
    ap.add_argument("--without", action="append", choices=["overlay", "voice"], default=[],
                    help="don't start this child process (e.g. to drive it from a test client)")
    args = ap.parse_args()
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
