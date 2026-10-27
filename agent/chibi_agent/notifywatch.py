"""Windows notifications for the briefing and the thought cloud (docs/scope.md).

Read through WinRT's UserNotificationListener once Saber allows it (tray). Spike 4
(docs/spikes.md) settled the shape:
- The NotificationChanged event needs package identity, so she polls (every 60 s)
  and compares toast keys.
- One listing of ~75 toasts takes 6-9 s and stalled the asyncio loop for up to
  1.6 s, so all WinRT work runs on a worker thread.
- The action centre keeps days of toasts; the ones from before she started
  (less 2 h) are skipped, and apps in `ignore_apps` never reach the model.

New toasts are labelled one at a time like mail (mail_labels, kind
"notification"), at most `max_labels_per_poll` by the model, the rest by rules.
Toast text is untrusted: the body only goes into the labelling prompt; the store
keeps the app and the first line, and logs keep counts. She never speaks about a
toast unasked (Windows already showed it): urgent and reply toasts go to the
thought cloud and the briefing.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from chibi_shared.protocol import Cloud

from . import mail_labels
from .memory.store import NotifRow, Store

log = logging.getLogger(__name__)
BACKLOG_S = 2 * 3600
KEEP_S = 2 * 86400
CLOUD_LABELS = ("urgent", "reply")
CLOUD_MAX = 3
_ACCESS = {0: "unspecified", 1: "allowed", 2: "denied"}  # UserNotificationListenerAccessStatus


@dataclass
class Toast:
    id: int
    app: str
    title: str
    body: str
    created: float  # unix seconds

    @property
    def key(self) -> str:  # ids may repeat after a reboot; the time keeps keys apart
        return f"{self.id}:{int(self.created)}"


class WinToasts:
    """The WinRT listener, called on a worker thread (each call gets its own event loop there)."""

    @staticmethod
    def _listener():
        from winrt.windows.ui.notifications.management import UserNotificationListener
        return UserNotificationListener.current

    def _status(self) -> str:
        return _ACCESS.get(int(self._listener().get_access_status()), "unknown")

    def _request(self) -> str:
        async def ask():
            return await self._listener().request_access_async()
        return _ACCESS.get(int(asyncio.run(ask())), "unknown")

    def _list(self) -> list[Toast]:
        from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds

        async def get():
            return await self._listener().get_notifications_async(NotificationKinds.TOAST)
        out = []
        for n in asyncio.run(get()):
            try:
                binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                texts = [t.text for t in binding.get_text_elements()] if binding else []
                app = n.app_info.display_info.display_name
            except Exception:  # a toast without app info or a generic binding: nothing to label
                continue
            out.append(Toast(n.id, app, texts[0] if texts else "", " ".join(texts[1:]),
                             n.creation_time.timestamp()))
        return out

    async def status(self) -> str:
        return await asyncio.to_thread(self._status)

    async def request(self) -> str:
        return await asyncio.to_thread(self._request)

    async def list(self) -> list[Toast]:
        return await asyncio.to_thread(self._list)


class NotifyWatch:
    def __init__(self, store: Store, llm, orch, vram, hub, cfg: dict,
                 clock: Callable[[], float] = time.time, source=None):
        self.store, self.llm, self.orch, self.vram, self.hub, self.cfg = store, llm, orch, vram, hub, cfg
        self.clock, self.source = clock, source or WinToasts()
        self.started = clock()
        self.ignore = {a.casefold() for a in cfg.get("ignore_apps", [])}
        self.access = "unknown"  # allowed | denied | unspecified | unknown
        self.on_access: Callable[[], Awaitable[None]] | None = None  # Controller.push_state
        self.seen: set[str] = set()  # keys settled this run: stored, ignored or backlog
        self._cloud: list[str] | None = None
        self._task: asyncio.Task | None = None
        hub.on_connect(self._connected)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="notifywatch")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def gaming(self) -> bool:
        return bool(self.vram is not None and self.vram.gaming)

    async def refresh_access(self, ask: bool = False) -> str:
        """Reads the access state; `ask` (the tray) requests it."""
        before = self.access
        try:
            self.access = await (self.source.request() if ask else self.source.status())
        except Exception as e:
            log.warning("notification access: %s", type(e).__name__)
            self.access = "unknown"
        if self.access != before:
            log.info("notification access: %s", self.access)
            if self.on_access:
                await self.on_access()
        return self.access

    async def poll(self) -> int:
        """List toasts, label and store the new ones; returns how many were labelled."""
        if self.access != "allowed" or self.gaming:
            return 0
        toasts = await self.source.list()
        fresh = sorted((t for t in toasts if t.key not in self.seen), key=lambda t: t.created)
        known = self.store.known_notif_keys([t.key for t in fresh])
        backlog = self.started - BACKLOG_S
        today = dt.date.today().strftime("%A %d %B %Y")
        cap, asked, done = int(self.cfg.get("max_labels_per_poll", 5)), 0, 0
        for t in fresh:
            if t.key in known or t.app.casefold() in self.ignore or t.created < backlog:
                self.seen.add(t.key)
                continue
            if self.orch.busy or self.gaming:  # Kryo's turn goes first; the rest wait for the next poll
                break
            item = mail_labels.MailIn(key=t.key, sender_name=t.app, sender_addr="", subject=t.title,
                                      snippet=t.body)
            if asked < cap:
                label, reason = await mail_labels.label(self.llm, item, today, "notification")
                asked += 1
            else:  # a flood (a busy chat) must not hold Ollama for minutes
                label, reason = mail_labels.rules_fallback(item)
            self.store.add_notif(NotifRow(t.key, t.app[:80], t.title[:200], t.created, label, reason))
            self.seen.add(t.key)
            done += 1
        self.seen &= {t.key for t in toasts}  # dismissed toasts never come back
        if done:  # unseen counts the ignored and the backlog too
            log.info("notifications: %d unseen, %d labelled", len(fresh) - len(known), done)
        self.store.prune_notif(self.clock() - KEEP_S)
        return done

    def cloud_items(self) -> list[str]:
        """Newest first: urgent and reply toasts from the last day that no briefing has covered."""
        rows = self.store.notif_since(self.clock() - 86400, CLOUD_LABELS, ("new",))
        items = [f"{r.app}: {r.title}" if r.title else r.app for r in reversed(rows)]
        return list(dict.fromkeys(items))[:CLOUD_MAX]  # one per sender, however many messages

    async def push_cloud(self) -> None:
        items = self.cloud_items()
        if items != self._cloud:
            self._cloud = items
            await self.hub.send("overlay", Cloud(items=items))

    async def _connected(self, role) -> None:
        if role == "overlay" and self._cloud:
            await self.hub.send("overlay", Cloud(items=self._cloud))

    async def _run(self) -> None:
        period = float(self.cfg.get("poll_seconds", 60))
        last_poll = self.clock() - period + 120  # first poll 2 min in: her start-up loads and the mail poll go first
        await self.refresh_access()  # so the tray shows the real state from the start
        while True:
            try:
                if self.clock() - last_poll >= period and not self.gaming and not self.orch.busy:
                    if self.access != "allowed":  # Kryo may turn it on in Settings at any time
                        await self.refresh_access()
                    await self.poll()
                    last_poll = self.clock()
                await self.push_cloud()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("notification watch: %s", type(e).__name__)
            await asyncio.sleep(15)
