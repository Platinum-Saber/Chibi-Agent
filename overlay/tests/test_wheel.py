"""The pose wheel: right-click on her, pick one of 8 poses, she plays it."""
import math
import time

import pytest

from chibi_overlay import stage as stage_mod, wheel as wheel_mod
from chibi_overlay.body.brain import Moment, Mood
from chibi_overlay.wheel import POSES, PoseWheel

from test_stage_outfit import st  # noqa: F401  (the fixture: a stage on one 1920x1080 monitor)

MON = (0, 0, 1920, 1080)


def _at(w: PoseWheel, i: int, r: float | None = None) -> tuple[float, float]:
    """A desktop point in the middle of segment i (clockwise from the top)."""
    r = (w.outer + w.inner) / 2 if r is None else r
    a = math.radians(i * 360 / len(POSES))
    return w.centre[0] + r * math.sin(a), w.centre[1] - r * math.cos(a)


def test_eight_poses_with_sit_and_sleep():
    keys = [p.key for p in POSES]
    assert len(keys) == 8 and "sit" in keys and "sleep" in keys
    assert set(keys) == set(stage_mod.PERFORM)
    for k in keys:
        assert (wheel_mod.ICONS / f"{k}.png").exists()


def test_segments_clockwise_from_the_top():
    w = PoseWheel()
    w.show((500, 800), 400, 60, 1.0, MON)
    for i in range(len(POSES)):
        assert w.segment_at(*_at(w, i)) == i
        # either edge of the segment, just inside it
        for da in (-20, 20):
            a = math.radians(i * 45 + da)
            r = (w.outer + w.inner) / 2
            assert w.segment_at(w.centre[0] + r * math.sin(a), w.centre[1] - r * math.cos(a)) == i
    assert w.segment_at(*w.centre) is None  # the hole
    assert w.segment_at(*_at(w, 0, w.outer + 5)) is None  # outside


def test_placed_to_her_right_and_flips_at_the_edge():
    w = PoseWheel()
    w.show((500, 800), 400, 60, 1.0, MON)
    assert w.centre[0] - w.outer > 500 + 60  # clear of her, to her right
    assert w.centre[1] == pytest.approx(800 - 400 * 0.55)
    w.show((1850, 800), 400, 60, 1.0, MON)
    assert w.centre[0] + w.outer < 1850 - 60  # no room on the right: her left
    w.show((500, 150), 400, 60, 1.0, MON)  # high up: kept on the monitor
    assert w.rect[1] >= 0
    w.show((500, 1080), 100, 30, 1.0, MON)  # short and low: the name still fits under it
    assert w.rect[3] <= 1080


def test_scales_with_dpi():
    a, b = PoseWheel(), PoseWheel()
    a.show((500, 800), 400, 60, 1.0, MON)
    b.show((500, 800), 400, 60, 1.5, MON)
    assert b.outer == pytest.approx(a.outer * 1.5)


def test_closes_a_while_after_the_cursor_left(monkeypatch):
    w = PoseWheel()
    w.show((500, 800), 400, 60, 1.0, MON)
    t = [100.0]
    monkeypatch.setattr(wheel_mod.time, "monotonic", lambda: t[0])
    w.track(_at(w, 2))
    assert w.hover == 2
    w.track((10, 10))
    assert w.open and w.hover is None
    t[0] += wheel_mod.IDLE_CLOSE_S + 0.1
    w.track((10, 10))
    assert not w.open


def _open(s):
    s.physics.place(600, 900)
    s.open_wheel()
    assert s.wheel.open and s.hit_overlay(*s.wheel.centre) == "wheel"


def test_right_click_toggles_and_a_choice_closes_it(st):  # noqa: F811
    _open(st)
    st.toggle_wheel()
    assert not st.wheel.open and "wheel" not in st.ov.rects
    _open(st)
    st.press_at(*_at(st.wheel, 0))  # Wave
    assert not st.wheel.open and "wheel" not in st.ov.rects
    assert st.brain.mood == Mood.MOMENT and st.brain.moment == Moment.WAVE
    assert st.press is None  # the click picked a pose; it didn't poke or grab her


def test_the_hole_and_a_click_elsewhere_close_it(st):  # noqa: F811
    _open(st)
    st.press_at(*st.wheel.centre)
    assert not st.wheel.open
    _open(st)
    st.cursor_on_her = False
    st.tick((10, 10), pressed=True)
    assert not st.wheel.open


@pytest.mark.parametrize("key, mood, moment", [
    ("wave", Mood.MOMENT, Moment.WAVE),
    ("cheer", Mood.HAPPY, None),
    ("think", Mood.THINKING, None),
    ("look_around", Mood.MOMENT, Moment.LOOK_AROUND),
    ("stretch", Mood.MOMENT, Moment.STRETCH),
    ("dance", Mood.DANCING, None),
    ("sit", Mood.MOMENT, Moment.SIT),
    ("sleep", Mood.SLEEPING, None),
])
def test_each_pose(st, key, mood, moment):  # noqa: F811
    assert st.perform(key)
    assert st.brain.mood == mood
    if moment is not None:
        assert st.brain.moment == moment
    assert st.rigs["chibi"].clip(st.brain.mood, st.brain.moment) is not None


def test_sit_lasts_twenty_seconds(st):  # noqa: F811
    st.perform("sit")
    now = int(time.monotonic() * 1000)
    st.brain.tick(now + 19_000, quiet_for_ms=0, music=False)
    assert st.brain.moment == Moment.SIT and st.brain.mood == Mood.MOMENT
    st.brain.tick(now + 20_500, quiet_for_ms=0, music=False)
    assert st.brain.mood != Mood.MOMENT


def test_a_dance_needs_no_music(st):  # noqa: F811
    st.perform("dance")
    now = int(time.monotonic() * 1000)
    st.brain.tick(now + 5_000, quiet_for_ms=0, music=False)
    assert st.brain.mood == Mood.DANCING
    st.brain.tick(now + 15_500, quiet_for_ms=0, music=False)
    assert st.brain.mood != Mood.DANCING


def test_sleep_survives_the_cursor_and_ends_on_a_poke(st):  # noqa: F811
    st.physics.place(600, 900)
    st.perform("sleep")
    h = st.size[st.form][0]
    for _ in range(5):  # the cursor stays right beside her after the click
        st.tick((640, 900 - h * 0.6))
    assert st.brain.mood == Mood.SLEEPING
    st.press_at(600, 880)
    st.release_at(600, 880)
    assert st.brain.mood != Mood.SLEEPING


def test_refused_while_held(st):  # noqa: F811
    st.brain.grab(int(time.monotonic() * 1000))
    assert not st.perform("dance")
    assert st.brain.mood == Mood.HELD
