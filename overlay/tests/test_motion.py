from pathlib import Path

import pytest

from chibi_overlay.body import motion
from chibi_overlay.body.brain import Mood, Moment

RIGS = Path(__file__).parents[1] / "rigs"


@pytest.mark.parametrize("name", ["haru.toml", "mao.toml"])
def test_rig_maps_load_and_cover_idle(name):
    m = motion.load(RIGS / name)
    assert m.height_dip > 0
    assert m.moods["idle"].motion == "Idle"


def test_missing_mood_falls_back_to_idle():
    m = motion.load(RIGS / "mao.toml")
    assert m.clip(Mood.DIZZY) == m.moods["idle"]


def test_moment_uses_moment_table():
    m = motion.load(RIGS / "haru.toml")
    assert m.clip(Mood.MOMENT, Moment.WAVE).expression == "F05"
    assert m.clip(Mood.MOMENT, None) == m.moods["idle"]  # no "moment" mood entry


def test_every_brain_mood_has_a_clip_on_the_chibi_rig():
    m = motion.load(RIGS / "haru.toml")
    missing = [x.value for x in Mood if x != Mood.MOMENT and x.value not in m.moods]
    assert missing == []


def test_agent_moods_map_to_requestable_brain_moods():
    from chibi_overlay.body.brain import AGENT_MOODS
    assert set(motion.AGENT_TO_BRAIN.values()) <= AGENT_MOODS
