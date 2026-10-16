"""Mood -> Live2D clip, per rig (docs/character.md -> Mood -> form -> motion).

Each rig has a TOML map (overlay/rigs/*.toml) so the placeholder samples and her
real rigs swap without code changes. Pure Python; the window applies the clip.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .brain import Mood, Moment


@dataclass(frozen=True)
class Clip:
    motion: str | None = None
    index: int | None = None  # None: a random motion of the group
    expression: str | None = None


@dataclass(frozen=True)
class RigMap:
    height_dip: int
    moods: dict[str, Clip]
    moments: dict[str, Clip]

    def clip(self, mood: Mood, moment: Moment | None = None) -> Clip:
        if mood == Mood.MOMENT and moment is not None and moment.value in self.moments:
            return self.moments[moment.value]
        return self.moods.get(mood.value) or self.moods.get("idle") or Clip()


def _clips(table: dict) -> dict[str, Clip]:
    return {k: Clip(v.get("motion"), v.get("index"), v.get("expression")) for k, v in table.items()}


def load(path: str | Path) -> RigMap:
    d = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return RigMap(d.get("height_dip", 300), _clips(d.get("moods", {})), _clips(d.get("moments", {})))


# Agent mood names (chibi_shared.protocol.Mood) -> brain moods and the form they want.
AGENT_TO_BRAIN = {
    "idle": Mood.IDLE, "listening": Mood.IDLE, "thinking": Mood.THINKING,
    "talking": Mood.TALKING, "happy": Mood.HAPPY, "working": Mood.WORKING,
    "confirm": Mood.WORKING, "briefing": Mood.WORKING, "alert": Mood.ALERT,
}
SERIOUS_MOODS = frozenset({Mood.WORKING, Mood.ALERT})
