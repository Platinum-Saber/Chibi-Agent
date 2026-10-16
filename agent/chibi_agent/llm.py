"""Ollama chat client: streaming, tools, images. Settings come from config [ollama].

`num_ctx` stays fixed (8192): changing it per request reloads the model (28 s
in spike 3). `think` is off: qwen3.5 thinks by default and that costs latency.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


@dataclass
class Chunk:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    done: bool = False
    stats: dict = field(default_factory=dict)


class Ollama:
    def __init__(self, cfg: dict):
        self.url = cfg["url"]
        self.model = cfg["model"]
        self.num_ctx = cfg.get("num_ctx", 8192)
        self.keep_alive = cfg.get("keep_alive", "120s")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5))

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   think: bool = False) -> AsyncIterator[Chunk]:
        body = {"model": self.model, "messages": messages, "stream": True, "think": think,
                "keep_alive": self.keep_alive, "options": {"num_ctx": self.num_ctx}}
        if tools:
            body["tools"] = tools
        async with self._client.stream("POST", f"{self.url}/api/chat", json=body) as r:
            if r.status_code != 200:
                detail = (await r.aread()).decode(errors="replace")
                raise RuntimeError(f"Ollama {r.status_code}: {detail}")  # surface Ollama's own message
            async for line in r.aiter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                m = msg.get("message", {})
                yield Chunk(text=m.get("content", ""), tool_calls=m.get("tool_calls") or [],
                            done=msg.get("done", False),
                            stats={k: msg[k] for k in ("eval_count", "eval_duration",
                                                        "prompt_eval_count") if k in msg})

    async def warm(self) -> None:
        """Load the model now, so Master's first question doesn't pay the cold load."""
        try:
            await self._client.post(f"{self.url}/api/generate", json={
                "model": self.model, "keep_alive": self.keep_alive, "options": {"num_ctx": self.num_ctx}})
            log.info("%s loaded", self.model)
        except httpx.HTTPError as e:
            log.warning("could not warm %s: %s", self.model, e)

    async def unload(self) -> None:
        await self._client.post(f"{self.url}/api/generate", json={"model": self.model, "keep_alive": 0})

    async def close(self) -> None:
        await self._client.aclose()


_BOUNDARY = re.compile(r"(?<=[.?!])\s+|\n+")


class SentenceSplitter:
    """Feeds streamed text, emits whole sentences as soon as they end.

    A run-on longer than `max_chars` is cut at its last comma or space so TTS
    can start without waiting for a full stop.
    """

    def __init__(self, max_chars: int = 160):
        self.buf = ""
        self.max_chars = max_chars

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out = []
        while True:
            m = _BOUNDARY.search(self.buf)
            if m:
                s, self.buf = self.buf[:m.start()].strip(), self.buf[m.end():]
                if s:
                    out.append(s)
                continue
            if len(self.buf) > self.max_chars:
                cut = max(self.buf.rfind(", ", 0, self.max_chars), self.buf.rfind(" ", 0, self.max_chars))
                if cut > 0:
                    out.append(self.buf[:cut + 1].strip())
                    self.buf = self.buf[cut + 1:].lstrip()
                    continue
            return out

    def flush(self) -> list[str]:
        s, self.buf = self.buf.strip(), ""
        return [s] if s else []
