"""Agent entry point: hub, supervisor, then (from M1) the orchestrator."""
from __future__ import annotations

import asyncio
import logging
import signal

from chibi_shared import config, paths
from chibi_shared.protocol import Quit

from .server import Hub
from .supervisor import Supervisor

log = logging.getLogger("chibi_agent")


async def run(stop: asyncio.Event | None = None) -> None:
    paths.ensure()
    cfg = config.load()
    hub = Hub()
    await hub.start()
    sup = Supervisor(cfg)
    await sup.start()
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
        for role in ("overlay", "voice"):
            await hub.send(role, Quit())
        await sup.stop()
        await hub.stop()


def main() -> None:
    paths.ensure()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(paths.LOGS / "agent.log", encoding="utf-8")])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
