import asyncio

from chibi_agent.memrelief import MemoryRelief, Proc, own_stack, protected
from chibi_shared import protocol as p

from test_vram_control import FakeHub

ME = 100


class FakeLLM:
    model = "qwen3.5:4b"

    def __init__(self, loaded=True, embed=False):
        self.calls, self._loaded, self.embed = [], loaded, embed

    async def loaded(self):
        out = [{"name": self.model, "size": 4 * 2**30, "size_vram": 4 * 2**30}] if self._loaded else []
        return out + ([{"name": "nomic-embed-text:latest", "size": 2**28}] if self.embed else [])

    async def unload(self):
        self.calls.append("unload")
        self._loaded = False

    async def unload_embed(self, model):
        self.calls.append(("unload_embed", model))
        self.embed = False


class FakeGate:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def ask(self, tool, args):
        self.asked.append((tool.name, args))
        return self.answer


class FakeOrch:
    def __init__(self, gate=None, last_active=-1e9):
        self.busy = False
        self.last_active = last_active
        self.runner = type("R", (), {"gate": gate})()
        self.said = []

    async def _say(self, s, first):
        self.said.append(s)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def procs():
    """A small PC: her stack, system processes, the Claude app, the app in front, idle apps."""
    ps = [
        Proc(4, "System", private_mb=0, mine=False),
        Proc(50, "python.exe", cmd="python chibi.py", ppid=1),
        Proc(ME, "python.exe", cmd="python -m chibi_agent", ppid=50, private_mb=90, ws_mb=100),
        Proc(101, "python.exe", cmd="python -m chibi_voice", ppid=ME, private_mb=3000, ws_mb=1500),
        Proc(102, "python.exe", cmd="python -m chibi_overlay", ppid=ME, private_mb=800, ws_mb=800),
        Proc(103, "Godot_v4.7.2-stable_win64.exe", ppid=102, private_mb=800, ws_mb=800),
        Proc(110, "ollama.exe", cmd="ollama serve", private_mb=80, ws_mb=60),
        Proc(200, "svchost.exe", private_mb=900, ws_mb=900, mine=False),
        Proc(201, "dwm.exe", private_mb=1000, ws_mb=1000, mine=False),
        Proc(202, "MsMpEng.exe", private_mb=500, ws_mb=500, mine=False),
        Proc(300, "claude.exe", exe=r"C:\Program Files\WindowsApps\Claude_1.0\app\claude.exe", private_mb=900, ws_mb=900),
        Proc(301, "msedgewebview2.exe", ppid=300, private_mb=1000, ws_mb=1000),
        Proc(400, "Code.exe", private_mb=1200, ws_mb=1200),           # in front
        Proc(500, "chrome.exe", private_mb=900, ws_mb=600),           # idle, has a window
        Proc(501, "chrome.exe", ppid=500, private_mb=1200, ws_mb=700),
        Proc(600, "Discord.exe", private_mb=800, ws_mb=500, cpu_s=0),  # busy
        Proc(700, "Steam.exe", private_mb=750, ws_mb=400),            # idle, no window
    ]
    return {x.pid: x for x in ps}


def make(cfg=None, *, pct=(80.0,), orch=None, llm=None, engine="f5", busy_pids=(600,)):
    hub = FakeHub()
    seq = list(pct)
    calls = {"snap": 0, "trim": [], "close": []}

    def sample():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def snap():
        calls["snap"] += 1
        ps = procs()
        for pid in busy_pids:  # CPU time grows between snapshots
            ps[pid].cpu_s = calls["snap"] * 5.0
        return ps

    def trim_fn(pid):
        calls["trim"].append(pid)
        return True

    async def nosleep(_):
        pass

    clock = Clock()
    r = MemoryRelief(hub, llm or FakeLLM(), orch, None, {"threshold": 70, **(cfg or {})},
                     sample=sample, available=lambda: 4000.0, snap=snap,
                     windows=lambda: {500: [5001], 400: [4001], 600: [6001], 300: [3001]},
                     foreground=lambda: 400, trim_fn=trim_fn, close_fn=calls["close"].extend,
                     ws=lambda pid: 50.0, sleep=nosleep, clock=clock, engine=lambda: engine)
    return r, hub, calls, clock


def test_hysteresis_and_cooldown():
    r, hub, calls, clock = make({"own_stack": False, "trim_working_sets": False, "offer_close": False},
                                pct=(71, 69, 71, 72, 68, 72, 66, 64, 72, 72))

    async def ticks(n):
        return [await r.tick() for _ in range(n)]

    out = asyncio.run(ticks(4))  # 71, 69 (reset), 71, 72 -> high on the 2nd in a row
    assert [o is not None for o in out] == [False, False, False, True]
    assert r.high
    clock.t = 30
    out = asyncio.run(ticks(3))  # 68, 72, 66: still high (not under 65), but in cooldown
    assert out == [None, None, None] and r.high
    out = asyncio.run(ticks(1))  # 64: back under threshold - hysteresis
    assert not r.high
    clock.t = 700
    out = asyncio.run(ticks(2))  # 72, 72: high again, cooldown over
    assert out[1] is not None


def test_skips_while_busy():
    orch = FakeOrch()
    orch.busy = True
    r, hub, calls, clock = make(pct=(80, 80), orch=orch)
    asyncio.run(r.tick())
    assert asyncio.run(r.tick()) is None and calls["snap"] == 0


