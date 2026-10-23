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


def test_looping_groups_reads_meta_loop(tmp_path):
    import json
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "a.motion3.json").write_text(json.dumps({"Meta": {"Loop": True}}))
    (tmp_path / "m" / "b.motion3.json").write_text(json.dumps({"Meta": {"Loop": False}}))
    model = tmp_path / "x.model3.json"
    model.write_text(json.dumps({"FileReferences": {"Motions": {
        "Walk": [{"File": "m/a.motion3.json"}], "Wave": [{"File": "m/b.motion3.json"}],
        "Gone": [{"File": "m/missing.motion3.json"}]}}}))
    assert motion.looping_groups(model) == {"Walk"}
    assert motion.looping_groups(tmp_path / "nope.model3.json") == frozenset()


@pytest.mark.parametrize("outfit,map_name", [("robe", "raphael_chibi.toml"), ("aniya", "aniya_chibi.toml")])
def test_chibi_map_names_exist_in_its_rig(outfit, map_name):
    """Every motion group and expression the map asks for exists in the configured rig."""
    import json
    from chibi_shared import config
    from chibi_overlay import outfits
    rig = outfits.parse(config.load()["overlay"]).outfits[outfit].rigs["chibi"]
    if not Path(rig).exists():
        pytest.skip("rig export not on this machine")
    refs = json.loads(Path(rig).read_text(encoding="utf-8-sig"))["FileReferences"]
    groups, exps = set(refs.get("Motions", {})), {e["Name"] for e in refs.get("Expressions", [])}
    m = motion.load(RIGS / map_name)
    clips = list(m.moods.values()) + list(m.moments.values())
    assert {c.motion for c in clips if c.motion} <= groups
    assert {c.expression for c in clips if c.expression} <= exps


def test_agent_moods_map_to_requestable_brain_moods():
    from chibi_overlay.body.brain import AGENT_MOODS
    assert set(motion.AGENT_TO_BRAIN.values()) <= AGENT_MOODS
