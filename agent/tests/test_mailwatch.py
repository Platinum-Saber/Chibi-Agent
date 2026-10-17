import datetime as dt

import httpx
import pytest

from chibi_agent import tools
from chibi_agent.mailwatch import Briefer, MailWatch, MorningBriefing, in_quiet_hours
from chibi_agent.memory.store import MailRow, Store
from chibi_agent.orchestrator import BRIEFING
from chibi_agent.tools import calendar as cal
from chibi_agent.tools import gmail

A, B = "kryo@gmail.com", "kryo.22@uni.lk"
TOKENS = {"tok-a": A, "tok-b": B}
T0 = dt.datetime(2026, 10, 19, 10, 0).timestamp()  # a Monday, 10:00


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class FakeGoogle:
    def accounts(self):
        return [A, B]

    async def token(self, email):
        return {A: "tok-a", B: "tok-b"}[email]


class FakeLLM:
    def __init__(self, label="urgent"):
        self.label, self.calls = label, 0

    async def complete_json(self, prompt, schema):
        self.calls += 1
        assert "@" not in prompt.split("EMAIL:")[-1].split("|")[0]  # no address in the prompt's sender
        return {"label": self.label, "reason": "exam change"}


class FakeOrch:
    busy = False

    def __init__(self):
        self.reports = []

    async def report(self, sentences, title, items, alert=False):
        self.reports.append((sentences, title, items, alert))


class FakeVram:
    gaming = False


def msg(mid, sender, subject, at):
    return {"id": mid, "internalDate": str(int(at * 1000)), "labelIds": [], "snippet": "please check",
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}}


class Inbox:
    def __init__(self):
        self.mails = {A: [], B: []}
        self.refuse = set()
        self.requests = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests += 1
        who = TOKENS[req.headers["authorization"].removeprefix("Bearer ")]
        if who in self.refuse:
            return httpx.Response(403)
        if req.url.path.endswith("/messages"):
            assert "newer_than:1d" in req.url.params["q"] and "-category:promotions" in req.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": m["id"]} for m in self.mails[who]]})
        mid = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=next(m for m in self.mails[who] if m["id"] == mid))


@pytest.fixture
def env(monkeypatch):
    inbox = Inbox()
    monkeypatch.setattr(gmail, "TRANSPORT", httpx.MockTransport(inbox.handler))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    store, clock, llm, orch, vram = Store(":memory:"), Clock(), FakeLLM(), FakeOrch(), FakeVram()
    w = MailWatch(store, llm, orch, vram, {}, clock=clock)
    return inbox, store, clock, llm, orch, vram, w


async def test_poll_labels_new_mail_once(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("a1", '"Dr Perera" <perera@uni.lk>', "EN4554 exam hall changed", T0 + 60),
                      msg("a2", "noreply@github.com", "CI failed", T0 + 30)]
    clock.t = T0 + 120
    assert await w.poll() == 2
    assert llm.calls == 1  # github settled by the sender rule
    rows = {r.key: r for r in store.mail_since(0, ("urgent", "info"), ("new",))}
    assert rows[f"{A}:a1"].label == "urgent" and rows[f"{A}:a1"].sender == "Dr Perera"
    assert rows[f"{A}:a2"].label == "info"
    assert "@" not in rows[f"{A}:a1"].sender
    assert await w.poll() == 0 and llm.calls == 1  # known mail is skipped


async def test_store_keeps_no_snippet(env):
    inbox, store, clock, *_rest, w = env
    inbox.mails[A] = [msg("a1", "X <x@y.com>", "Hello", T0 + 10)]
    await w.poll()
    cols = [r[1] for r in store.db.execute("PRAGMA table_info(mail)")]
    assert "snippet" not in cols and "body" not in cols


async def test_urgent_warning_once_and_backlog_skipped(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("old", "Prof <p@u.lk>", "Old urgent thing", T0 - 600),  # before she started
                      msg("new", '"Dr Perera" <perera@uni.lk>', "EN4554 exam hall changed", T0 + 60)]
    clock.t = T0 + 120
    await w.poll()
    assert await w.warn()
    sentences, title, items, alert = orch.reports[0]
    assert sentences == ["Warning.", "Urgent mail from Dr Perera: exam hall changed."] and alert
    assert "Old urgent" not in " ".join(sentences)
    assert not await w.warn() and len(orch.reports) == 1  # once only


async def test_quiet_hours_gaming_and_busy_defer(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("n", "Dr P <p@u.lk>", "Hall change", T0 + 60)]
    clock.t = T0 + 120
    await w.poll()
    vram.gaming = True
    assert not await w.warn()
    vram.gaming, orch.busy = False, True
    assert not await w.warn()
    orch.busy = False
    assert await w.warn()  # sent once allowed
    late = dt.datetime(2026, 10, 19, 23, 30)
    assert in_quiet_hours(late, "23:00", "07:00") and not in_quiet_hours(late.replace(hour=12), "23:00", "07:00")


async def test_old_urgent_mail_waits_for_the_briefing(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("n", "Dr P <p@u.lk>", "Hall change", T0 + 60)]
    clock.t = T0 + 120
    await w.poll()
    clock.t = T0 + 3 * 3600  # more than 2 h later
    assert not await w.warn() and not orch.reports


