"""Raphael's long-term memory (docs/architecture.md -> Memory).

- recall(query): the top facts and past-conversation summaries similar to what
  Saber just said, as a short block for the system prompt (~20 ms warm embed).
- remember(text): store one fact, replacing a near-duplicate instead of piling up.
- conversations: every turn is logged; after 5 minutes of quiet the conversation
  is closed and the model extracts durable facts plus a one-line summary from
  Saber's words and her replies only (never tool output: screen/file/web text
  must not be able to plant memories).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from chibi_shared import paths

from .store import Hit, Store

log = logging.getLogger(__name__)

IDLE_S = 300.0         # a conversation ends after 5 minutes without a turn
FACT_MIN_SIM = 0.5     # recall threshold for facts (nomic-embed-text cosine; the spike set needs 0.52)
SUMMARY_MIN_SIM = 0.6
DUPLICATE_SIM = 0.9    # a new fact this close to an old one replaces it

EXTRACT_PROMPT = """You maintain long-term memory for Raphael, a desktop companion, about her user Saber.
From the conversation below, list durable facts about Saber worth remembering for weeks: preferences, people, projects, routines, important dates, how Saber likes things done. Each fact is one short sentence that starts with "Saber" and uses the name Saber, never he, she or they.
Do NOT store: small talk, one-off requests or tasks (reminders, opening apps, questions asked once), the time or date, anything only Raphael said. Return at most 6 facts, or none.
Also write a one-sentence summary of what was discussed. Never use a pronoun for Saber (no he/she/his/her/they/their): repeat the name, e.g. "Saber mentioned that Saber's sister is visiting."

Conversation:
{conversation}"""
EXTRACT_SCHEMA = {"type": "object", "properties": {
    "facts": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"}}, "required": ["facts", "summary"]}


class Embedder:
    def __init__(self, cfg: dict):
        self.url, self.model = cfg["url"], cfg.get("embed_model", "nomic-embed-text")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5))

    async def __call__(self, texts: list[str], query: bool = False) -> list[list[float]]:
        prefix = "search_query: " if query else "search_document: "  # nomic's task prefixes
        r = await self._client.post(f"{self.url}/api/embed", json={
            "model": self.model, "input": [prefix + t for t in texts], "keep_alive": "30m"})
        r.raise_for_status()
        return r.json()["embeddings"]

    async def close(self) -> None:
        await self._client.aclose()


class Memory:
    def __init__(self, cfg: dict, store: Store | None = None, embed: Embedder | None = None, llm=None):
        self.store = store or Store(paths.DATA / "memory.db")
        self.embed = embed or Embedder(cfg)
        self.llm = llm  # an Ollama client, for extraction
        self.conv_id: int | None = None
        self.last_turn = 0.0

    # --- recall -------------------------------------------------------------------------
    async def recall(self, query: str, vec: list[float] | None = None) -> str:
        """A prompt block of what she remembers that relates to `query` ('' if nothing).
        `vec` is the turn's query vector when tool selection already embedded it."""
        if vec is None:
            try:
                (vec,) = await asyncio.wait_for(self.embed([query], query=True), 2.0)
            except Exception as e:
                log.warning("recall skipped: %s", "embedding took over 2 s (model cold?)"
                            if isinstance(e, asyncio.TimeoutError) else repr(e))
                return ""
        facts = self.store.search_facts(vec, 5, FACT_MIN_SIM)
        convs = self.store.search_summaries(vec, 2, SUMMARY_MIN_SIM)
        if not facts and not convs:
            return ""
        lines = ["What you remember (use only if relevant; never recite it as a list):"]
        lines += [f"- {h.text}" for h in facts]
        lines += [f"- Earlier conversation: {h.text}" for h in convs]
        return "\n".join(lines)

    # --- writing ------------------------------------------------------------------------
    async def remember(self, text: str, source: str = "told") -> str:
        text = text.strip().rstrip(".") + "."
        (vec,) = await self.embed([text])
        near = self.store.search_facts(vec, 1, DUPLICATE_SIM)
        if near:
            self.store.replace_fact(near[0].id, text, vec)
            return "updated"
        self.store.add_fact(text, vec, source)
        return "added"

    async def find(self, query: str, k: int = 5, min_sim: float = 0.5) -> list[Hit]:
        (vec,) = await self.embed([query], query=True)
        return self.store.search_facts(vec, k, min_sim)

    def forget(self, ids: list[int]) -> None:
        self.store.delete_facts(ids)

    # --- conversations --------------------------------------------------------------------
    def log_turn(self, user: str, reply: str) -> None:
        now = time.time()
        if self.conv_id is None or now - self.last_turn > IDLE_S:
            self.conv_id = self.store.new_conversation()
        self.store.log(self.conv_id, "user", user)
        if reply:
            self.store.log(self.conv_id, "assistant", reply)
        self.last_turn = now

    async def extract_due(self, force: bool = False) -> int:
        """Mine every finished conversation (quiet for IDLE_S, or all if `force`)."""
        before = time.time() + 1 if force else time.time() - IDLE_S
        done = 0
        for cid in self.store.unextracted(before):
            if cid == self.conv_id and not force and time.time() - self.last_turn < IDLE_S:
                continue
            await self._extract(cid)
            if cid == self.conv_id:
                self.conv_id = None
            done += 1
        return done

    async def _extract(self, cid: int) -> None:
        msgs = self.store.messages(cid)
        convo = "\n".join(f"{'Saber' if r == 'user' else 'Raphael'}: {c}" for r, c in msgs)
        facts, summary = [], ""
        if self.llm is not None and convo.strip():
            try:
                out = await self.llm.complete_json(EXTRACT_PROMPT.format(conversation=convo[-6000:]), EXTRACT_SCHEMA)
                facts = [f for f in out.get("facts", []) if isinstance(f, str) and f.strip()][:6]
                summary = str(out.get("summary", "")).strip()
            except Exception as e:
                log.warning("extraction failed for conversation %d: %s", cid, e)
                return  # stays unextracted; retried next time
        for f in facts:
            await self.remember(f, source=f"conversation:{cid}")
        vec = (await self.embed([summary]))[0] if summary else None
        self.store.set_summary(cid, summary, vec)
        log.info("conversation %d: %d facts, summary %r", cid, len(facts), summary[:80])

    async def close(self) -> None:
        await self.embed.close()
        self.store.close()

