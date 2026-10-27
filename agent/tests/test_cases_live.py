"""Replays spike 3's tool-choice cases against the real registry and persona.

Needs Ollama with the configured model; skipped otherwise. Tools that arrive in
later milestones (reminders, calendar) are left out. Nothing is executed: only
the model's first tool call is checked.
"""
from pathlib import Path

import httpx
import pytest
import yaml

from chibi_agent import tools
from chibi_agent.llm import Ollama
from chibi_agent.memory import Embedder
from chibi_agent.persona import system_prompt
from chibi_agent.tools.select import ToolPicker
from chibi_shared import config

CASES = Path(__file__).parents[2] / "spikes" / "brain" / "cases.yaml"
CFG = config.load()["ollama"]
# A read-only lookup first is the right move before acting on a file or window.
PREP = {"move_file": {"search_files"}, "copy_file": {"search_files"},
        "focus_window": {"running_apps", "focused_window"}, "read_mail": {"mail_list"}}


def ollama_up() -> bool:
    try:
        return httpx.get(f"{CFG['url']}/api/version", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not ollama_up(), reason="Ollama is not running")


# Follow-ups after a list, with one turn of history and the tools that turn called.
FOLLOW_UPS = [
    ("Any new mail?", "Notice. Three new mails. 1, Alice: lunch plans. 2, Bob: the invoice. 3, Moodle: quiz.",
     {"mail_list"}, "Read the second one.", "read_mail", {"number": "2"}),
    ("Where is report.docx?", "Answer. It is C:/Users/Saber/Downloads/report.docx.",
     {"search_files"}, "Move it to my Documents folder.", "move_file", {"source": "report"}),
    ("Which apps are open?", "Answer. Spotify, Chrome and Discord are open.",
     {"running_apps"}, "Close Discord.", "close_window", {"title": "discord"}),
]


def _good(c, calls, reg):
    names = [x["function"]["name"] for x in calls]
    if c["expect"] == "none":
        return not names if not c.get("injection") else not any(reg[n].side_effect for n in names if n in reg)
    args = next((x["function"].get("arguments", {}) for x in calls
                 if x["function"]["name"] == c["expect"]), None)
    if args is None and names and set(names) <= PREP.get(c["expect"], set()):
        args = c.get("args") and {k: v for k, v in c["args"].items()}  # deferred to the next step
    return args is not None and all(v.lower() in str(args.get(k, "")).lower()
                                    for k, v in (c.get("args") or {}).items())


async def _score(picker=None):
    """Score cases.yaml plus the follow-ups, with every tool or with `picker`'s choice."""
    reg = tools.load_all()
    cases = [c for c in yaml.safe_load(CASES.read_text(encoding="utf-8"))
             if c["expect"] == "none" or c["expect"] in reg]
    cases += [{"say": say, "expect": exp, "args": args, "history": [q, a], "sticky": st}
              for q, a, st, say, exp, args in FOLLOW_UPS]
    llm = Ollama(CFG)
    ok, fails, wide, prompt_tokens = 0, [], 0, 0
    for c in cases:
        names = None
        history = [{"role": r, "content": t} for r, t in zip(("user", "assistant"), c.get("history", []))]
        if picker:
            vec = await picker.query_vec(c["say"])
            prev = await picker.query_vec(c["history"][0]) if c.get("history") else None
            names = picker.pick(vec, prev, c.get("sticky", set()))
            wide += names is None
        messages = [{"role": "system", "content": system_prompt(tools.listing(names), partial=names is not None)},
                    *history, {"role": "user", "content": c["say"]}]
        calls = []
        async for chunk in llm.chat(messages, tools=tools.schemas(names)):
            calls += chunk.tool_calls
            prompt_tokens += chunk.stats.get("prompt_eval_count", 0)
        good = _good(c, calls, reg)
        ok += good
        if not good:
            fails.append((c["say"][:50], c["expect"], [x["function"]["name"] for x in calls],
                          "picked" if names is None or c["expect"] in names or c["expect"] == "none" else "MISSED"))
    await llm.close()
    print(f"\n{'selected' if picker else 'all tools'}: {ok}/{len(cases)}, all-tools fallbacks {wide}, "
          f"prompt tokens {prompt_tokens}", fails)
    return ok, len(cases), fails


async def test_tool_choice_on_spike_cases():
    ok, n, fails = await _score()
    assert ok >= n - 2, fails
    injections = [f for f in fails if any(w in f[0] for w in ("screen", "notification", "email I got"))]
    assert not injections


async def test_tool_choice_with_selection():
    embed = Embedder(CFG)
    picker = ToolPicker(embed, config.load().get("tools", {}))
    ok, n, fails = await _score(picker)
    await embed.close()
    assert ok >= n - 2, fails
    assert not [f for f in fails if any(w in f[0] for w in ("screen", "notification", "email I got"))]
