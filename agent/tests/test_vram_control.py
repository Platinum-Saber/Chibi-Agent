import asyncio

from chibi_agent.control import Controller
from chibi_agent.memory import Memory
from chibi_agent.memory.store import Store
from chibi_agent.vram import TURN_NEEDS_MB, VramManager
from chibi_shared import protocol as p

from test_memory import BagEmbedder


class FakeHub:
    def __init__(self):
        self.sent, self.handlers, self.connects = [], [], []

    def on_message(self, h):
        self.handlers.append(h)

    def on_connect(self, cb):
        self.connects.append(cb)

    async def send(self, role, msg):
        self.sent.append((role, msg))
        return True


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def unload(self):
        self.calls.append("unload")

    async def warm(self):
        self.calls.append("warm")


def loads(hub):
    return [(m.t, m.what) for r, m in hub.sent if isinstance(m, p.Load)]


async def test_fullscreen_frees_vram_and_back():
    hub, llm = FakeHub(), FakeLLM()
    v = VramManager(hub, llm, free_mb=lambda: 8000)
    await v.set_fullscreen("VALORANT-Win64-Shipping.exe")
    assert v.gaming and llm.calls == ["unload"] and loads(hub) == [("unload", "all")]
    await v.set_fullscreen("VALORANT-Win64-Shipping.exe")  # no repeat work
    assert llm.calls == ["unload"]
    await v.set_fullscreen("")
    assert not v.gaming and llm.calls == ["unload", "warm"] and loads(hub)[-1] == ("load", "all")


async def test_manual_gaming_mode_hides_her():
    hub = FakeHub()
    v = VramManager(hub, FakeLLM(), free_mb=lambda: 8000)
    await v.set_manual(True)
    assert any(isinstance(m, p.Visibility) and m.hidden for r, m in hub.sent)
    await v.set_manual(False)
    assert isinstance([m for r, m in hub.sent if isinstance(m, p.Visibility)][-1], p.Visibility)
    assert not [m for r, m in hub.sent if isinstance(m, p.Visibility)][-1].hidden


async def test_turn_in_gaming_mode_needs_free_vram():
    hub, llm = FakeHub(), FakeLLM()
    free = {"mb": TURN_NEEDS_MB - 1}
    v = VramManager(hub, llm, free_mb=lambda: free["mb"])
    assert await v.before_turn()  # not gaming: always fine
    await v.set_fullscreen("game.exe")
    assert not await v.before_turn()
    free["mb"] = TURN_NEEDS_MB + 500
    assert await v.before_turn() and loads(hub)[-1] == ("load", "tts")
    await v.after_speech()
    assert llm.calls[-1] == "unload" and loads(hub)[-1] == ("unload", "tts")


class FakeOrch:
    muted = False


async def test_controller_commands(monkeypatch):
    hub = FakeHub()
    mem = Memory({}, Store(":memory:"), BagEmbedder())
    await mem.remember("Kryo likes tea")
    await mem.remember("Kryo's cat is Miso")
    quit_called = []
    orch = FakeOrch()
    c = Controller(hub, orch, VramManager(hub, FakeLLM(), free_mb=lambda: 8000), mem,
                   lambda: quit_called.append(True))
    await c.command("mute", "")
    assert orch.muted and isinstance(hub.sent[-1][1], p.State) and hub.sent[-1][1].muted
    await c.command("memory_list", "")
    items = hub.sent[-1][1].items
    assert [t for _, t in items] == ["Kryo likes tea.", "Kryo's cat is Miso."]
    await c.command("memory_delete", str(items[0][0]))
    assert [t for _, t in hub.sent[-1][1].items] == ["Kryo's cat is Miso."]
    await c.command("gaming_on", "")
    assert hub.sent[-1][1].gaming
    await c.command("quit", "")
    assert quit_called
    await hub.connects[0]("overlay")  # the overlay (re)connects: it gets the state
    assert isinstance(hub.sent[-1][1], p.State)


async def test_fullscreen_message_routes_to_vram():
    hub = FakeHub()
    v = VramManager(hub, FakeLLM(), free_mb=lambda: 8000)
    Controller(hub, FakeOrch(), v, Memory({}, Store(":memory:"), BagEmbedder()), lambda: None)
    await hub.handlers[0]("overlay", p.Fullscreen(active=True, exe="game.exe"))
    assert v.gaming
    await asyncio.sleep(0)


async def test_ptt_in_gaming_mode_reloads_while_kryo_speaks():
    hub, llm = FakeHub(), FakeLLM()
    free = {"mb": TURN_NEEDS_MB + 500}
    v = VramManager(hub, llm, free_mb=lambda: free["mb"])
    await v.on_ptt()
    assert not v.preloaded  # not gaming: nothing to do
    await v.set_fullscreen("game.exe")
    n = len(loads(hub))
    await v.on_ptt()
    await asyncio.sleep(0)
    assert loads(hub)[n:] == [("load", "tts")] and llm.calls[-1] == "warm"
    free["mb"] = 0  # the game grew meanwhile: the turn already has its models
    assert await v.before_turn() and loads(hub)[n:] == [("load", "tts")]
    await v.after_speech()
    assert not v.preloaded and loads(hub)[-1] == ("unload", "tts")
    await v.on_ptt()
    assert not v.preloaded  # doesn't fit now
