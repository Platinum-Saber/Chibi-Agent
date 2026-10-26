import asyncio
import datetime as dt
import hashlib
import math
import re
import time

import pytest

from chibi_agent import memory as mem
from chibi_agent.memory import Memory
from chibi_agent.memory.store import DIM, Store
from chibi_agent.schedulers import Reminders, parse_when, say_when

STOP = {"kryo", "kryo's", "is", "the", "a", "an", "of", "my", "to", "what", "does", "do", "i", "and", "on", "in", "s"}


class BagEmbedder:
    """Deterministic stand-in for nomic-embed-text: hashed bag of content words."""

    async def __call__(self, texts, query=False):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z']+", t.lower()):
                if w not in STOP:
                    v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    async def close(self):
        pass


class FakeLLM:
    def __init__(self, facts, summary="Talked about the weekend."):
        self.out, self.prompts = {"facts": facts, "summary": summary}, []

    async def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.out


@pytest.fixture
def memory():
    m = Memory({}, Store(":memory:"), BagEmbedder())
    yield m
    m.store.close()


async def test_remember_then_recall(memory):
    await memory.remember("Saber's cat is called Miso")
    await memory.remember("Saber drinks iced latte")
    block = await memory.recall("what is my cat called")
    assert "Miso" in block and "latte" not in block


async def test_near_duplicate_replaces(memory, monkeypatch):
    monkeypatch.setattr(mem, "DUPLICATE_SIM", 0.8)
    assert await memory.remember("Saber's cat is called Miso") == "added"
    assert await memory.remember("Saber's cat is called Miso now") == "updated"
    assert len(memory.store.all_facts()) == 1


async def test_nothing_relevant_gives_empty_block(memory):
    await memory.remember("Saber's cat is called Miso")
    assert await memory.recall("quantum chromodynamics lecture") == ""


async def test_forget(memory):
    await memory.remember("Saber's cat is called Miso")
    hits = await memory.find("cat called", min_sim=0.3)
    memory.forget([h.id for h in hits])
    assert memory.store.all_facts() == []


async def test_conversation_ends_after_idle_and_is_extracted(monkeypatch):
    llm = FakeLLM(["Saber plays Valorant on weekends"])
    m = Memory({}, Store(":memory:"), BagEmbedder(), llm)
    m.log_turn("I'll play Valorant this weekend", "Answer. Have fun.")
    first = m.conv_id
    assert await m.extract_due() == 0  # still going
    real = time.time
    monkeypatch.setattr(mem.time, "time", lambda: real() + 400)
    m.log_turn("new topic", "Answer. Sure.")
    assert m.conv_id != first  # a new conversation after 5 quiet minutes
    assert await m.extract_due() >= 1
    assert "Valorant" in llm.prompts[0] and "Saber: I'll play Valorant" in llm.prompts[0]
    assert "Valorant" in await m.recall("do I play Valorant on weekends")


async def test_extraction_failure_is_retried_later():
    class Broken(FakeLLM):
        async def complete_json(self, prompt, schema):
            raise RuntimeError("ollama down")

    m = Memory({}, Store(":memory:"), BagEmbedder(), Broken([]))
    m.log_turn("hello", "Answer. Hello.")
    await m.extract_due(force=True)
    assert m.store.unextracted(time.time() + 1)  # still pending


def test_parse_when():
    now = dt.datetime(2026, 10, 17, 7, 0)
    assert parse_when("in 20 minutes", now) == now + dt.timedelta(minutes=20)
    assert parse_when("at 6 pm", now) == dt.datetime(2026, 10, 17, 18, 0)
    assert parse_when("at 6 am", now) == dt.datetime(2026, 10, 18, 6, 0)  # already past today
    assert parse_when("tomorrow at 9am", now) == dt.datetime(2026, 10, 18, 9, 0)
    assert parse_when("next monday 10am", now).weekday() == 0
    assert parse_when("whenever", now) is None


def test_say_when():
    now = dt.datetime(2026, 10, 17, 7, 0).timestamp()
    assert say_when(dt.datetime(2026, 10, 17, 18, 0).timestamp(), now) == "today at 6:00 PM"
    assert say_when(dt.datetime(2026, 10, 18, 9, 5).timestamp(), now) == "tomorrow at 9:05 AM"


async def test_reminder_fires_once_on_time():
    fired = []

    async def announce(r, late):
        fired.append((r.text, late))

    store = Store(":memory:")
    rem = Reminders(store, announce)
    rem.start()
    rem.add("call Mom", time.time() + 0.3)
    rem.add("later thing", time.time() + 3600)
    await asyncio.sleep(0.9)
    rem.stop()
    assert fired == [("call Mom", False)]
    assert [r.text for r in store.pending_reminders()] == ["later thing"]


async def test_missed_reminders_on_startup(tmp_path):
    db = tmp_path / "m.db"
    s = Store(db)
    s.add_reminder("recent miss", time.time() - 600)
    s.add_reminder("ancient miss", time.time() - 2 * 86400)
    s.add_reminder("future", time.time() + 3600)
    s.close()
    fired = []

    async def announce(r, late):
        fired.append((r.text, late))

    store = Store(db)  # a restart: reminders persisted
    rem = Reminders(store, announce)
    rem.start()
    await asyncio.sleep(0.3)
    rem.stop()
    assert fired == [("recent miss", True)]
    assert [r.text for r in store.pending_reminders()] == ["future"]


async def test_cancel_wakes_and_skips():
    fired = []

    async def announce(r, late):
        fired.append(r.text)

    store = Store(":memory:")
    rem = Reminders(store, announce)
    rem.start()
    rid = rem.add("tea", time.time() + 0.4)
    rem.cancel(rid)
    await asyncio.sleep(0.7)
    rem.stop()
    assert fired == []
