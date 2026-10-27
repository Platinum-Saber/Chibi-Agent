"""Can an unpackaged Python process read Windows toasts? Answers step 0 of the
notifications plan: the access result, whether toasts list with app, title and
body, whether the NotificationChanged event works without package identity, and
how long one poll takes.

Run it from your own terminal, not the Claude app (MSIX). Notification text is
untrusted and private, so only lengths are printed unless you pass --show.

Usage: uv run listen.py [--show] [--watch SECONDS] [--loop-check]
"""
import argparse
import asyncio
import datetime as dt
import time

from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
from winrt.windows.ui.notifications.management import UserNotificationListener


def texts(n) -> list[str]:
    binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
    return [t.text for t in binding.get_text_elements()] if binding else []


def app_name(n) -> str:
    try:
        return n.app_info.display_info.display_name
    except Exception as e:  # some toasts have no app info
        return f"<{type(e).__name__}>"


async def poll(listener, show: bool, seen: set[int]) -> None:
    t0 = time.perf_counter()
    notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    ms = (time.perf_counter() - t0) * 1000
    new = [n for n in notifs if n.id not in seen]
    print(f"poll: {len(notifs)} toasts, {len(new)} new, {ms:.1f} ms")
    now = dt.datetime.now(dt.timezone.utc)
    for n in new:
        seen.add(n.id)
        parts = texts(n)
        age = (now - n.creation_time).total_seconds() / 60
        if show:
            print(f"  #{n.id} {app_name(n)!r} {age:.0f} min ago: {parts}")
        else:
            print(f"  #{n.id} {app_name(n)!r} {age:.0f} min ago: {len(parts)} texts, lengths {[len(p) for p in parts]}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print notification text (private)")
    ap.add_argument("--watch", type=float, default=0, help="keep polling for this many seconds")
    ap.add_argument("--loop-check", action="store_true", help="report how long a poll blocks the event loop")
    args = ap.parse_args()

    listener = UserNotificationListener.current
    print("status before:", listener.get_access_status())
    status = await listener.request_access_async()
    print("request_access_async:", status)

    try:
        token = listener.add_notification_changed(lambda _s, e: print("event:", e.change_kind, e.user_notification_id))
        print("NotificationChanged: subscribed (token", token, ")")
    except Exception as e:
        print("NotificationChanged: failed:", type(e).__name__, e)

    stall = asyncio.create_task(watch_loop()) if args.loop_check else None
    seen: set[int] = set()
    await poll(listener, args.show, seen)
    end = time.monotonic() + args.watch
    while time.monotonic() < end:
        await asyncio.sleep(5)
        await poll(listener, args.show, seen)
    if stall:
        stall.cancel()
        print(f"event loop: longest stall {max_gap * 1000:.0f} ms (a 100 ms ticker ran during the polls)")


max_gap = 0.0


async def watch_loop() -> None:
    """Does the slow poll block the asyncio loop (bad: voice and the hub share it)?"""
    global max_gap
    last = time.perf_counter()
    while True:
        await asyncio.sleep(0.1)
        now = time.perf_counter()
        max_gap = max(max_gap, now - last - 0.1)
        last = now


asyncio.run(main())
