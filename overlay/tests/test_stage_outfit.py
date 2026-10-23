"""Changing outfits on the stage: queued, played behind the puff, keeps form/mood/facing."""
from pathlib import Path

import pytest

from chibi_overlay import outfits, stage as stage_mod
from chibi_overlay.body.brain import Mood
from chibi_overlay.body.physics import Rect
from chibi_overlay.env import Ground
from chibi_shared.protocol import FormReq, OutfitReq, OutfitState

PKG = Path(__file__).resolve().parents[1]


class FakeGround(Ground):
    def __init__(self, own):
        self.own = own
        self.mons = [(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True)]
        self.window = None
        self.feet_y = 0.0

    def refresh(self):
        pass


class FakeMedia:
    playing = False
    now = None

    def stop(self):
        pass


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def states(self):
        return [m for m in self.sent if isinstance(m, OutfitState)]


@pytest.fixture
def st(monkeypatch, tmp_path):
    monkeypatch.setattr(stage_mod, "Ground", FakeGround)
    monkeypatch.setattr(stage_mod, "MediaWatcher", FakeMedia)
    for n in ("haru", "mao"):
        (tmp_path / f"{n}.model3.json").write_text("{}")
    w = outfits.parse({
        "outfit": "robe", "chibi_map": "rigs/haru.toml", "serious_map": "rigs/mao.toml",
        "outfits": {
            "robe": {"chibi_rig": str(tmp_path / "haru.model3.json"), "serious_rig": str(tmp_path / "mao.model3.json")},
            "coat": {"chibi_rig": str(tmp_path / "mao.model3.json"), "chibi_map": "rigs/mao.toml",
                     "serious_rig": str(tmp_path / "haru.model3.json"), "serious_map": "rigs/haru.toml"},
            "cape": {"chibi_rig": str(tmp_path / "gone.model3.json"), "serious_rig": str(tmp_path / "mao.model3.json")},
        },
    })
    s = stage_mod.Stage(w, PKG, 1.0, FakeLink(), own_windows=set())
    s.size = {"chibi": (140.0, 40.0), "serious": (420.0, 90.0)}
    return s


def _run_puff(s):
    """Tick until the puff has started, then step it to the end."""
    s.tick((0, 0))
    assert s.transform_t0 is not None
    s.transform_t0 -= stage_mod.TRANSFORM_S / 2  # jump to the midpoint
    s._step_transform(s.transform_t0 + stage_mod.TRANSFORM_S / 2, 0.0)
    s.transform_t0 -= stage_mod.TRANSFORM_S
    # + a margin: with a large time.monotonic() (days of uptime) t0 + T - t0 can round below T
    s._step_transform(s.transform_t0 + stage_mod.TRANSFORM_S + 1e-3, 0.0)


def test_starts_in_the_configured_outfit(st):
    assert st.outfit == "robe"
    assert st.rig_paths["chibi"].endswith("haru.model3.json")
    assert st.rigs["serious"].height_dip == 420


def test_announces_what_she_wears(st):
    st.send_outfit_state()
    (m,) = st.link.states()
    assert m.ok and m.outfit == "robe" and m.outfits == ["robe", "coat", "cape"]


def test_unknown_outfit_is_refused(st):
    st.on_message(OutfitReq(outfit="tuxedo"))
    (m,) = st.link.states()
    assert not m.ok and "tuxedo" in m.error and m.outfit == "robe"
    assert st._outfit_next is None


def test_missing_model_is_refused(st):
    st.request_outfit("cape")
    (m,) = st.link.states()
    assert not m.ok and "gone.model3.json" in m.error
    assert st._outfit_next is None


def test_same_outfit_just_acks(st):
    st.request_outfit("robe")
    (m,) = st.link.states()
    assert m.ok and m.outfit == "robe"
    assert st._outfit_next is None


def test_switch_happens_behind_the_puff_and_keeps_her_state(st):
    st.facing_left = True
    st.brain.mood = Mood.HAPPY
    gen = st.outfit_gen
    st.on_message(OutfitReq(outfit="coat"))
    assert st.outfit == "robe" and not st.link.states()  # queued, not yet worn

    st.tick((0, 0))
    assert st.transform_t0 is not None and st.outfit == "robe"  # the puff has started
    st.transform_t0 -= stage_mod.TRANSFORM_S / 2 + 0.01
    st._step_transform(st.transform_t0 + stage_mod.TRANSFORM_S / 2 + 0.01, 0.0)

    assert st.outfit == "coat" and st.outfit_gen == gen + 1
    assert st.rig_paths["chibi"].endswith("mao.model3.json")
    assert st.rigs["chibi"].height_dip == 420
    assert st.geom == {}  # the windows re-measure the new models
    assert st.form == "chibi" and st.facing_left
    (m,) = st.link.states()
    assert m.ok and m.outfit == "coat"


def test_switch_waits_while_she_is_dragged(st):
    st.request_outfit("coat")
    st.dragging = True
    st.tick((0, 0))
    assert st.transform_t0 is None and st._outfit_next is not None
    st.dragging = False
    _run_puff(st)
    assert st.outfit == "coat" and st.transform_t0 is None


def test_switch_keeps_the_serious_form(st):
    st.on_message(FormReq(form="serious", sticky=True))
    _run_puff(st)  # the form transform
    assert st.form == "serious"
    st.request_outfit("coat")
    _run_puff(st)
    assert st.form == "serious" and st.outfit == "coat"


def test_chibi_only_never_turns_serious(st):
    st.chibi_only = True
    st.brain.mood = Mood.WORKING
    st.serious_until = 1e12
    st.on_message(FormReq(form="serious", sticky=True))
    st.tick((0, 0))
    assert st.transform_t0 is None and st.form == "chibi"


def test_serious_moods_still_switch_without_chibi_only(st):
    st.brain.mood = Mood.WORKING
    st.serious_until = 1e12
    st.tick((0, 0))
    assert st.transform_t0 is not None



def test_she_looks_where_you_click_then_ahead(st, monkeypatch):
    st.tick((100, 200), pressed=False)
    assert st.gaze_target() is None
    st.tick((300, 400), pressed=True)
    assert st.gaze_target() == (300, 400)
    st.tick((500, 500), pressed=True)  # still held: not a new click
    assert st.gaze_target() == (300, 400)
    later = st.look_at[2] + st.character.behaviour.look_hold_s + 0.1
    monkeypatch.setattr(stage_mod.time, "monotonic", lambda: later)
    assert st.gaze_target() is None
    st.character.behaviour.look_at = "cursor"
    assert st.gaze_target() == st.cursor


def test_excited_music_picks_the_excited_dance(st):
    from chibi_overlay.body.music import Track
    from chibi_overlay.body.motion import Clip
    rig = st.rigs["chibi"]
    st.rigs = {**st.rigs, "chibi": type(rig)(rig.height_dip, {**rig.moods, "dancing": Clip("DanceVibe"),
                                                                "dancing_excited": Clip("DanceExcited")}, rig.moments)}
    st.brain.mood = Mood.DANCING
    st.media.playing, st.media.now = True, Track("Clair de Lune", "Debussy")
    assert st.clip("chibi").motion == "DanceVibe"
    st.media.now = Track("Levels", "Avicii")
    assert st.clip("chibi").motion == "DanceExcited"
    st.character.behaviour.dance_words = "debussy"
    st.media.now = Track("Clair de Lune", "Debussy")
    assert st.clip("chibi").motion == "DanceExcited"
    st.brain.mood = Mood.IDLE
    assert st.clip("chibi").motion != "DanceExcited"
