"""Her short voice reactions: the overlay reports a body event (`React`), this decides whether
she says something and which line (docs/character.md -> Sounds).

She stays quiet when muted, in gaming mode, while Saber is talking to her or she's answering,
and inside the cooldowns; idle moments she starts by herself speak only sometimes. The line
plays from the voice process's clip cache (`only_cached`): a reaction never synthesises.
"""
from __future__ import annotations

import logging
import os
import random
import time

from chibi_shared.protocol import React, Speak
from chibi_shared.reactions import IDLE_EVENTS, REACTIONS

log = logging.getLogger(__name__)

GLOBAL_COOLDOWN_S = 1.5
EVENT_COOLDOWN_S = 4.0
IDLE_CHANCE = 0.25
IDLE_COOLDOWN_S = 30.0
PREFIX = "react-"  # utt_id prefix: the orchestrator ignores these SpeakStates


class Reactor:
    def __init__(self, hub, orch, vram, rng: random.Random | None = None, clock=time.monotonic):
        self.hub, self.orch, self.vram = hub, orch, vram
        self._rng = rng or random.Random()
        self._clock = clock
        self._last = -1e9
        self._last_event: dict[str, float] = {}
        self._last_idle = -1e9
        self._last_line: dict[str, str] = {}
        hub.on_message(self.on_message)

    async def on_message(self, role, msg) -> None:
        if isinstance(msg, React):
            await self.react(msg.event, msg.picked)

    def line_for(self, event: str, picked: bool) -> str | None:
        """The line to say now, or None to stay quiet (and why, in the debug log)."""
        lines = REACTIONS.get(event)
        if not lines:
            return None
        if self.orch.muted or getattr(self.vram, "gaming", False) or self.orch.busy:
            return None
        now = self._clock()
        if now - self._last < GLOBAL_COOLDOWN_S or now - self._last_event.get(event, -1e9) < EVENT_COOLDOWN_S:
            return None
        if event in IDLE_EVENTS and not picked:
            if now - self._last_idle < IDLE_COOLDOWN_S or self._rng.random() >= IDLE_CHANCE:
                return None
            self._last_idle = now
        choices = [ln for ln in lines if ln != self._last_line.get(event)] or lines
        line = self._rng.choice(choices)
        self._last, self._last_event[event], self._last_line[event] = now, now, line
        return line

    async def react(self, event: str, picked: bool = False) -> None:
        line = self.line_for(event, picked)
        if line is None:
            return
        log.info("reaction %s%s: %s", event, " (picked)" if picked else "", line)
        await self.hub.send("voice", Speak(utt_id=f"{PREFIX}{os.urandom(4).hex()}", text=line,
                                           clip=line, only_cached=True))
