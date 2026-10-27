"""Gmail, read-only (M5). Code builds the query and the lines; senders are named,
never shown by address. Everything from a mail is untrusted data. The list is
numbered so Saber can say "read the second one" (read_mail resolves the number
against the last list). Mail stays unread: the scope is read-only."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import html
import re
from email.utils import parseaddr
from html.parser import HTMLParser

import httpx

from ..google_auth import short
from . import Result, _google, tool

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests swap in httpx.MockTransport
PER_ACCOUNT = 10
MAX_LINES = 12
BODY_CHARS = 1500
NEW_MAIL = ("is:unread in:inbox -category:promotions -category:social -category:updates "
            "-category:forums newer_than:3d")
_LAST: list[tuple[str, str]] = []  # the last list's [n] -> (account, message id)
_NUMBERS = {w: i for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve".split(), 1)}
_NUMBERS.update({"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1})


_AUTOMATED = re.compile(r"^(no-?reply|do-?not-?reply|notifications?|info|mailer|support|alerts?)\b", re.I)


def sender_name(from_header: str) -> str:
    """'Dr Perera <perera@uni.lk>' -> 'Dr Perera'; a bare address -> its local part,
    or its domain's name for automated senders ('noreply@github.com' -> 'github')."""
    name, addr = parseaddr(from_header)
    name = name.strip().strip('"')
    if name and "@" not in name:
        return name
    local, _, domain = (addr or from_header).partition("@")
    if _AUTOMATED.match(local) and domain:
        return domain.split(".")[0]
    return local or "someone"


def sender_addr(from_header: str) -> str:
    """For the label rules only; never shown or spoken."""
    return parseaddr(from_header)[1].lower()


async def fetch_new(query: str, emails: list[str]) -> tuple[list[tuple[str, dict]], list[str]]:
    """[(account, message metadata)] for a query over the given accounts, and problem lines."""
    done, problems = await _google.each_account(
        API, TRANSPORT, lambda c, auth, _e: _list_account(c, auth, query), emails)
    return [(email, m) for email, msgs in done for m in msgs], problems


def _headers(msg: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _when(msg: dict) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000).astimezone()


def format_line(n: int, account: str, msg: dict) -> str:
    h = _headers(msg)
    tags = short(account) + (", important" if "IMPORTANT" in msg.get("labelIds", []) else "")
    line = f"[{n}] {_when(msg):%a %d %b %H:%M}  {sender_name(h.get('from', ''))}: {h.get('subject') or '(no subject)'}"
    snippet = html.unescape(msg.get("snippet", "")).strip()
    return f"{line}  ({tags})" + (f" · {snippet[:100]}" if snippet else "")


async def _list_account(c: httpx.AsyncClient, auth: dict, query: str) -> list[dict]:
    r = await c.get("/messages", params={"q": query, "maxResults": str(PER_ACCOUNT)}, headers=auth)
    r.raise_for_status()
    ids = [m["id"] for m in r.json().get("messages", [])]

    async def meta(mid: str) -> dict:
        r = await c.get(f"/messages/{mid}", headers=auth, params=[
            ("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"),
            ("metadataHeaders", "Date")])
        r.raise_for_status()
        return r.json()
    return list(await asyncio.gather(*(meta(i) for i in ids)))


@tool("mail_list", "List new mail, or search mail.",
      {"about": ("Optional: what to search for, e.g. 'exam' or 'from Dr Perera'. Empty = new mail", False)},
      summary=lambda a: f"Mail: {a.get('about') or 'new'}")
