"""One conversation turn at a time: transcript in, streamed speech + bubble out.

Flow (docs/architecture.md -> Turn data flow): PTT down -> voice records,
she listens; PTT up -> transcript -> Ollama stream -> sentences. The opener
("Answer.", "Notice." ...) plays from a pre-rendered clip the moment the LLM
emits it, which hides F5's ~1 s per-sentence cost (spike 3: 0.82 s to first
audio instead of 2.0 s). Pressing PTT while she talks interrupts her.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from chibi_shared.protocol import (Bubble, Message, MoodReq, Ptt, Role, Speak, SpeakState, Stop,
                                   TextInput, Transcript)

from .llm import Ollama, SentenceSplitter
from .persona import MARKERS, system_prompt
from .server import Hub

log = logging.getLogger(__name__)
HISTORY_TURNS = 12


class Orchestrator:
    def __init__(self, hub: Hub, llm: Ollama):
        self.hub = hub
        self.llm = llm
        self.history: list[dict] = []
        self.turn: asyncio.Task | None = None
        self.pending_utts: set[str] = set()
        self.listening = False
        self.t_release = 0.0
        hub.on_message(self.on_message)

    # --- inputs ---------------------------------------------------------------
    def ptt_down(self) -> None:
        self.listening = True
        if self.turn and not self.turn.done():
            self.turn.cancel()  # barge-in
        asyncio.create_task(self._ptt(True))

    def ptt_up(self) -> None:
        if not self.listening:
            return
        self.listening = False
        self.t_release = time.perf_counter()
        asyncio.create_task(self._ptt(False))

    async def _ptt(self, down: bool) -> None:
        if down:
            await self.hub.send("voice", Stop())
            self.pending_utts.clear()
        await self.hub.send("voice", Ptt(down=down))
        await self.hub.send("overlay", MoodReq(mood="listening" if down else "thinking"))

    async def on_message(self, role: Role, msg: Message) -> None:
        if isinstance(msg, Transcript):
            log.info("heard (%d ms): %s", msg.ms, msg.text)
            self.start_turn(msg.text)
        elif isinstance(msg, TextInput):
            self.t_release = time.perf_counter()
            self.start_turn(msg.text)
        elif isinstance(msg, SpeakState):
            if msg.state in ("end", "cancel"):
                self.pending_utts.discard(msg.utt_id)
                if not self.pending_utts and (self.turn is None or self.turn.done()):
                    await self.hub.send("overlay", MoodReq(mood="idle"))
            elif msg.state == "start" and self.t_release:
                log.info("first audio %.2f s after release", time.perf_counter() - self.t_release)
                self.t_release = 0.0

    def start_turn(self, text: str) -> None:
        text = text.strip()
        if not text:
            asyncio.create_task(self.hub.send("overlay", MoodReq(mood="idle")))
            return
        if self.turn and not self.turn.done():
            self.turn.cancel()
        self.turn = asyncio.create_task(self._run_turn(text))

    # --- the turn -------------------------------------------------------------
    async def _say(self, sentence: str, first: bool) -> None:
        utt = uuid.uuid4().hex
        self.pending_utts.add(utt)
        clip = sentence if first and sentence in MARKERS else None
        await self.hub.send("voice", Speak(utt_id=utt, text=sentence, clip=clip))

    async def _run_turn(self, text: str) -> None:
        messages = [{"role": "system", "content": system_prompt()}, *self.history,
                    {"role": "user", "content": text}]
        split = SentenceSplitter()
        reply, first, talking = "", True, False
        try:
            async for chunk in self.llm.chat(messages):
                if chunk.text:
                    reply += chunk.text
                    await self.hub.send("overlay", Bubble(text=reply, stream=True, done=False))
                for s in split.feed(chunk.text):
                    if not talking:
                        await self.hub.send("overlay", MoodReq(mood="talking"))
                        talking = True
                    await self._say(s, first)
                    first = False
            for s in split.flush():
                await self._say(s, first)
                first = False
        except asyncio.CancelledError:
            log.info("turn interrupted")
            raise
        except Exception as e:
            log.exception("turn failed")
            reply = "Warning. My reasoning core is unavailable, Master."
            await self._say(reply, False)
            await self.hub.send("overlay", MoodReq(mood="alert"))
        await self.hub.send("overlay", Bubble(text=reply, stream=True, done=True))
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-2 * HISTORY_TURNS:]
        if not self.pending_utts:
            await self.hub.send("overlay", MoodReq(mood="idle"))
