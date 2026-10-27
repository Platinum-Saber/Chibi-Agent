"""Tools over her memory and reminders. All async: they run on the agent's loop,
which owns the SQLite connection (worker threads may not use it). Remembering, reminders and forgetting are all
confirmed first (Saber's call, 2026-10-17)."""
from __future__ import annotations

import time

from ..schedulers import parse_when, say_when
from . import CTX, Result, tool


@tool("remember", "Store a lasting fact about Saber.",
      {"fact": ("One short sentence, e.g. 'Saber's sister is called Nimi'", True)},
      side_effect=True)
async def remember(fact: str) -> Result:
    if CTX.memory is None:
        return Result("Memory is unavailable.")
    how = await CTX.memory.remember(fact)
    return Result(f"Remembered ({how}): {fact}")


@tool("recall_memory", "Look up what you remember.", {"topic": ("What to look up", True)})
async def recall_memory(topic: str) -> Result:
    if CTX.memory is None:
        return Result("Memory is unavailable.")
    hits = await CTX.memory.find(topic, k=8, min_sim=0.45)
    return Result("\n".join(f"- {h.text}" for h in hits) if hits else "Nothing remembered about that.")


@tool("forget_memory", "Forget facts about a topic.", {"topic": ("What to forget", True)},
      side_effect=True, summary=lambda a: f"Forget what I remember about '{a.get('topic')}'")
async def forget_memory(topic: str) -> Result:
    if CTX.memory is None:
        return Result("Memory is unavailable.")
    hits = await CTX.memory.find(topic, k=8, min_sim=0.6)
    if not hits:
        return Result("Nothing remembered about that.")
    CTX.memory.forget([h.id for h in hits])
    return Result("Forgot: " + "; ".join(h.text for h in hits))


@tool("set_reminder", "Set a reminder or timer.",
      {"text": ("What to remind about", True),
       "when": ("When, in Saber's words: 'in 20 minutes', 'at 6 pm', 'tomorrow 9am'", True)},
      side_effect=True)
async def set_reminder(text: str, when: str) -> Result:
    if CTX.reminders is None:
        return Result("Reminders are unavailable.")
    due = parse_when(when)
    if due is None:
        return Result(f"I could not understand the time '{when}'. Ask Saber for a clearer time.")
    CTX.reminders.add(text, due.timestamp())
    return Result(f"Reminder set for {say_when(due.timestamp())}: {text}")


@tool("list_reminders", "List pending reminders.")
async def list_reminders() -> Result:
    if CTX.reminders is None:
        return Result("Reminders are unavailable.")
    items = CTX.reminders.pending()
    if not items:
        return Result("No pending reminders.")
    now = time.time()
    return Result("\n".join(f"#{r.id} {say_when(r.due, now)}: {r.text}" for r in items))


@tool("cancel_reminder", "Cancel a pending reminder.",
      {"which": ("Its number from list_reminders, or words from its text", True)},
      side_effect=True)
async def cancel_reminder(which: str) -> Result:
    if CTX.reminders is None:
        return Result("Reminders are unavailable.")
    items = CTX.reminders.pending()
    w = which.strip().lstrip("#").lower()
    match = [r for r in items if str(r.id) == w] or [r for r in items if w in r.text.lower()]
    if len(match) != 1:
        return Result("No single reminder matches that; list them first." if match or items
                      else "No pending reminders.")
    CTX.reminders.cancel(match[0].id)
    return Result(f"Cancelled: {match[0].text}")
