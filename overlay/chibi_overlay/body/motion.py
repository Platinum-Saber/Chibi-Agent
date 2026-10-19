"""Mood -> Live2D clip, per rig (docs/character.md -> Mood -> form -> motion).

Each rig has a TOML map (overlay/rigs/*.toml) so the placeholder samples and her
real rigs swap without code changes. Pure Python; the window applies the clip.
"""
from __future__ import annotations

import json
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


def looping_groups(model_json: str | Path) -> frozenset[str]:
    """Motion groups whose first motion3 sets Meta.Loop. live2d-py ignores the flag
    (only Idle restarts, by the SDK's idle fallback), so the puppet restarts these."""
    model = Path(model_json)
    try:
        groups = json.loads(model.read_text(encoding="utf-8-sig"))["FileReferences"].get("Motions", {})
    except (OSError, ValueError, KeyError):
        return frozenset()
    out = set()
    for name, entries in groups.items():
        try:
            meta = json.loads((model.parent / entries[0]["File"]).read_text(encoding="utf-8-sig"))["Meta"]
        except (OSError, ValueError, KeyError, IndexError):
            continue
        if meta.get("Loop"):
            out.add(name)
    return frozenset(out)


# Agent mood names (chibi_shared.protocol.Mood) -> brain moods and the form they want.
AGENT_TO_BRAIN = {
    "idle": Mood.IDLE, "listening": Mood.IDLE, "thinking": Mood.THINKING,
    "talking": Mood.TALKING, "happy": Mood.HAPPY, "working": Mood.WORKING,
    "confirm": Mood.WORKING, "briefing": Mood.WORKING, "alert": Mood.ALERT,
}
SERIOUS_MOODS = frozenset({Mood.WORKING, Mood.ALERT})
