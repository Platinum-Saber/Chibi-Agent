"""Her UI sounds (Kryo's files in config [overlay] sounds_dir) and the body events she reacts to.

`Sfx` plays the short interface sounds right here in the overlay. Voice reactions are not
played here: `reaction_for` names the event, the stage sends `React`, and the agent decides
whether she says one of chibi_shared.reactions' lines (docs/character.md -> Sounds).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .body.brain import Moment, Mood

log = logging.getLogger(__name__)

NAMES = ("startup", "appear", "hover", "click", "close")

_ENTER = {
    Mood.POUT: "pout", Mood.CRYING: "cry", Mood.HELD: "held", Mood.SOFT_LANDING: "soft_landing",
    Mood.HARD_LANDING: "hard_landing", Mood.DIZZY: "dizzy", Mood.SLEEPING: "sleep", Mood.DANCING: "dance",
}
_MOMENTS = {Moment.STRETCH: "stretch", Moment.WAVE: "wave", Moment.SIT: "sit", Moment.LOOK_AROUND: "look_around"}


def reaction_for(prev: Mood, new: Mood, moment: Moment, performing: bool) -> str | None:
    """The event a mood change is, or None. Moods the agent drives (talking, thinking for a
    turn, working) and walking or cursor moods aren't reactions."""
    if new == Mood.SURPRISED:
        return "wake" if prev == Mood.SLEEPING else "poke"
    if new == Mood.FALLING:
        return "drop" if prev == Mood.HELD else None  # a ledge vanishing under her isn't a drop
    if new == Mood.MOMENT:
        return _MOMENTS.get(moment)
    if new == Mood.HAPPY:
        return "cheer" if performing else None  # the agent's happy and long presses stay quiet
    if new == Mood.THINKING:
        return "think" if performing else None
    return _ENTER.get(new)


class Sfx:
    def __init__(self, folder: str | Path | None, volume: float = 0.6, enabled=lambda: True):
        self.enabled = enabled  # asked on each play: tray -> Sound effects (character behaviour.sounds)
        self._fx = {}
        if not folder:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect
        missing = []
        for name in NAMES:
            p = Path(folder) / f"{name}.wav"
            if not p.exists():
                missing.append(name)
                continue
            fx = QSoundEffect()
            fx.setSource(QUrl.fromLocalFile(str(p)))
            fx.setVolume(max(0.0, min(1.0, float(volume))))
            self._fx[name] = fx
        if missing:
            log.info("ui sounds: no %s in %s", ", ".join(missing), folder)

    def play(self, name: str) -> None:
        fx = self._fx.get(name)
        if fx is not None and self.enabled():
            fx.play()