def test_own_stack_first_and_early_stop():
    orch = FakeOrch(gate=FakeGate(True))
    llm = FakeLLM()
    r, hub, calls, clock = make(pct=(60,), orch=orch, llm=llm)
    clock.t = 1000
    rep = asyncio.run(r.relieve(80))
    loads = [(m.t, m.what, m.reason) for _, m in hub.sent if isinstance(m, p.Load)]
    assert loads == [("unload", "tts", "memory")]
    assert llm.calls == ["unload"]
    assert calls["trim"] == [] and calls["close"] == []  # RAM fell under 65 % after stage 1
    assert rep["done"] == ["unloaded my voice model", "unloaded the language model"]
    assert orch.said == ["Notice."]  # F5 just went: only the clip, so it isn't loaded straight back


def test_recent_activity_keeps_models():
    clock_now = 1000
    orch = FakeOrch(last_active=clock_now - 30)
    llm = FakeLLM()
    r, hub, calls, clock = make({"trim_working_sets": False, "offer_close": False}, orch=orch, llm=llm)
    clock.t = clock_now
    asyncio.run(r.relieve(80))
    assert not [m for _, m in hub.sent if isinstance(m, p.Load)] and llm.calls == []


def test_kokoro_voice_is_not_unloaded():
    orch = FakeOrch()
    r, hub, calls, clock = make({"trim_working_sets": False, "offer_close": False}, orch=orch, engine="kokoro")
    clock.t = 1000
    rep = asyncio.run(r.relieve(80))
    assert not [m for _, m in hub.sent if isinstance(m, p.Load)]
    assert "unloaded my voice model" not in rep["done"]


def test_trims_only_idle_unprotected_and_quiet_voice():
    orch = FakeOrch(gate=FakeGate(False))
    r, hub, calls, clock = make({"offer_close": False}, orch=orch, llm=FakeLLM(loaded=False), engine="kokoro")
    clock.t = 1000
    asyncio.run(r.relieve(80))
    # chrome x2, Steam idle; her quiet voice process; never Discord (busy), Code (front),
    # svchost/dwm/MsMpEng (system), Claude + its WebView2, overlay/Godot/agent/ollama (hers).
    assert sorted(calls["trim"]) == [101, 500, 501, 700]


def test_offer_declined_closes_nothing_and_stays_quiet():
    gate = FakeGate(False)
    orch = FakeOrch(gate=gate)
    r, hub, calls, clock = make({"trim_working_sets": False}, orch=orch, llm=FakeLLM(loaded=False), engine="kokoro")
    clock.t = 1000
    asyncio.run(r.relieve(80))
    assert gate.asked == [("close_app", {"app": "chrome", "size": "2.1 GB"})]
    assert calls["close"] == []
    clock.t = 2000  # declined an hour's quiet: not offered again
    asyncio.run(r.relieve(80))
    assert len(gate.asked) == 1


def test_offer_yes_closes_that_app_only():
    gate = FakeGate(True)
    orch = FakeOrch(gate=gate)
    r, hub, calls, clock = make({"trim_working_sets": False}, orch=orch, llm=FakeLLM(loaded=False), engine="kokoro")
    clock.t = 1000
    rep = asyncio.run(r.relieve(80))
    assert calls["close"] == [5001]
    assert rep["done"] == ["asked chrome to close"]
    assert any(isinstance(m, p.Hud) and m.title == "Memory relief" for _, m in hub.sent)


def test_dry_run_touches_nothing():
    gate = FakeGate(True)
    orch = FakeOrch(gate=gate)
    llm = FakeLLM()
    r, hub, calls, clock = make(orch=orch, llm=llm)
    r.dry_run = True
    clock.t = 1000
    asyncio.run(r.relieve(80))
    assert hub.sent == [] and llm.calls == [] and calls["trim"] == [] and calls["close"] == [] and gate.asked == []


def test_protected_and_own_stack():
    ps = procs()
    guard = protected(ps, fg=400)
    assert {200, 201, 202, 4} <= guard.keys()               # system / not Kryo's
    assert guard[300] == guard[301] == "Claude app"          # and its WebView2
    assert guard[400] == "foreground"
    assert own_stack(ps, me=ME) == {50, ME, 101, 102, 103, 110}


def test_ptt_reloads_released_voice():
    orch = FakeOrch()
    r, hub, calls, clock = make({"trim_working_sets": False, "offer_close": False}, pct=(60,), orch=orch)
    clock.t = 1000
    asyncio.run(r.relieve(80))
    assert r.tts_released
    asyncio.run(r.on_ptt())
    assert [(m.t, m.what) for _, m in hub.sent if isinstance(m, p.Load)][-1] == ("load", "tts")
    assert not r.tts_released


def test_idle_embedding_model_is_unloaded():
    orch = FakeOrch()
    llm = FakeLLM(loaded=False, embed=True)
    r, hub, calls, clock = make({"embed_model": "nomic-embed-text", "trim_working_sets": False,
                                 "offer_close": False}, pct=(60,), orch=orch, llm=llm, engine="kokoro")
    clock.t = 1000
    rep = asyncio.run(r.relieve(80))
    assert llm.calls == [("unload_embed", "nomic-embed-text")]
    assert rep["done"] == ["unloaded the embedding model"]
    assert orch.said[0] == "Notice." and len(orch.said) == 2  # Kokoro: she says the whole report
