"""Reminders and timers: persisted in the memory database, fired on time.

One asyncio task sleeps until the next due reminder (and wakes early when one is
added or cancelled). Reminders missed while the PC was off are announced at
start-up if they're less than 12 hours late; older ones are marked fired quietly.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from collections.abc import Awaitable, Callable

import dateparser

from .memory.store import Reminder, Store

log = logging.getLogger(__name__)
LATE_LIMIT_S = 12 * 3600
_NEXT = re.compile(r"\bnext\s+", re.I)


def parse_when(text: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """'in 20 minutes', 'at 6 pm', 'tomorrow 9am', '18:00', 'next monday 10am' -> a future time."""
    now = now or dt.datetime.now()
    settings = {"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now, "RETURN_AS_TIMEZONE_AWARE": False}
    for candidate in (text, _NEXT.sub("", text)):
        when = dateparser.parse(candidate, settings=settings)
        if when is not None:
            if when <= now and when.date() == now.date() and re.search(r"\d", candidate):
                when += dt.timedelta(days=1)  # "at 6 am" said at 7 am means tomorrow
            return when if when > now else None
    return None


def say_when(t: float, now: float | None = None) -> str:
    d, n = dt.datetime.fromtimestamp(t), dt.datetime.fromtimestamp(now or time.time())
    clock = d.strftime("%I:%M %p").lstrip("0")
    if d.date() == n.date():
        return f"today at {clock}"
    if d.date() == (n + dt.timedelta(days=1)).date():
        return f"tomorrow at {clock}"
    return d.strftime("%A %d %B at ") + clock


Announce = Callable[[Reminder, bool], Awaitable[None]]  # (reminder, late)


class Reminders:
    def __init__(self, store: Store, announce: Announce):
        self.store = store
        self.announce = announce
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="reminders")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def add(self, text: str, due: float) -> int:
        rid = self.store.add_reminder(text, due)
        self._wake.set()
        return rid

    def cancel(self, rid: int) -> None:
        self.store.set_reminder_state(rid, "cancelled")
        self._wake.set()

    def pending(self) -> list[Reminder]:
        return self.store.pending_reminders()

    async def _run(self) -> None:
        first = True
        while True:
            now = time.time()
            for r in self.store.pending_reminders():
                if r.due > now:
                    break
                late = now - r.due
                self.store.set_reminder_state(r.id, "fired")
                if late > LATE_LIMIT_S:
                    log.info("reminder %d is %.0f h late; dropped quietly", r.id, late / 3600)
                    continue
                try:
                    await self.announce(r, first and late > 60)
                except Exception:
                    log.exception("could not announce reminder %d", r.id)
            first = False
            upcoming = self.store.pending_reminders()
            delay = min(30.0, max(0.2, upcoming[0].due - time.time())) if upcoming else 30.0
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except asyncio.TimeoutError:
                pass
