"""Google Calendar, read-only (M5). Code turns Kryo's words into a time range and
formats the events; the model only reads the lines. Event text comes from other
people's invites, so it is marked untrusted."""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from urllib.parse import quote

import dateparser
import httpx

from ..google_auth import short
from . import Result, _google, tool

API = "https://www.googleapis.com/calendar/v3"
MAX_LINES = 25
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests swap in httpx.MockTransport
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "fourteen": 14}
_N_DAYS = re.compile(r"(?:next|coming)?\s*(\d+|" + "|".join(_WORDS) + r")\s+days?")


def day_range(when: str | None, now: dt.datetime) -> tuple[dt.datetime, dt.datetime, str] | None:
    """'today', 'tomorrow', 'this week', 'next week', 'the weekend', 'next 3 days' or a date
    -> (start, end, label) in local time; None if it can't be read."""
    w = (when or "today").strip().lower().rstrip("?.")
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day = dt.timedelta(days=1)
    monday_next = day0 + (7 - day0.weekday()) * day
    if w in ("", "today", "now"):
        return day0, day0 + day, "today"
    if w in ("tonight", "rest of today", "later today", "later"):
        return now, day0 + day, "for the rest of today"
    if w == "tomorrow":
        return day0 + day, day0 + 2 * day, "tomorrow"
    if w in ("this week", "week", "the week"):
        return day0, monday_next, "this week"
    if w == "next week":
        return monday_next, monday_next + 7 * day, "next week"
    if "weekend" in w:
        sat = day0 + ((5 - day0.weekday()) % 7) * day if day0.weekday() != 6 else day0 - day
        if w.startswith("next"):
            sat += 7 * day
        return max(sat, day0), sat + 2 * day, "this weekend" if not w.startswith("next") else "next weekend"
    m = _N_DAYS.fullmatch(w)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _WORDS[m.group(1)]
        return day0, day0 + n * day, f"in the next {n} days"
    d = dateparser.parse(w, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now,
                                      "RETURN_AS_TIMEZONE_AWARE": False})
    if d is None:
        return None
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + day, f"on {start:%A %d %B}"


def _local(t: dt.datetime) -> dt.datetime:
    return t.astimezone() if t.tzinfo is None else t


def _when(ev: dict) -> tuple[dt.datetime, str]:
    """(sort key, 'Sat 18 Oct 09:00-10:00' or 'Sat 18 Oct all day') in local time."""
    s, e = ev.get("start", {}), ev.get("end", {})
    if "dateTime" in s:
        a = dt.datetime.fromisoformat(s["dateTime"]).astimezone()
        b = dt.datetime.fromisoformat(e.get("dateTime", s["dateTime"])).astimezone()
        return a, f"{a:%a %d %b} {a:%H:%M}–{b:%H:%M}"
    a = dt.datetime.fromisoformat(s.get("date", "1970-01-01")).astimezone()
    return a, f"{a:%a %d %b} all day"


def format_events(events: list[tuple[str, dict]], label: str, many_calendars: bool) -> str:
    rows, seen = [], set()
    for cal, ev in events:
        uid = ev.get("iCalUID") or ev.get("id")
        if ev.get("status") == "cancelled" or (uid and uid in seen):
            continue  # an invite in two of Kryo's accounts shows once
        seen.add(uid)
        key, when = _when(ev)
        line = f"{when}  {(ev.get('summary') or '(no title)')[:80]}"
        if ev.get("location"):
            line += f"  at {ev['location'][:60]}"
        if many_calendars:
            line += f"  ({cal})"
        rows.append((key, line))
    if not rows:
        return f"No events {label}."
    rows.sort(key=lambda r: r[0])
    lines = [r[1] for r in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        lines.append(f"…and {len(rows) - MAX_LINES} more.")
    return f"Events {label}:\n" + "\n".join(lines)


async def fetch_events(c: httpx.AsyncClient, auth: dict, start: dt.datetime,
                       end: dt.datetime) -> tuple[list[tuple[str, dict]], int]:
    """Events from every calendar one account shows in Google Calendar, and how many calendars.
    The calendars are read at the same time."""
    r = await c.get("/users/me/calendarList", params={"minAccessRole": "reader"}, headers=auth)
    r.raise_for_status()
    cals = [x for x in r.json().get("items", []) if x.get("selected") or x.get("primary")]
    params = {"timeMin": _local(start).isoformat(), "timeMax": _local(end).isoformat(),
              "singleEvents": "true", "orderBy": "startTime", "maxResults": "100"}

    async def one(cal: dict) -> list[tuple[str, dict]]:
        r = await c.get(f"/calendars/{quote(cal['id'], safe='')}/events", params=params, headers=auth)
        r.raise_for_status()
        name = cal.get("summaryOverride") or cal.get("summary") or cal["id"]
        if name == cal["id"] and "@" in name:  # a primary calendar is named after its address
            name = short(name)
        return [(name, ev) for ev in r.json().get("items", [])]
    lists = await asyncio.gather(*(one(cal) for cal in cals))
    return [x for lst in lists for x in lst], len(cals)


@tool("calendar_events", "List Kryo's calendar events.",
      {"when": ("'today', 'tomorrow', 'this week', 'next week', 'the weekend', 'next 3 days' or a date", False)},
      summary=lambda a: f"Calendar: {a.get('when') or 'today'}")
async def calendar_events(when: str = "today") -> Result:
    emails = _google.accounts()
    if not emails:
        return Result(_google.not_connected("Calendar"))
    rng = day_range(when, dt.datetime.now())
    if rng is None:
        return Result(f"I could not understand '{when}' as a day. Ask Kryo which day.")
    start, end, label = rng
    # All accounts at once over one pooled client: one by one took ~10 s for three accounts.
    done, problems = await _google.each_account(
        API, TRANSPORT, lambda c, auth, _email: fetch_events(c, auth, start, end), emails)
    if not done:
        return Result("\n".join(problems), failed=True)
    events = [ev for _, (got, _n) in done for ev in got]
    n_cals = sum(n for _, (_got, n) in done)
    text = format_events(events, label, n_cals > 1)
    return Result("\n".join([text, *problems]), untrusted=True)
