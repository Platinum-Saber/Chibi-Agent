import tomllib

from chibi_overlay import character, sprites
from chibi_overlay.body.brain import Brain, Mood
from chibi_overlay.body.motion import Clip, RigMap


def _full() -> character.Character:
    ch = character.Character(outfit="casual_coat")
    ch.behaviour.gaze = False
    ch.behaviour.sleep_after_s = 5.0
    tw = ch.tweaks("casual_coat")
    tw.height_dip = 400
    tw.moods["walking"] = {"motion": "Dance", "expression": "happy"}
    tw.moments["wave"] = {"motion": "Wave", "expression": "neutral"}
    ch.sequences["Walk"] = {"frames": [["poses/walk_contact_left", 0.1], ["poses/walk_pass_left", 0.2]],
                            "loop": True, "effect": "music_note"}
    ch.tweaks('odd "name"').height_dip = 200  # keys that need quoting
    ch.voice = character.VoiceSettings("kokoro", "bf_emma", 1.1, 8)
    return ch


def test_round_trip(tmp_path):
    ch = _full()
    path = tmp_path / "character.toml"
    character.save(ch, path)
    tomllib.loads(path.read_text(encoding="utf-8"))  # valid TOML
    back = character.load(path)
    assert back == ch


def test_voice_is_only_written_when_chosen(tmp_path):
    ch = character.Character()
    assert "[voice]" not in character.dumps(ch)
    path = tmp_path / "c.toml"
    character.save(ch, path)
    assert character.load(path).voice is None
    assert character.parse({"voice": {"engine": "espeak", "speed": "fast"}}).voice == character.VoiceSettings()


def test_missing_or_broken_file_gives_defaults(tmp_path):
    assert character.load(tmp_path / "nope.toml") == character.Character()
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    assert character.load(bad) == character.Character()


def test_bad_values_are_skipped():
    ch = character.parse({"behaviour": {"gaze_reach": "far", "blink_min_s": 1},
                          "outfits": {"x": {"height_dip": -5, "moods": {"idle": "Wave"}}},
                          "sequences": {"Walk": {"frames": [["a", "slow"], ["b", 0.2]]}}})
    assert ch.behaviour.gaze_reach == 0.45 and ch.behaviour.blink_min_s == 1.0
    assert ch.outfits["x"].height_dip is None and ch.outfits["x"].moods == {}
    assert ch.sequences["Walk"]["frames"] == [["b", 0.2]]


def test_apply_to_map_overrides_size_and_clips():
    rig = RigMap(320, {"idle": Clip("Idle", None, "neutral"), "walking": Clip("Walk", None, "neutral")},
                 {"wave": Clip("Wave", None, "happy")})
    out = character.apply_to_map(rig, _full().outfits["casual_coat"])
    assert out.height_dip == 400
    assert out.moods["walking"] == Clip("Dance", None, "happy")
    assert out.moods["idle"] == rig.moods["idle"]
    assert out.moments["wave"] == Clip("Wave", None, "neutral")
    assert character.apply_to_map(rig, None) is rig


def test_brain_sleeps_after_the_tuned_gap():
    b = Brain()
    b.sleep_after_ms = 5_000
    b.tick(0, quiet_for_ms=4_000)
    assert b.mood != Mood.SLEEPING
    b.tick(100, quiet_for_ms=5_000)
    assert b.mood == Mood.SLEEPING


def test_sprite_model_takes_sequences_and_behaviour(tmp_path):
    from tests.test_sprites import _png  # same synthetic pack helper
    _png(tmp_path, "expressions/neutral", 140)
    m = sprites.SpriteModel(str(tmp_path), None)
    m.tune(_full())
    walk = m.sequences["Walk"]
    assert [k for k, _ in walk.frames] == ["poses/walk_contact_left", "poses/walk_pass_left"]
    assert walk.effect == "music_note" and walk.drawn_left  # drawn direction is the pack's, kept
    assert not m.gaze_on
    m._look = (500.0, 20.0)
    assert m.gaze(1.0) is None
    m.tune(character.Character())
    assert m.sequences["Walk"] == sprites.SEQUENCES["Walk"] and m.gaze_on


def test_new_fields_round_trip(tmp_path):
    ch = character.Character()
    ch.behaviour.look_at, ch.behaviour.look_hold_s = "cursor", 2.5
    tw = ch.tweaks("casual_coat")
    tw.mask, tw.sword = False, True
    ch.sequences["Sit"] = {"frames": [["poses/sit", 0.9]], "loop": True, "effect": "", "prop": "", "seat": "extras/slime"}
    path = tmp_path / "c.toml"
    character.save(ch, path)
    assert character.load(path) == ch
    assert character.parse({"behaviour": {"look_at": "everywhere"}}).behaviour.look_at == "clicks"