async def test_gaming_pauses_polling(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("n", "Dr P <p@u.lk>", "Hall change", T0 + 60)]
    vram.gaming = True
    assert await w.poll() == 0 and inbox.requests == 0 and llm.calls == 0


async def test_one_refused_account(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg("n", "Dr P <p@u.lk>", "Hall change", T0 + 60)]
    inbox.refuse.add(B)
    assert await w.poll() == 1


# --- the briefing -------------------------------------------------------------------------
async def test_briefer_reads_calendar_mail_and_marks_briefed(monkeypatch):
    def api(req):
        if req.url.path.endswith("/calendarList"):
            who = TOKENS[req.headers["authorization"].removeprefix("Bearer ")]
            return httpx.Response(200, json={"items": [{"id": who, "summary": who, "selected": True}]})
        return httpx.Response(200, json={"items": [
            {"iCalUID": "ex", "summary": "EXAM: EN4554 Deep Learning for Vision",
             "start": {"dateTime": "2026-10-20T09:00:00"}, "end": {"dateTime": "2026-10-20T12:00:00"}}]})
    monkeypatch.setattr(cal, "TRANSPORT", httpx.MockTransport(api))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    store = Store(":memory:")
    store.add_mail(MailRow(f"{A}:m", A, "Dr Perera", "Hall change", T0 - 600, "urgent"))
    store.add_mail(MailRow(f"{A}:p", A, "daraz", "Sale", T0 - 600, "promo"))
    b = await Briefer(store).run(dt.datetime.fromtimestamp(T0))
    text = " ".join(b.sentences)
    assert "Your Deep Learning for Vision exam is tomorrow at 9 AM." in text  # once, though two accounts
    assert text.count("Deep Learning") == 1
    assert "Urgent mail from Dr Perera: Hall change." in text and "Sale" not in text
    assert store.mail_since(0, ("urgent",), ("briefed",))


class FakeBriefer:
    def __init__(self):
        self.runs = 0

    async def run(self, now=None):
        from chibi_agent.briefing import compose
        self.runs += 1
        return compose(now or dt.datetime.now())


def _morning(start: dt.datetime, vram=None):
    clock = Clock(start.timestamp())
    orch, briefer, store = FakeOrch(), FakeBriefer(), Store(":memory:")
    m = MorningBriefing(store, briefer, orch, vram or FakeVram(), {}, clock=clock)
    return m, clock, orch, briefer


async def test_morning_on_first_start_after_six_once_a_day():
    m, clock, orch, briefer = _morning(dt.datetime(2026, 10, 19, 8, 0))
    assert not m.due()  # 10 s grace for the voice to connect
    clock.t += 15
    assert m.due()
    await m.fire()
    assert orch.reports and orch.reports[0][0][-1] in ("End of report.", "There are no pending matters, Kryo.")
    assert not m.due()  # once a day
    clock.t = dt.datetime(2026, 10, 20, 6, 30).timestamp()  # still running the next morning
    assert not m.due()
    clock.t = dt.datetime(2026, 10, 20, 7, 31).timestamp()
    assert m.due()


async def test_morning_running_since_before_six_waits_for_half_past_seven():
    m, clock, *_ = _morning(dt.datetime(2026, 10, 19, 5, 0))
    clock.t = dt.datetime(2026, 10, 19, 7, 0).timestamp()
    assert not m.due()
    clock.t = dt.datetime(2026, 10, 19, 7, 30).timestamp()
    assert m.due()


async def test_morning_waits_while_gaming():
    vram = FakeVram()
    vram.gaming = True
    m, clock, *_ = _morning(dt.datetime(2026, 10, 19, 9, 0), vram)
    clock.t += 30
    assert not m.due()
    vram.gaming = False
    assert m.due()


def test_briefing_command_regex():
    for s in ("Briefing.", "Give me the briefing", "Raphael, morning report please", "What needs my attention?",
              "anything important?"):
        assert BRIEFING.search(s), s
    for s in ("report a bug in this code", "write a report about Rome", "is the briefing room free"):
        assert not BRIEFING.search(s), s


async def test_briefing_command_skips_the_llm():
    from chibi_shared import protocol as p
    from test_turn import FakeHub

    from chibi_agent.orchestrator import Orchestrator

    class NoLLM:
        async def chat(self, *a, **k):
            raise AssertionError("the briefing must not call the model")
            yield
    hub, briefer = FakeHub(), FakeBriefer()
    o = Orchestrator(hub, NoLLM())
    o.briefer = briefer
    o.start_turn("Give me the briefing")
    await o.turn
    speaks = [m for r, m in hub.sent if isinstance(m, p.Speak)]
    assert briefer.runs == 1 and speaks[0].clip == "Report." and speaks[0].text == "Report."
    assert not o.busy or o.pending_utts  # only her speech is pending


async def test_labelling_yields_to_a_conversation(env):
    inbox, store, clock, llm, orch, vram, w = env
    inbox.mails[A] = [msg(f"m{i}", f"Person {i} <p{i}@x.lk>", "Hello", T0 + i) for i in range(3)]

    async def label_then_talk(prompt, schema):
        llm.calls += 1
        if llm.calls == 1:
            orch.busy = True  # Kryo pressed push-to-talk during the first label
        return {"label": "info", "reason": "x"}
    llm.complete_json = label_then_talk
    assert await w.poll() == 1 and llm.calls == 1
    orch.busy = False
    assert await w.poll() == 2  # the rest are labelled on the next poll