async def mail_list(about: str = "") -> Result:
    emails = _google.accounts()
    if not emails:
        return Result(_google.not_connected("Mail"))
    about = (about or "").strip()
    query = f"{about} newer_than:30d" if about else NEW_MAIL
    done, problems = await _google.each_account(
        API, TRANSPORT, lambda c, auth, _e: _list_account(c, auth, query), emails)
    if not done:
        return Result("\n".join(problems), failed=True)
    mails = sorted(((email, m) for email, msgs in done for m in msgs), key=lambda x: _when(x[1]), reverse=True)
    _LAST[:] = [(email, m["id"]) for email, m in mails[:MAX_LINES]]
    if not mails:
        text = f"No mail about '{about}' in the last 30 days." if about else "No new mail."
    else:
        lines = [format_line(i, email, m) for i, (email, m) in enumerate(mails[:MAX_LINES], 1)]
        if len(mails) > MAX_LINES:
            lines.append(f"…and {len(mails) - MAX_LINES} more.")
        text = ("Mail about '" + about + "':\n" if about else "New mail:\n") + "\n".join(lines)
    return Result("\n".join([text, *problems]), untrusted=True)


# --- reading one mail ---------------------------------------------------------------
class _Text(HTMLParser):
    BLOCK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s: str) -> str:
    p = _Text()
    p.feed(s)
    return "".join(p.out)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _walk(part: dict, plain: list[str], htmls: list[str], files: list[str]) -> None:
    mime, body = part.get("mimeType", ""), part.get("body", {})
    if part.get("filename"):
        files.append(part["filename"])
    elif mime == "text/plain" and body.get("data"):
        plain.append(_decode(body["data"]))
    elif mime == "text/html" and body.get("data"):
        htmls.append(_decode(body["data"]))
    for sub in part.get("parts", []):
        _walk(sub, plain, htmls, files)


_WROTE = re.compile(r"^\s*On .{5,200}wrote:\s*$", re.M)


def clean_body(text: str) -> str:
    m = _WROTE.search(text)
    if m:
        text = text[:m.start()]  # the quoted conversation below adds nothing
    lines = [ln.strip() for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    text = "\n".join(re.sub(r"[ \t ]+", " ", ln) for ln in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_text(msg: dict) -> tuple[str, list[str]]:
    plain, htmls, files = [], [], []
    _walk(msg.get("payload", {}), plain, htmls, files)
    text = "\n".join(plain) if plain else "\n".join(html_to_text(h) for h in htmls)
    return clean_body(text), files


def _number(s: str) -> int | None:
    s = s.strip().lower()
    m = re.search(r"\d+", s)  # "2", "[2]", "2nd", "number 2"
    if m:
        return int(m.group())
    for word in s.split():
        if word in _NUMBERS:
            return _NUMBERS[word]
    return None


@tool("read_mail", "Read one mail from the last list in full.",
      {"number": ("The mail's number in the last list, e.g. '2'", True)},
      summary=lambda a: f"Read mail {a.get('number')}")
async def read_mail(number: str) -> Result:
    if not _LAST:
        return Result("There is no mail list yet. List the mail first with mail_list.")
    n = _number(str(number))
    if n == -1:
        n = len(_LAST)
    if n is None or not 1 <= n <= len(_LAST):
        return Result(f"The last list has mails 1 to {len(_LAST)}. Ask Saber which one.")
    email, mid = _LAST[n - 1]
    done, problems = await _google.each_account(
        API, TRANSPORT, lambda c, auth, _e: _get_full(c, auth, mid), [email])
    if not done:
        return Result("\n".join(problems), failed=True)
    msg = done[0][1]
    h = _headers(msg)
    body, files = body_text(msg)
    if len(body) > BODY_CHARS:
        body = body[:BODY_CHARS].rstrip() + " (cut)"
    head = (f"From {sender_name(h.get('from', ''))}, {_when(msg):%a %d %b %H:%M}, "
            f"subject: {h.get('subject') or '(no subject)'}")
    if files:
        head += "\nAttachments: " + ", ".join(files[:10])
    return Result(f"{head}\n\n{body or '(no text)'}", untrusted=True)


async def _get_full(c: httpx.AsyncClient, auth: dict, mid: str) -> dict:
    r = await c.get(f"/messages/{mid}", params={"format": "full"}, headers=auth)
    r.raise_for_status()
    return r.json()
