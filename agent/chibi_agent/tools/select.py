"""Per-turn tool selection: send the 4B model only the tool families this request
needs, not all ~37 schemas (10 k characters, three times the persona). Small
models pick tools better from a short list (ToolDreamer; dynamic tool dependency
retrieval, both tested on Qwen3 0.6-14B).

Selection is by family, not by tool, so multi-step flows keep their partners
(mail_list -> read_mail, search_files -> move_file). Each family has a descriptor
written for nomic-embed-text: what it does plus how Saber asks for it. Anything
unsure falls back to every tool, which is the old behaviour.
"""
from __future__ import annotations

import asyncio
import logging
import math

from . import REGISTRY

log = logging.getLogger(__name__)

# family -> (tools, descriptor for embedding)
FAMILIES: dict[str, tuple[tuple[str, ...], str]] = {
    "windows": (("open_app", "focus_window", "arrange_window", "close_window"),
                "Open, launch, start, switch to, focus, close, minimise, maximise or snap application windows. "
                "Open Spotify. Switch to Chrome. Close it. Snap this window to the left. Launch VS Code."),
    "files": (("search_files", "open_path", "move_file", "copy_file", "grep_files", "list_folder",
               "read_file", "create_folder", "create_file"),
              "Files and folders on the PC: find, open, move, rename, copy, list, read or create files and folders, "
              "search text inside documents. Where is my resume? Move report.docx to Documents. "
              "What's in my Downloads folder? Make a new folder."),
    "mail": (("mail_list", "read_mail"),
             "Email and Gmail: new mail, unread messages, inbox, search mail, read an email from someone. "
             "Any new mail? Did the professor email me? Read the second one."),
    "calendar": (("calendar_events",),
                 "Calendar, schedule and events: meetings, classes, appointments today, tomorrow or this week. "
                 "What's on today? Am I free on Friday? When is my next meeting?"),
    "memory": (("remember", "recall_memory", "forget_memory"),
               "Long-term memory about Saber: remember a fact or preference, recall what you know, forget something. "
               "Remember that my sister is called Aiko. What do you know about my project? Forget that."),
    "reminders": (("set_reminder", "list_reminders", "cancel_reminder"),
                  "Reminders, timers and alarms: remind me later, set a timer, list or cancel reminders. "
                  "Remind me at 6 to call mum. Set a timer for ten minutes. What reminders do I have?"),
    "media": (("media", "set_volume"),
              "Music, video and sound: play, pause, resume, skip or go back a track, volume up or down, mute. "
              "Pause the music. Skip this song. Turn it up. Set volume to 30."),
    "web": (("open_url", "web_search"),
            "The internet and browser: search the web, look something up online, YouTube, open a website or link. "
            "Search YouTube for lo-fi. Google the weather. Open github.com."),
    "system": (("get_time", "system_info", "focused_window", "running_apps", "network"),
               "The PC's state: time and date, battery, CPU, RAM, GPU memory, disk space, which apps are running, "
               "the window in front, internet connection, Wi-Fi, ping. How much battery is left? Is my internet down?"),
    "screen": (("look_at_screen",),
               "Look at the screen and see what Saber sees: look at this, what's this error, read what's on screen."),
    "clipboard": (("get_clipboard", "set_clipboard"),
                  "The clipboard: what did I copy, read the clipboard, copy this text, paste."),
    "shell": (("run_shell",),
              "Run a PowerShell or terminal command, a script, processes, advanced system tasks. "
              "Show which processes use the most memory, using PowerShell."),
    "recycle": (("recycle_bin", "recycle_bin_action"),
                "The Recycle Bin and trash: what's in the bin, restore a deleted file, open the Recycle Bin."),
}
# Cheap, frequent, and asked for in phrases too short to embed well ("look at this").
CORE = frozenset({"look_at_screen", "remember", "open_app"})
FAMILY_OF = {t: f for f, (ts, _) in FAMILIES.items() for t in ts}
PREV_WEIGHT = 0.7  # "read the second one" means little alone: let the last turn's topic count too
EMBED_TIMEOUT_S = 2.0


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class ToolPicker:
    def __init__(self, embed, cfg: dict | None = None):
        cfg = cfg or {}
        self.embed = embed  # memory.Embedder: (texts, query=False) -> vectors
        self.enabled = cfg.get("select", True)
        self.k = cfg.get("families", 3)
        self.margin = cfg.get("margin", 0.03)
        self.min_sim = cfg.get("min_sim", 0.35)
        self.sticky_turns = cfg.get("sticky_turns", 2)
        self.vecs: dict[str, list[float]] = {}

    async def warm(self) -> bool:
        """Embed the family descriptors once (one /api/embed call). Retried lazily
        on the next turn if Ollama wasn't up yet."""
        if not self.enabled or self.vecs:
            return bool(self.vecs)
        try:
            vecs = await asyncio.wait_for(self.embed([d for _, d in FAMILIES.values()]), EMBED_TIMEOUT_S * 5)
        except Exception as e:
            log.warning("tool selection off for now: %r", e)
            return False
        self.vecs = dict(zip(FAMILIES, vecs))
        return True

    async def query_vec(self, text: str) -> list[float] | None:
        """The turn's query vector (shared with memory recall), or None."""
        if not self.enabled:
            return None
        try:
            if not await self.warm():
                return None
            (vec,) = await asyncio.wait_for(self.embed([text], query=True), EMBED_TIMEOUT_S)
            return vec
        except Exception as e:
            log.warning("tool selection skipped: %s", "embedding took over 2 s"
                        if isinstance(e, asyncio.TimeoutError) else repr(e))
            return None

    def pick(self, vec: list[float] | None, prev: list[float] | None = None,
             sticky: set[str] = frozenset()) -> list[str] | None:
        """Tool names in registry order, or None for every tool."""
        if not self.vecs or vec is None:
            return None
        scores = {f: max(_cos(vec, v), PREV_WEIGHT * _cos(prev, v) if prev else 0.0)
                  for f, v in self.vecs.items()}
        ranked = sorted(scores, key=scores.get, reverse=True)
        if scores[ranked[0]] < self.min_sim:
            log.info("tools: all (best family %s %.2f is unsure)", ranked[0], scores[ranked[0]])
            return None
        cut = scores[ranked[min(self.k, len(ranked)) - 1]] - self.margin
        chosen = {f for f in ranked if scores[f] >= cut} | {FAMILY_OF[t] for t in sticky if t in FAMILY_OF}
        names = CORE | {t for f in chosen for t in FAMILIES[f][0]}
        log.info("tools: %s", ", ".join(f"{f} {scores[f]:.2f}" for f in ranked if f in chosen))
        # A tool with no family (new, or a test's) is always sent rather than silently hidden.
        return [n for n in REGISTRY if n in names or n not in FAMILY_OF]
