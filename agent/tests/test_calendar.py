import datetime as dt
import json

import httpx
import pytest

from chibi_agent import tools
from chibi_agent.google_auth import INDEX, SERVICE, GoogleAuth, NotConnected
from chibi_agent.tools import calendar as cal

NOW = dt.datetime(2026, 10, 17, 14, 30)  # a Saturday
DAY = dt.timedelta(days=1)
D0 = dt.datetime(2026, 10, 17)


@pytest.mark.parametrize("when,start,end", [
    (None, D0, D0 + DAY),
    ("today", D0, D0 + DAY),
    ("Tomorrow?", D0 + DAY, D0 + 2 * DAY),
    ("this week", D0, dt.datetime(2026, 10, 19)),
    ("next week", dt.datetime(2026, 10, 19), dt.datetime(2026, 10, 26)),
    ("the weekend", D0, D0 + DAY + DAY),
    ("next 3 days", D0, D0 + 3 * DAY),
    ("next three days", D0, D0 + 3 * DAY),
])
def test_day_range(when, start, end):
    s, e, _ = cal.day_range(when, NOW)
    assert (s, e) == (start, end)


def test_day_range_tonight_and_dates():
    assert cal.day_range("tonight", NOW)[:2] == (NOW, D0 + DAY)
    s, e, label = cal.day_range("October 21", NOW)
    assert s == dt.datetime(2026, 10, 21) and e == s + DAY and "Wednesday" in label
    assert cal.day_range("purple", NOW) is None


def test_weekend_on_sunday_is_today():
    sun = dt.datetime(2026, 10, 18, 9)
    s, e, _ = cal.day_range("this weekend", sun)
    assert s == dt.datetime(2026, 10, 18) and e == dt.datetime(2026, 10, 19)


A, B = "kryo@gmail.com", "kryo.22@uni.lk"
TOKENS = {"tok-a": A, "tok-b": B}
SHARED = {"iCalUID": "meet-1", "summary": "Project sync", "start": {"dateTime": "2026-10-17T18:00:00+05:30"},
          "end": {"dateTime": "2026-10-17T19:00:00+05:30"}}


def _who(req: httpx.Request) -> str:
    return TOKENS[req.headers["authorization"].removeprefix("Bearer ")]


def _events_api(seen, refuse=()):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        who = _who(req)
        if who in refuse:
            return httpx.Response(403)
        if req.url.path.endswith("/calendarList"):
            items = [{"id": who, "summary": who, "selected": True, "primary": True}]
            if who == A:
                items += [{"id": "en.lk#holiday@group.v.calendar.google.com", "summary": "Holidays",
                           "selected": True},
                          {"id": "hidden@x", "summary": "Hidden", "selected": False}]
            return httpx.Response(200, json={"items": items})
        if "holiday" in req.url.path:
            return httpx.Response(200, json={"items": [
                {"iCalUID": "poya", "summary": "Poya day", "start": {"date": "2026-10-17"},
                 "end": {"date": "2026-10-18"}}]})
        if who == A:
            return httpx.Response(200, json={"items": [
                {"iCalUID": "lab", "summary": "Lab report due", "location": "Room 4",
                 "start": {"dateTime": "2026-10-17T16:00:00+05:30"},
                 "end": {"dateTime": "2026-10-17T17:00:00+05:30"}, "attendees": [{"email": "someone@uni.lk"}]},
                {"iCalUID": "gone", "summary": "Gone", "status": "cancelled",
                 "start": {"dateTime": "2026-10-17T10:00:00+05:30"}},
                SHARED]})
        return httpx.Response(200, json={"items": [SHARED]})
    return handler


class FakeGoogle:
    def __init__(self, accounts=(A, B), expired=()):
        self._accounts, self.expired = list(accounts), expired

    def accounts(self):
        return self._accounts

    async def token(self, email):
        if email in self.expired:
            raise NotConnected("the sign-in has expired")
        return {A: "tok-a", B: "tok-b"}[email]


async def test_calendar_merges_accounts(monkeypatch):
    seen = []
    monkeypatch.setattr(cal, "TRANSPORT", httpx.MockTransport(_events_api(seen)))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    res = await cal.calendar_events("today")
    assert res.untrusted and not res.failed
    lines = res.text.splitlines()
    assert lines[0] == "Events today:"
    assert "all day  Poya day  (Holidays)" in lines[1]
    assert "Lab report due  at Room 4  (kryo)" in lines[2]
    assert "Project sync  (kryo)" in lines[3] and len(lines) == 4  # the shared invite shows once
    assert "Gone" not in res.text and "someone@" not in res.text and "@gmail" not in res.text
    paths = [r.url.raw_path.decode() for r in seen]
    assert any("en.lk%23holiday%40group" in p for p in paths)
    assert not any("hidden" in p for p in paths)


