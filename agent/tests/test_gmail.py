import base64
import logging

import httpx
import pytest

from chibi_agent import tools
from chibi_agent.persona import system_prompt
from chibi_agent.tools import gmail

A, B = "kryo@gmail.com", "kryo.22@uni.lk"
TOKENS = {"tok-a": A, "tok-b": B}


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def meta(mid, sender, subject, ms, labels=(), snippet=""):
    return {"id": mid, "internalDate": str(ms), "labelIds": list(labels), "snippet": snippet,
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}}


MAILS = {
    A: [meta("a1", '"Dr Perera" <perera@uni.lk>', "EN4554 exam hall changed", 1_792_300_000_000,
             ["IMPORTANT", "UNREAD"], "The exam moves to hall B &amp; starts at 9"),
        meta("a2", "noreply@github.com", "CI failed", 1_792_100_000_000)],
    B: [meta("b1", "Registrar <reg@uni.lk>", "Fees", 1_792_200_000_000)],
}
FULL = {
    "id": "b1", "internalDate": "1792200000000",
    "payload": {"mimeType": "multipart/mixed", "headers": [
        {"name": "From", "value": "Registrar <reg@uni.lk>"}, {"name": "Subject", "value": "Fees"}],
        "parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": b64(
                    "Dear student,\n\nPay   by Friday.\n> old quote\n\nOn Mon, 12 Oct 2026, X <x@y> wrote:\nold stuff")}},
                {"mimeType": "text/html", "body": {"data": b64("<p>HTML version</p>")}}]},
            {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"attachmentId": "x"}}]},
}


def gmail_api(seen, refuse=()):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        who = TOKENS[req.headers["authorization"].removeprefix("Bearer ")]
        if who in refuse:
            return httpx.Response(403)
        path = req.url.path
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": m["id"]} for m in MAILS[who]]})
        mid = path.rsplit("/", 1)[-1]
        if req.url.params.get("format") == "full":
            return httpx.Response(200, json=FULL)
        return httpx.Response(200, json=next(m for m in MAILS[who] if m["id"] == mid))
    return handler


class FakeGoogle:
    def __init__(self, accounts=(A, B)):
        self._accounts = list(accounts)

    def accounts(self):
        return self._accounts

    async def token(self, email):
        return {A: "tok-a", B: "tok-b"}[email]


@pytest.fixture
def api(monkeypatch):
    seen = []
    monkeypatch.setattr(gmail, "TRANSPORT", httpx.MockTransport(gmail_api(seen)))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    monkeypatch.setattr(gmail, "_LAST", [])
    return seen


async def test_new_mail_is_merged_newest_first_without_addresses(api):
    res = await gmail.mail_list()
    assert res.untrusted and not res.failed
    lines = res.text.splitlines()
    assert lines[0] == "New mail:"
    assert lines[1].startswith("[1] ") and "Dr Perera: EN4554 exam hall changed  (kryo, important)" in lines[1]
    assert "hall B & starts" in lines[1]
    assert "Registrar: Fees  (kryo.22)" in lines[2] and "github: CI failed" in lines[3]
    assert "@" not in res.text
    q = api[0].url.params["q"]
    assert "is:unread" in q and "-category:promotions" in q and "newer_than:3d" in q


async def test_search_uses_gmail_query(api):
    res = await gmail.mail_list("exam")
    assert api[0].url.params["q"] == "exam newer_than:30d"
    assert res.text.startswith("Mail about 'exam':")


async def test_read_mail_resolves_the_number(api):
    await gmail.mail_list()
    res = await gmail.read_mail("2nd")
    full = [r for r in api if r.url.params.get("format") == "full"]
    assert full and full[0].url.path.endswith("/messages/b1")
    assert full[0].headers["authorization"] == "Bearer tok-b"  # the right account
    assert res.untrusted
    head, body = res.text.split("\n\n", 1)
    assert head.startswith("From Registrar, ") and "subject: Fees" in head and "Attachments: invoice.pdf" in head
    assert body == "Dear student,\n\nPay by Friday."  # plain preferred, quotes dropped
    assert "@" not in res.text


async def test_read_mail_numbers_and_errors(api):
    assert "List the mail first" in (await gmail.read_mail("1")).text
    await gmail.mail_list()
    assert "1 to 3" in (await gmail.read_mail("7")).text
    await gmail.read_mail("the last one")
    full = [r for r in api if r.url.params.get("format") == "full"]
    assert full[-1].url.path.endswith("/messages/a2")  # oldest, listed third


async def test_one_refused_account_still_lists_the_other(monkeypatch):
    monkeypatch.setattr(gmail, "TRANSPORT", httpx.MockTransport(gmail_api([], refuse=(B,))))
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle())
    res = await gmail.mail_list()
    assert not res.failed and "Dr Perera" in res.text
    assert res.text.splitlines()[-1].startswith("Could not read kryo.22: Google refused access")


async def test_no_accounts(monkeypatch):
    monkeypatch.setattr(tools.CTX, "google", FakeGoogle(accounts=()))
    assert "Add Google account" in (await gmail.mail_list()).text


def test_body_from_html_and_long_mail():
    msg = {"payload": {"mimeType": "text/html", "body": {"data": b64(
        "<html><head><style>p{}</style></head><body><p>Hello&nbsp;Kryo</p><script>x()</script>"
        "<div>Line two</div></body></html>")}}}
    text, files = gmail.body_text(msg)
    assert text == "Hello Kryo\n\nLine two" and files == []


async def test_long_body_is_cut(api, monkeypatch):
    long = {**FULL, "payload": {**FULL["payload"], "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("word " * 800)}}]}}
    monkeypatch.setattr(gmail, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, json=long) if r.url.params.get("format") == "full"
        else gmail_api([])(r)))
    await gmail.mail_list()
    res = await gmail.read_mail("1")
    assert res.text.endswith("(cut)") and len(res.text) < gmail.BODY_CHARS + 200


def test_sender_name():
    assert gmail.sender_name('"Dr Perera" <perera@uni.lk>') == "Dr Perera"
    assert gmail.sender_name("perera@uni.lk") == "perera"
    assert gmail.sender_name("perera@uni.lk <perera@uni.lk>") == "perera"
    assert gmail.sender_name("noreply@github.com") == "github"
    assert gmail.sender_addr("\"Dr P\" <Perera@Uni.lk>") == "perera@uni.lk"


def test_mail_tools_are_read_only_and_the_prompt_fits():
    reg = tools.load_all()
    for name in ("mail_list", "read_mail"):
        assert not reg[name].side_effect and not reg[name].confirm
    assert len(system_prompt(tools.listing())) < 3400  # the real prompt, every tool listed


async def test_untrusted_results_stay_out_of_the_log(caplog, monkeypatch):
    from test_turn import FakeHub
    from chibi_agent.orchestrator import Orchestrator
    from chibi_agent.tools import Result

    class FakeRunner:
        gate = None

        async def run(self, name, args):
            return Result("Dr Perera: secret exam hall", untrusted=True)
    o = Orchestrator(FakeHub(), llm=None, runner=FakeRunner())
    caplog.set_level(logging.INFO)
    await o._run_calls([{"function": {"name": "mail_list", "arguments": {}}}], [])
    assert "secret" not in caplog.text and "chars of untrusted data" in caplog.text
