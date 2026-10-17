"""Mail polling, urgent-mail warnings and the briefing (M5, docs/scope.md).

- MailWatch: every 5 minutes, new inbox mail from every account is labelled one
  mail at a time (mail_labels: rules first, then the model) and stored without
  its text. A new urgent mail is announced once, only 07:00-23:00, never while
  gaming or mid-turn, and only while it is under 2 hours old; otherwise it waits
  for the briefing. Polling pauses in gaming mode, so the 4 GB model never loads
  next to a game; the next poll catches up.
- Briefer: gathers calendar events (72 h), labelled mail, labelled Windows
  notifications (notifywatch) and today's reminders, and lets briefing.compose
  word them.
- MorningBriefing: once a day, on the first start after 06:00, or at 07:30 if
  she was already running.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable

from . import briefing, mail_labels
from .memory.store import MailRow, Store
from .tools import _google, calendar, gmail

log = logging.getLogger(__name__)
WATCH_QUERY = "in:inbox newer_than:1d -category:promotions -category:social -category:forums"
ANNOUNCE_WITHIN_S = 2 * 3600
BRIEF_LABELS = ("urgent", "reply", "bill")
NOTICE_LABELS = ("urgent", "reply")


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def in_quiet_hours(now: dt.datetime, quiet_from: str, quiet_to: str) -> bool:
    start, end, t = _hm(quiet_from), _hm(quiet_to), now.time()
    return (t >= start or t < end) if start > end else (start <= t < end)


class MailWatch:
    def __init__(self, store: Store, llm, orch, vram, cfg: dict, clock: Callable[[], float] = time.time):
        self.store, self.llm, self.orch, self.vram, self.cfg, self.clock = store, llm, orch, vram, cfg, clock
        self.started = clock()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mailwatch")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def gaming(self) -> bool:
        return bool(self.vram is not None and self.vram.gaming)

    async def poll(self) -> int:
        """Fetch, label and store new mail; returns how many were labelled."""
        emails = _google.accounts()
        if not emails or self.gaming:
            return 0
        found, problems = await gmail.fetch_new(WATCH_QUERY, emails)
        for p in problems:  # names the account only, never mail text
            log.warning("mail poll: %s", p.split(":")[0])
        keys = {f"{email}:{m['id']}": (email, m) for email, m in found}
        known = self.store.known_mail_keys(list(keys))
        new = [k for k in keys if k not in known]
        today = dt.date.today().strftime("%A %d %B %Y")
        done = 0
        for key in new:
            if self.orch.busy:  # Ollama runs one request at a time: Kryo's turn goes first.
                break           # The rest stay unstored, so the next poll labels them.
            email, m = keys[key]
            h = gmail._headers(m)
            mail = mail_labels.MailIn(key=key, sender_name=gmail.sender_name(h.get("from", "")),
                                      sender_addr=gmail.sender_addr(h.get("from", "")),
                                      subject=h.get("subject", ""), snippet=m.get("snippet", ""))
            label, reason = await mail_labels.label(self.llm, mail, today)
            self.store.add_mail(MailRow(key, email, mail.sender_name, mail.subject[:200],
                                        int(m.get("internalDate", "0")) / 1000, label, reason))
            done += 1
        if new:
            log.info("mail poll: %d new, %d labelled", len(new), done)
        self.store.prune_mail(self.clock() - 7 * 86400)
        return done

    def due_warnings(self) -> list[MailRow]:
        """Urgent mail that arrived since she started, under 2 h old, not yet announced."""
        since = max(self.started, self.clock() - ANNOUNCE_WITHIN_S)
        return self.store.mail_since(since, ("urgent",), ("new",))

    def may_interrupt(self) -> bool:
        now = dt.datetime.fromtimestamp(self.clock())
        return not (self.gaming or self.orch.busy or
                    in_quiet_hours(now, self.cfg.get("quiet_from", "23:00"), self.cfg.get("quiet_to", "07:00")))

    async def warn(self) -> bool:
        rows = self.due_warnings()
        if not rows or not self.may_interrupt():
            return False
        mails = [briefing.Mail(r.key, r.sender, r.subject, r.label, dt.datetime.fromtimestamp(r.received))
                 for r in rows]
        sentences = briefing.urgent_sentences(mails)
        if sentences:
            await self.orch.report(sentences, "Urgent mail", [f"{m.sender}: {m.subject}" for m in mails],
                                   alert=True)
        self.store.set_mail_state([r.key for r in rows], "announced")
        return True

    async def _run(self) -> None:
        period = 60 * float(self.cfg.get("poll_minutes", 5))
        last_poll = self.clock() - period + 90  # first poll 90 s in: her start-up loads come first
        while True:
            try:
                if self.clock() - last_poll >= period and not self.gaming and not self.orch.busy:
                    await self.poll()
                    last_poll = self.clock()
                await self.warn()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("mail watch: %s", type(e).__name__)
            await asyncio.sleep(30)  # warnings held back by quiet hours or gaming go out when allowed


class Briefer:
    """What the briefing reads: 72 h of calendar, labelled mail and toasts, today's reminders."""

    def __init__(self, store: Store):
        self.store = store

    async def events(self, now: dt.datetime) -> list[briefing.Event]:
        emails = _google.accounts()
        if not emails:
            return []
        start, end = now.replace(hour=0, minute=0, second=0, microsecond=0), now + briefing.DEADLINE_WINDOW
        done, problems = await _google.each_account(
            calendar.API, calendar.TRANSPORT, lambda c, auth, _e: calendar.fetch_events(c, auth, start, end), emails)
        for p in problems:
            log.warning("briefing calendar: %s", p.split(":")[0])
        out, seen = [], set()
        for _email, (got, _n) in done:
            for _cal, ev in got:
                uid = ev.get("iCalUID") or ev.get("id")
                if ev.get("status") == "cancelled" or uid in seen:
                    continue
                seen.add(uid)
                s = ev.get("start", {})
                if "dateTime" in s:
                    t, all_day = dt.datetime.fromisoformat(s["dateTime"]).astimezone().replace(tzinfo=None), False
                else:
                    t, all_day = dt.datetime.fromisoformat(s.get("date", "1970-01-01")), True
                out.append(briefing.Event(uid, ev.get("summary") or "an event", t, all_day))
        return out

    async def run(self, now: dt.datetime | None = None) -> briefing.Briefing:
        now = now or dt.datetime.now()
        try:
            events = await self.events(now)
        except Exception as e:  # the calendar failing must not lose the mail and reminders
            log.warning("briefing calendar failed: %s", type(e).__name__)
            events = []
        rows = self.store.mail_since(now.timestamp() - 86400, BRIEF_LABELS, ("new", "announced"))
        mails = [briefing.Mail(r.key, r.sender, r.subject, r.label, dt.datetime.fromtimestamp(r.received))
                 for r in rows]
        reminders = [briefing.Reminder(str(r.id), r.text, dt.datetime.fromtimestamp(r.due))
                     for r in self.store.pending_reminders()]
        notices = [briefing.Notice(r.key, r.app, r.title, r.label, dt.datetime.fromtimestamp(r.received))
                   for r in self.store.notif_since(now.timestamp() - 86400, NOTICE_LABELS, ("new",))]
        b = briefing.compose(now, events, mails, reminders, seed=int(now.timestamp()) // 60, notices=notices)
        self.store.set_mail_state(b.mail_keys, "briefed")
        self.store.set_notif_state(b.notice_keys, "briefed")
        log.info("briefing: %d items", len(b.items))
        return b


class MorningBriefing:
    """Once a day: on the first start after 06:00, or at 07:30 if already running."""
    KEY = "morning_briefed"

    def __init__(self, store: Store, briefer: Briefer, orch, vram, cfg: dict,
                 clock: Callable[[], float] = time.time, ready: Callable[[], bool] = lambda: True):
        self.store, self.briefer, self.orch, self.vram, self.cfg = store, briefer, orch, vram, cfg
        self.clock, self.ready = clock, ready
        self.started = dt.datetime.fromtimestamp(clock())
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="morning")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def due(self) -> bool:
        now = dt.datetime.fromtimestamp(self.clock())
        if self.store.get_kv(self.KEY) == now.date().isoformat():
            return False
        after, at = _hm(self.cfg.get("morning_after", "06:00")), _hm(self.cfg.get("morning_at", "07:30"))
        if now.time() < after:
            return False
        first_seen = self.started if self.started.date() == now.date() else now.replace(hour=0, minute=0)
        when = (dt.datetime.combine(now.date(), at) if first_seen.time() < after
                else first_seen + dt.timedelta(seconds=10))
        if now < when:
            return False
        quiet = in_quiet_hours(now, self.cfg.get("quiet_from", "23:00"), self.cfg.get("quiet_to", "07:00"))
        gaming = bool(self.vram is not None and self.vram.gaming)
        return not (gaming or quiet or self.orch.busy) and self.ready()

    async def fire(self) -> None:
        self.store.set_kv(self.KEY, dt.datetime.fromtimestamp(self.clock()).date().isoformat())
        b = await self.briefer.run(dt.datetime.fromtimestamp(self.clock()))
        await self.orch.report(b.sentences, "Morning status report", [i.title for i in b.items])

    async def _run(self) -> None:
        while True:
            try:
                if self.due():
                    await self.fire()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("morning briefing: %s", type(e).__name__)
            await asyncio.sleep(15)

