"""The briefing composer: ranks what needs Kryo's attention and words it in her
voice ("Notice. … End of report."). A port of Saber-Theme's BriefingComposer.

Pure: no clock, network or model, so every rule is tested. The model only labels
single mails upstream; when a model phrased briefings it just read the facts
back, so the words are written here. Module codes and mail addresses are never
spoken.
"""
from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass, field
from enum import IntEnum

MAX_WORDS = 50
SPOKEN_FACTS = 4
DEADLINE_WINDOW = dt.timedelta(hours=72)
OPENERS = ("Notice.", "Report.")
CLOSER = "End of report."
ALL_QUIET = "There are no pending matters, Kryo."
_NUMBERS = "Two Three Four Five Six Seven Eight Nine Ten".split()
_CODE = re.compile(r"\b[A-Z]{2,4} ?\d{4}[A-Z]?\b\s*[-:–]?\s*")
_DEADLINE = re.compile(r"\b(exam|quiz|deadline|due|submission|viva|presentation)\b", re.I)
_PREFIX = re.compile(r"^\s*(exam|quiz|deadline|due|submission|viva|presentation)\s*[:\-–]\s*", re.I)


class Urgency(IntEnum):
    NOW = 0
    TODAY = 1
    SOON = 2
    LATER = 3


@dataclass
class Event:
    key: str
    title: str
    start: dt.datetime
    all_day: bool = False


@dataclass
class Mail:
    key: str
    sender: str  # a name, never an address
    subject: str
    label: str   # urgent | reply | bill | info | promo
    at: dt.datetime


@dataclass
class Reminder:
    key: str
    text: str
    due: dt.datetime


@dataclass
class Item:
    key: str
    kind: str     # deadline | mail | event | reminder
    title: str    # for the HUD
    urgency: Urgency
    at: dt.datetime | None
    speech: str


@dataclass
class Briefing:
    items: list[Item]
    sentences: list[str]  # marker first: it plays from a clip
    mail_keys: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


# --- wording helpers -------------------------------------------------------------------
def strip_codes(s: str) -> str:
    """'EXAM: EN4554 Deep Learning for Vision' -> 'EXAM: Deep Learning for Vision'."""
    return re.sub(r"\s{2,}", " ", _CODE.sub("", s)).strip(" -:–")


def speak_name(sender: str) -> str:
    """Names only: an address that slipped through becomes its domain's name."""
    if "@" not in sender:
        return sender.strip() or "someone"
    return sender.split("<")[-1].split("@", 1)[1].split(".")[0] or "someone"


def clock(t: dt.datetime) -> str:
    s = t.strftime("%I:%M %p").lstrip("0")
    return s.replace(":00", "")


def when(t: dt.datetime, now: dt.datetime) -> str:
    days = (t.date() - now.date()).days
    if days == 0:
        return f"today at {clock(t)}"
    if days == 1:
        return f"tomorrow at {clock(t)}"
    if 2 <= days <= 6:
        return f"on {t:%A} at {clock(t)}"
    return f"on {t.day} {t:%B}"


def in_hours(delta: dt.timedelta) -> str:
    hours = round(delta.total_seconds() / 3600)
    if hours < 1:
        return "within the hour"
    return "in one hour" if hours == 1 else f"in {hours} hours"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _words(s: str) -> int:
    return len(s.split())


# --- the lines -----------------------------------------------------------------------------
def _deadline(e: Event, now: dt.datetime) -> Item | None:
    left = e.start - now
    if left <= dt.timedelta(0) or left > DEADLINE_WINDOW:
        return None
    kind = _DEADLINE.search(e.title).group(1).lower()
    name = strip_codes(_PREFIX.sub("", e.title))
    name = re.sub(rf"\b{kind}\b", "", name, flags=re.I).strip(" -:–") or name
    due = in_hours(left) if left < dt.timedelta(hours=6) else when(e.start, now)
    if kind in ("deadline", "due", "submission"):
        speech = f"{name} is due {due}"
    else:
        speech = f"your {name} {kind} is {due}"
    urgency = Urgency.NOW if left < dt.timedelta(hours=24) else Urgency.SOON
    return Item(e.key, "deadline", f"{strip_codes(e.title)} · {when(e.start, now)}", urgency, e.start, speech)


