"""Her short voice reactions to what happens to her body (docs/character.md -> Sounds).

The overlay sends `React(event)`; the agent picks one of these lines and asks the voice
process to play it from the clip cache, where every line is pre-rendered in her current voice.
Calm and formal, like the rest of Raphael; words, not gasps (F5 says words reliably).
"""
from __future__ import annotations

REACTIONS: dict[str, list[str]] = {
    "poke": ["Hm?", "Yes, Saber? What is it?", "Is something needed?"],  # F5 garbled a bare "Yes, Saber?"
    "pout": ["Saber, please stop.", "That is enough poking."],
    "cry": ["That was uncalled for.", "Please be gentle, Saber."],
    # a long press on her (Saber, 2026-10-26). Spaced syllables: F5 squeezed "Hehe" into one "he"
    "giggle": ["Hee hee.", "He he, that tickles."],
    "held": ["Oh.", "Where are we going?"],
    "drop": ["Ah."],
    "soft_landing": ["Landed."],
    "dizzy": ["Everything is spinning.", "Recalibrating balance."],
    "hard_landing": ["Ow.", "That was unnecessary."],
    "sleep": ["Entering standby.", "Resting for a moment."],
    "wake": ["I'm awake.", "Resuming."],
    "stretch": ["Mmh. Stretching."],
    "wave": ["Hello, Saber."],
    "cheer": ["Wonderful."],
    "dance": ["Let's dance."],
    "sit": ["I will sit for a while."],
    "look_around": ["Let me see."],  # not "Hm.": clips are found by slug, and "Hm?" is taken
    "think": ["Let me think."],  # F5 read "Analysing." as "And now I sing"
}

IDLE_EVENTS = frozenset({"stretch", "wave", "sit", "look_around", "sleep", "dance"})
"""Events her idle life also starts by itself: unless Saber picked them, they speak only sometimes."""


def all_lines() -> list[str]:
    seen: dict[str, None] = {}
    for lines in REACTIONS.values():
        seen.update(dict.fromkeys(lines))
    return list(seen)
