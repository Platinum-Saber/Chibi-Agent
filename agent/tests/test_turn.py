import asyncio

from chibi_agent.hotkey import parse
from chibi_agent.llm import Chunk, SentenceSplitter
from chibi_agent.orchestrator import Orchestrator
from chibi_agent.persona import system_prompt
from chibi_shared import protocol as p


def test_splitter_emits_sentences_as_they_end():
    s = SentenceSplitter()
    assert s.feed("Answer.") == []          # no boundary yet: might be "Answer.5"
    assert s.feed(" The capital is") == ["Answer."]
    assert s.feed(" Tokyo. Shall") == ["The capital is Tokyo."]
    assert s.flush() == ["Shall"]


def test_splitter_cuts_run_ons():
    s = SentenceSplitter(max_chars=40)
    out = s.feed("one, two, three, four, five, six, seven, eight, nine, ten")
    assert out and all(len(x) <= 41 for x in out)


def test_persona_stays_short():
    assert len(system_prompt()) < 3000
    assert len(system_prompt([("open_app", "Open an application by name.")] * 12)) < 3000


def test_hotkey_parse():
    assert parse("Alt+1") == ({"alt"}, "1")
    assert parse("ctrl+alt+s") == ({"ctrl", "alt"}, "s")


class FakeHub:
    def __init__(self):
        self.sent = []

    def on_message(self, h):
        pass

    async def send(self, role, msg):
        self.sent.append((role, msg))
        return True


class FakeLLM:
    def __init__(self, pieces):
        self.pieces = pieces
        self.seen = None

    async def chat(self, messages, tools=None, think=False):
        self.seen = messages
        for piece in self.pieces:
            yield Chunk(text=piece)
        yield Chunk(done=True)


async def test_turn_plays_opener_clip_then_synthesises():
    hub, llm = FakeHub(), FakeLLM(["Answer.", " Tokyo is the", " capital, Master."])
    o = Orchestrator(hub, llm)
    o.start_turn("capital of Japan?")
    await o.turn
    speaks = [m for r, m in hub.sent if isinstance(m, p.Speak)]
    assert [(s.text, s.clip) for s in speaks] == [
        ("Answer.", "Answer."), ("Tokyo is the capital, Master.", None)]
    bubbles = [m for r, m in hub.sent if isinstance(m, p.Bubble)]
    assert bubbles[-1].done and bubbles[-1].text == "Answer. Tokyo is the capital, Master."
    assert o.history[-1] == {"role": "assistant", "content": "Answer. Tokyo is the capital, Master."}


async def test_marker_mid_reply_is_not_a_clip():
    hub = FakeHub()
    o = Orchestrator(hub, FakeLLM(["Tokyo. Answer. Done."]))
    o.start_turn("x")
    await o.turn
    assert all(m.clip is None for r, m in hub.sent if isinstance(m, p.Speak))


async def test_ptt_down_interrupts_the_turn():
    class SlowLLM(FakeLLM):
        async def chat(self, messages, tools=None, think=False):
            yield Chunk(text="Answer. ")
            await asyncio.sleep(10)
            yield Chunk(text="never")

    hub = FakeHub()
    o = Orchestrator(hub, SlowLLM([]))
    o.start_turn("x")
    await asyncio.sleep(0.05)
    o.ptt_down()
    await asyncio.sleep(0.05)
    assert o.turn.cancelled()
    assert any(isinstance(m, p.Stop) for r, m in hub.sent)
    assert any(r == "voice" and isinstance(m, p.Ptt) and m.down for r, m in hub.sent)


async def test_history_is_bounded():
    hub = FakeHub()
    o = Orchestrator(hub, FakeLLM(["Answer. Ok."]))
    for i in range(30):
        o.start_turn(f"q{i}")
        await o.turn
    assert len(o.history) == 24
