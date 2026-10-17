"""Gaming mode and the VRAM budget (docs/architecture.md -> VRAM manager).

A fullscreen app in front (or the tray toggle) puts her in gaming mode: the
overlay hides itself, the LLM is unloaded (keep_alive 0) and the voice process
drops F5 and Whisper (STT falls back to CPU). Push-to-talk still works: the
moment PTT goes down the manager checks free VRAM with NVML and, if a turn
fits, starts reloading the LLM and TTS while Kryo is still speaking (the cold
reload was most of a ~16 s gaming-mode turn). It unloads everything again once
she has finished speaking.
"""
from __future__ import annotations

import asyncio
import logging

from chibi_shared.protocol import Load, Visibility

log = logging.getLogger(__name__)
TURN_NEEDS_MB = 4800  # qwen3.5:4b at 8k (~3.95 GB) + F5 (~0.95 GB), spike 3


def free_vram_mb() -> int | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        return pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).free // 2**20
    except Exception:
        return None


class VramManager:
    def __init__(self, hub, llm, free_mb=free_vram_mb):
        self.hub, self.llm, self.free_mb = hub, llm, free_mb
        self.fullscreen = ""  # exe of the fullscreen app in front, "" if none
        self.manual = False   # the tray's "Gaming mode"
        self.gaming = False
        self.preloaded = False  # gaming mode: models reloaded for the turn under way
        self.on_change = None  # async callback after gaming flips (State to the tray)

    async def set_fullscreen(self, exe: str) -> None:
        self.fullscreen = exe
        await self._update()

    async def set_manual(self, on: bool) -> None:
        self.manual = on
        await self._update()

    async def _update(self) -> None:
        want = self.manual or bool(self.fullscreen)
        if want == self.gaming:
            return
        self.gaming = want
        if want:
            log.info("gaming mode on (%s): freeing VRAM", self.fullscreen or "manual")
            await self.llm.unload()
            await self.hub.send("voice", Load(t="unload", what="all"))
            if self.manual:  # a fullscreen app already hid her in the overlay
                await self.hub.send("overlay", Visibility(hidden=True, reason="gaming mode"))
        else:
            log.info("gaming mode off: loading models again")
            await self.hub.send("overlay", Visibility(hidden=False))
            await self.hub.send("voice", Load(t="load", what="all"))
            await self.llm.warm()
        if self.on_change:
            await self.on_change()

    def _fits(self) -> bool:
        free = self.free_mb()
        return free is None or free >= TURN_NEEDS_MB

    async def on_ptt(self) -> None:
        """PTT went down: in gaming mode, reload the models while Kryo speaks."""
        if not self.gaming or self.preloaded or not self._fits():
            return  # a turn that doesn't fit is refused in before_turn
        self.preloaded = True
        await self.hub.send("voice", Load(t="load", what="tts"))
        asyncio.create_task(self.llm.warm())

    async def before_turn(self) -> bool:
        """In gaming mode: True if a turn fits in free VRAM now (TTS reloaded for it)."""
        if not self.gaming or self.preloaded:
            return True
        if not self._fits():
            log.warning("gaming mode: only %s MB free, need %d; skipping the turn", self.free_mb(), TURN_NEEDS_MB)
            return False
        self.preloaded = True
        await self.hub.send("voice", Load(t="load", what="tts"))
        return True

    async def after_speech(self) -> None:
        """She's done talking: in gaming mode, hand the VRAM back to the game."""
        self.preloaded = False
        if self.gaming:
            await self.llm.unload()
            await self.hub.send("voice", Load(t="unload", what="tts"))