async def test_one_blocked_account_does_not_hide_the_others(monkeypatch):
    monkeypatch.setattr(cal, "TRANSPORT", httpx.MockTransport(_events_api([], refuse=(B,))))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    res = await cal.calendar_events("today")
    assert not res.failed and "Lab report due" in res.text
    assert res.text.splitlines()[-1].startswith("Could not read kryo.22: Google refused access")


async def test_all_accounts_failing_is_a_failure(monkeypatch):
    monkeypatch.setattr(cal, "TRANSPORT", httpx.MockTransport(_events_api([], refuse=(A,))))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle(expired=(B,)))
    res = await cal.calendar_events("tomorrow")
    assert res.failed and "expired" in res.text and "refused" in res.text


async def test_calendar_not_connected(monkeypatch):
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle(accounts=()))
    res = await cal.calendar_events()
    assert "Sign in to Google" in res.text and not res.failed


def test_calendar_tool_is_read_only():
    t = tools.load_all()["calendar_events"]
    assert not t.side_effect and not t.confirm


class FakeKeyring:
    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        del self.d[(s, u)]


class FakeCreds:
    def __init__(self, token, refresh):
        self.token, self.refresh_token = token, refresh


def _client_file(tmp_path):
    f = tmp_path / "google_client.json"
    f.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "s",
                                           "token_uri": "https://oauth2.googleapis.com/token"}}))
    return f


def _auth(tmp_path, kr, flows):
    """GoogleAuth whose browser flow hands out the next fake sign-in."""
    primary = httpx.MockTransport(lambda req: httpx.Response(200, json={"id": _who(req)}))
    g = GoogleAuth(_client_file(tmp_path), kr, transport=primary)
    g._run_flow = lambda: flows.pop(0)
    return g


async def test_several_accounts_sign_in_and_out(tmp_path):
    kr = FakeKeyring()
    g = _auth(tmp_path, kr, [FakeCreds("tok-a", "ra"), FakeCreds("tok-b", "rb"), FakeCreds("tok-a", "ra2")])
    assert not g.connected and g.accounts() == []
    assert await g.sign_in() == A
    assert await g.sign_in() == B
    assert await g.sign_in() == A  # again: renewed, not duplicated
    assert g.accounts() == [A, B] and kr.d[(SERVICE, f"google:{A}")] == "ra2"
    assert await g.token(B) == "tok-b"  # cached from the sign-in
    g.sign_out(A)
    assert g.accounts() == [B]
    with pytest.raises(NotConnected):
        await g.token(A)
    g.sign_out()
    assert g.accounts() == [] and (SERVICE, INDEX) not in kr.d
    g.sign_out()  # twice is fine


async def test_missing_client_file(tmp_path):
    with pytest.raises(NotConnected, match="missing.json"):
        await GoogleAuth(tmp_path / "missing.json", FakeKeyring()).sign_in()


def _signed_in(tmp_path, *emails):
    kr = FakeKeyring()
    for e in emails:
        kr.set_password(SERVICE, f"google:{e}", f"refresh-{e}")
    kr.set_password(SERVICE, INDEX, json.dumps(list(emails)))
    return kr, GoogleAuth(_client_file(tmp_path), kr)


async def test_invalid_grant_drops_only_that_account(tmp_path, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    def refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(Credentials, "refresh", refresh)
    kr, g = _signed_in(tmp_path, A, B)
    with pytest.raises(NotConnected, match="kryo has expired"):
        await g.token(A)
    assert g.accounts() == [B]


async def test_access_token_is_cached_per_account(tmp_path, monkeypatch):
    from google.oauth2.credentials import Credentials
    calls = []

    def refresh(self, request):
        calls.append(self.refresh_token)
        self.token = "access-" + self.refresh_token
        self.expiry = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=1)
    monkeypatch.setattr(Credentials, "refresh", refresh)
    kr, g = _signed_in(tmp_path, A, B)
    assert await g.token(A) == f"access-refresh-{A}" and await g.token(A) == f"access-refresh-{A}"
    assert await g.token(B) == f"access-refresh-{B}"
    assert calls == [f"refresh-{A}", f"refresh-{B}"]


async def test_accounts_and_calendars_are_read_at_the_same_time(monkeypatch):
    import asyncio
    import time
    sync = _events_api([])

    async def slow(req):
        await asyncio.sleep(0.2)
        return sync(req)
    monkeypatch.setattr(cal, "TRANSPORT", httpx.MockTransport(slow))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    t = time.perf_counter()
    res = await cal.calendar_events("today")
    # one by one: 5 requests x 0.2 s; in parallel: calendar list, then events = 2 rounds
    assert time.perf_counter() - t < 0.6 and "Project sync" in res.text