def _event(e: Event, now: dt.datetime) -> Item | None:
    days = (e.start.date() - now.date()).days
    title = strip_codes(e.title)
    if e.all_day:
        if days == 0:
            return Item(e.key, "event", f"{title} · all day", Urgency.SOON, e.start, f"{title} is today")
        if days == 1:
            return Item(e.key, "event", f"{title} · tomorrow", Urgency.LATER, e.start, f"{title} is tomorrow")
        return None
    if e.start < now or days > 1:
        return None
    if e.start - now <= dt.timedelta(hours=2):
        urgency = Urgency.TODAY
    elif days == 0:
        urgency = Urgency.SOON
    else:
        urgency = Urgency.LATER
    speech = f"{title} begins at {clock(e.start)}" if days == 0 else f"{title} is tomorrow at {clock(e.start)}"
    return Item(e.key, "event", f"{title} · {clock(e.start)}", urgency, e.start, speech)


def _mail(m: Mail) -> Item | None:
    sender, subject = speak_name(m.sender), strip_codes(m.subject) or "no subject"
    if m.label == "urgent":
        urgency, speech = Urgency.TODAY, f"urgent mail from {sender}: {subject}"
    elif m.label == "reply":
        urgency, speech = Urgency.TODAY, f"{sender} awaits your reply regarding {subject}"
    elif m.label == "bill":
        urgency, speech = Urgency.SOON, f"a bill from {sender}: {subject}"
    else:
        return None  # info and promo never surface
    return Item(m.key, "mail", f"{sender}: {subject}", urgency, m.at, speech)


def _reminder(r: Reminder, now: dt.datetime) -> Item | None:
    if r.due.date() != now.date() or r.due < now:
        return None
    return Item(r.key, "reminder", f"{r.text} · {clock(r.due)}", Urgency.TODAY, r.due,
                f"a reminder at {clock(r.due)}: {r.text}")


def compose(now: dt.datetime, events: list[Event] = (), mails: list[Mail] = (),
            reminders: list[Reminder] = (), seed: int = 0) -> Briefing:
    items: list[Item] = []
    for e in events:  # an exam or due date is a deadline (72 h window), never also an event
        item = _deadline(e, now) if _DEADLINE.search(e.title) else _event(e, now)
        if item:
            items.append(item)
    items += [i for i in (_mail(m) for m in mails) if i]
    items += [i for i in (_reminder(r, now) for r in reminders) if i]
    far = dt.datetime.max.replace(tzinfo=now.tzinfo)
    items.sort(key=lambda i: (i.urgency, i.at or far))
    mail_keys = [i.key for i in items if i.kind == "mail"]
    if not items:
        return Briefing([], ["Report.", ALL_QUIET])
    opener = random.Random(seed).choice(OPENERS)
    n = len(items)
    count = ("One matter requires your attention, Kryo." if n == 1 else
             f"{_NUMBERS[n - 2] if n - 2 < len(_NUMBERS) else n} matters require your attention, Kryo.")
    sentences, words = [opener, count], _words(opener) + _words(count) + _words(CLOSER)
    for item in items[:SPOKEN_FACTS]:
        fact = _cap(item.speech) + "."
        if words + _words(fact) > MAX_WORDS:
            break
        sentences.append(fact)
        words += _words(fact)
    return Briefing(items, sentences + [CLOSER], mail_keys)


def urgent_sentences(mails: list[Mail]) -> list[str]:
    """Unasked, so short: the alarm word, then the pressing mails."""
    sentences, words = ["Warning."], 1
    for m in mails[:SPOKEN_FACTS]:
        item = _mail(m)
        if not item:
            continue
        fact = _cap(item.speech) + "."
        if words + _words(fact) > MAX_WORDS:
            break
        sentences.append(fact)
        words += _words(fact)
    return sentences if len(sentences) > 1 else []
