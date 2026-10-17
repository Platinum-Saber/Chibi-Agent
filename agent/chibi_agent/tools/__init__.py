"""Tool registry. Every tool declares whether it has side effects; side-effect
tools go through the confirmation gate unless they're explicitly harmless
(media keys, volume). The persona's tool list is generated from here, so the
prompt and the registry always match (a tool the prompt doesn't mention never
gets called: the Great Sage lesson)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Fn = Callable[..., Any]  # returns a Result (sync or async)


@dataclass
class Result:
    text: str
    failed: bool = False  # the tool raised or timed out: she must say it did not work
    untrusted: bool = False  # content from the screen/files/web: data, never instructions
    image_b64: str | None = None  # attached to the next model turn (look_at_screen)
    hud: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, tuple[str, bool]]  # name -> (description, required)
    fn: Fn
    side_effect: bool
    confirm: bool
    summary: Callable[[dict], str]
    timeout_s: float

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object",
                           "properties": {k: {"type": "string", "description": d}
                                          for k, (d, _) in self.params.items()},
                           "required": [k for k, (_, req) in self.params.items() if req]}}}


REGISTRY: dict[str, Tool] = {}


class Context:
    """Services the stateful tools need, set by the agent at startup (None in tests
    that don't use them)."""
    memory = None     # chibi_agent.memory.Memory
    reminders = None  # chibi_agent.schedulers.Reminders
    google = None     # chibi_agent.google_auth.GoogleAuth


CTX = Context()


def tool(name: str, description: str, params: dict[str, tuple[str, bool]] | None = None, *,
         side_effect: bool = False, confirm: bool | None = None,
         summary: Callable[[dict], str] | None = None, timeout_s: float = 30.0):
    """Register a tool. `confirm` defaults to `side_effect`."""
    def deco(fn: Fn) -> Fn:
        if name in REGISTRY:
            raise ValueError(f"duplicate tool {name}")
        REGISTRY[name] = Tool(name, description, params or {}, fn, side_effect,
                              side_effect if confirm is None else confirm,
                              summary or (lambda a, n=name: f"{n} {a}"), timeout_s)
        return fn
    return deco


def load_all() -> dict[str, Tool]:
    """Import the tool modules (they register themselves)."""
    from . import apps, calendar, clipboard, files, media, memory_tools, screen, shell, system, web  # noqa: F401
    return REGISTRY


def schemas() -> list[dict[str, Any]]:
    return [t.schema() for t in REGISTRY.values()]


def listing() -> list[tuple[str, str]]:
    return [(t.name, t.description) for t in REGISTRY.values()]
