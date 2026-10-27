import asyncio
import random
from types import SimpleNamespace

from chibi_agent.orchestrator import Orchestrator
from chibi_agent.reactions import Reactor
from chibi_shared.protocol import SpeakState


class Hub:
    def __init__(self):
        self.sent = []

    def on_message(self, h):
        pass

    async def send(self, role, msg):
        self.sent.append((role, msg))


def _reactor(chance=0.0, **orch):
    t = [100.0]
    hub = Hub()
    o = SimpleNamespace(muted=False, busy=False, **orch)
    r = Reactor(hub, o, SimpleNamespace(gaming=False), rng=random.Random(1), clock=lambda: t[0])
    r._rng.random = lambda: chance
    return r, hub, o, t


def test_poke_speaks_a_cached_clip_then_cools_down():
    r, hub, _, t = _reactor()
    asyncio.run(r.react("poke"))
    (role, msg), = hub.sent
    assert role == "voice" and msg.only_cached and msg.clip == msg.text and msg.utt_id.startswith("react-")
    asyncio.run(r.react("poke"))
    assert len(hub.sent) == 1  # within the cooldowns
    t[0] += 5
    asyncio.run(r.react("poke"))
    assert len(hub.sent) == 2 and hub.sent[1][1].text != hub.sent[0][1].text  # no repeat


def test_quiet_when_muted_busy_or_gaming():
    for orch, gaming in (({"muted": True}, False), ({"busy": True}, False), ({}, True)):
        r, hub, o, _ = _reactor()
        for k, v in orch.items():
            setattr(o, k, v)
        r.vram.gaming = gaming
        asyncio.run(r.react("held"))
        assert hub.sent == []


def test_idle_moments_speak_sometimes_picked_poses_always():
    r, hub, _, _ = _reactor(chance=0.9)  # above IDLE_CHANCE: an idle stretch stays quiet
    asyncio.run(r.react("stretch"))
    assert hub.sent == []
    asyncio.run(r.react("stretch", picked=True))
    assert len(hub.sent) == 1
    asyncio.run(r.react("no_such_event", picked=True))
    assert len(hub.sent) == 1


def test_a_reaction_ending_doesnt_send_her_idle():
    hub = Hub()
    o = Orchestrator.__new__(Orchestrator)
    o.hub, o.pending_utts, o.turn, o.vram, o.last_active = hub, set(), None, None, 0.0
    asyncio.run(o.on_message("voice", SpeakState(utt_id="react-ab12", state="end")))
    assert hub.sent == []
