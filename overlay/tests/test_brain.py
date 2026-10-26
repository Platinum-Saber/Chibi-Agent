import random

import pytest

from chibi_overlay.body import brain as b
from chibi_overlay.body.brain import Brain, Moment, Mood


@pytest.fixture
def brain() -> Brain:
    return Brain(random.Random(1))


def test_one_poke_surprises_then_returns_to_idle(brain):
    brain.poke(0)
    assert brain.mood == Mood.SURPRISED
    brain.tick(b.SURPRISE_MS - 1)
    assert brain.mood == Mood.SURPRISED
    brain.tick(b.SURPRISE_MS)
    assert brain.mood == Mood.IDLE


def test_quick_pokes_escalate_to_pout_then_crying(brain):
    brain.poke(0); brain.poke(300); brain.poke(600)
    assert brain.mood == Mood.POUT
    brain.poke(900)
    assert brain.mood == Mood.POUT
    brain.poke(1_200)
    assert brain.mood == Mood.CRYING


def test_slow_pokes_do_not_escalate(brain):
    brain.poke(0); brain.poke(2_500); brain.poke(5_000)
    assert brain.mood == Mood.SURPRISED


def test_long_press_makes_her_happy(brain):
    brain.long_press(0)
    assert brain.mood == Mood.HAPPY
    brain.tick(b.HAPPY_MS)
    assert brain.mood == Mood.IDLE


def test_grab_release_fall_and_landing_reactions(brain):
    brain.grab(0)
    assert brain.mood == Mood.HELD
    brain.poke(10)
    assert brain.mood == Mood.HELD
    brain.release(100)
    assert brain.mood == Mood.FALLING
    brain.land(400)
    assert brain.mood == Mood.SOFT_LANDING
    brain.land(500, high=True)
    assert brain.mood == Mood.HARD_LANDING  # a high drop lands hard; no more dizziness
    brain.land(600, hurt=True)
    assert brain.mood == Mood.CRYING


def test_a_flat_fall_lands_hard_whatever_the_speed_and_refuses_requests(brain):
    brain.grab(0)
    brain.release(100)
    brain.land(400, flat=True)
    assert brain.mood == Mood.HARD_LANDING
    assert not brain.request_mood(Mood.THINKING, 500)
    brain.tick(400 + b.HARD_LANDING_MS)
    assert brain.mood == Mood.IDLE


def test_walks_home_after_a_reaction_when_moved(brain):
    brain.land(0)
    brain.away_from_home = True
    brain.tick(b.SOFT_LANDING_MS)
    assert brain.mood == Mood.WALKING
    brain.arrived(2_000)
    brain.away_from_home = False
    brain.tick(2_001)
    assert brain.mood == Mood.IDLE


def test_falls_asleep_when_quiet_and_wakes_with_a_start_on_touch(brain):
    brain.tick(0, quiet_for_ms=0)
    brain.tick(1_000, quiet_for_ms=b.SLEEP_AFTER_MS)
    assert brain.mood == Mood.SLEEPING
    brain.tick(2_000, quiet_for_ms=30)
    assert brain.mood == Mood.SURPRISED


def test_dances_while_music_plays_and_stops_after(brain):
    brain.tick(0, music=True)
    assert brain.mood == Mood.DANCING
    brain.tick(10_000, quiet_for_ms=b.SLEEP_AFTER_MS * 2, music=True)
    assert brain.mood == Mood.DANCING  # no sleeping through music
    brain.tick(11_000, music=False)
    assert brain.mood == Mood.IDLE


@pytest.mark.parametrize("seed", range(20))
def test_idle_moments_come_after_a_gap_and_end(seed):
    seeded = Brain(random.Random(seed))
    seeded.tick(0)
    assert seeded.mood == Mood.IDLE
    seeded.tick(b.MOMENT_GAP_MIN_MS - 1)
    assert seeded.mood == Mood.IDLE
    t = 0
    while seeded.mood == Mood.IDLE and t < b.MOMENT_GAP_MAX_MS + 1:
        t += 100
        seeded.tick(t)
    assert seeded.mood in (Mood.MOMENT, Mood.WANDER)
    assert t >= b.MOMENT_GAP_MIN_MS
    if seeded.mood == Mood.MOMENT:
        seeded.tick(t + b.moment_ms(seeded.moment))
    else:
        assert 40.0 <= abs(seeded.wander_px) <= 120.0
        seeded.arrived(t + 1)
    assert seeded.mood == Mood.IDLE


def test_moments_are_the_desktop_set():
    assert {m.name for m in Moment} == {
        "LOOK_AROUND", "STRETCH", "ANALYSE", "SIT", "WAVE", "CURIOUS", "THINKING",
    }
    rng = random.Random(3)
    seen = set()
    brain = Brain(rng)
    t = 0
    brain.tick(t)
    for _ in range(3_000):
        t += 500
        brain.tick(t)
        if brain.mood == Mood.MOMENT:
            seen.add(brain.moment)
        elif brain.mood == Mood.WANDER:
            brain.arrived(t)
    assert seen == set(Moment)


def test_pokes_still_work_while_sleeping(brain):
    brain.tick(0)
    brain.tick(1, quiet_for_ms=b.SLEEP_AFTER_MS)
    brain.poke(2)
    assert brain.mood == Mood.SURPRISED


# Cursor: the desktop's finger (Duel/Point on the phone).

def test_near_cursor_reaction_ends_even_if_it_stays(brain):
    brain.cursor_near(0)
    assert brain.mood == Mood.CURSOR_NEAR
    for t in range(0, b.CURSOR_NEAR_MAX_MS, 500):  # the pointer rests beside her
        brain.cursor_near(t)
        brain.tick(t)
        assert brain.mood == Mood.CURSOR_NEAR
    brain.tick(b.CURSOR_NEAR_MAX_MS)
    assert brain.mood == Mood.IDLE
    brain.cursor_near(b.CURSOR_NEAR_MAX_MS + 100)  # still there: no new smile
    assert brain.mood == Mood.IDLE
    brain.cursor_left()
    brain.cursor_near(b.CURSOR_NEAR_MAX_MS + 200)  # it left and came back
    assert brain.mood == Mood.CURSOR_NEAR


def test_near_cursor_going_away_ends_it_sooner(brain):
    brain.cursor_near(0)
    brain.cursor_gone(100)
    brain.tick(100 + b.CURSOR_NEAR_LINGER_MS - 1)
    assert brain.mood == Mood.CURSOR_NEAR
    brain.tick(100 + b.CURSOR_NEAR_LINGER_MS)
    assert brain.mood == Mood.IDLE


def test_far_cursor_points_and_crossing_switches(brain):
    brain.cursor_far(0)
    assert brain.mood == Mood.CURSOR_FAR
    brain.cursor_near(100)
    assert brain.mood == Mood.CURSOR_NEAR
    brain.cursor(near=False, now=200)
    assert brain.mood == Mood.CURSOR_FAR
    brain.cursor_gone(300)
    brain.tick(300 + b.CURSOR_FAR_LINGER_MS - 1)
    assert brain.mood == Mood.CURSOR_FAR
    brain.tick(300 + b.CURSOR_FAR_LINGER_MS)
    assert brain.mood == Mood.IDLE


def test_cursor_back_during_the_reaction_does_not_extend_it(brain):
    brain.cursor_near(0)
    brain.cursor_gone(100)
    brain.cursor_near(1_000)
    brain.tick(b.CURSOR_NEAR_MAX_MS + 5_000)
    assert brain.mood == Mood.IDLE


def test_cursor_is_ignored_while_held_or_crying(brain):
    brain.grab(0)
    brain.cursor_near(10)
    assert brain.mood == Mood.HELD
    brain.release(20)
    brain.land(30, hurt=True)
    brain.cursor_far(40)
    assert brain.mood == Mood.CRYING


def test_cursor_is_ignored_while_working_for_the_agent(brain):
    brain.request_mood(Mood.WORKING, 0)
    brain.cursor_near(10)
    assert brain.mood == Mood.WORKING


def test_cursor_gone_does_nothing_outside_cursor_moods(brain):
    brain.request_mood(Mood.THINKING, 0)
    brain.cursor_gone(10)
    brain.tick(100_000)
    assert brain.mood == Mood.THINKING


def test_new_message_makes_her_glance_unless_busy(brain):
    brain.message(0)
    assert brain.mood == Mood.MOMENT
    assert brain.moment == Moment.CURIOUS
    brain.cursor_near(100)
    brain.message(200)
    assert brain.mood == Mood.CURSOR_NEAR


# Talking.

def test_talks_until_quiet_without_sleeping_or_timing_out(brain):
    brain.talk(0, 30_000)
    assert brain.mood == Mood.TALKING
    brain.tick(29_999, quiet_for_ms=b.SLEEP_AFTER_MS)
    assert brain.mood == Mood.TALKING
    brain.quiet(29_999)
    assert brain.mood == Mood.IDLE


def test_talking_ends_when_its_time_limit_passes(brain):
    brain.talk(0, 1_000)
    brain.talk(800, 1_000)  # still speaking: extends the limit
    brain.tick(1_799)
    assert brain.mood == Mood.TALKING
    brain.tick(1_800)
    assert brain.mood == Mood.IDLE


def test_talking_interrupts_moments_and_wander_but_not_sulking_or_being_held(brain):
    brain.message(0)
    brain.talk(100, 10_000)
    assert brain.mood == Mood.TALKING
    brain.quiet(200)
    brain.poke(300); brain.poke(400); brain.poke(500)
    brain.talk(600, 10_000)
    assert brain.mood == Mood.POUT
    brain.quiet(700)
    assert brain.mood == Mood.POUT
    brain.grab(800)
    brain.talk(900, 10_000)
    assert brain.mood == Mood.HELD


# Agent requests.

@pytest.mark.parametrize("mood", [Mood.THINKING, Mood.TALKING, Mood.WORKING, Mood.ALERT])
def test_request_mood_holds_until_the_next_request(brain, mood):
    assert brain.request_mood(mood, 0) is True
    assert brain.mood == mood
    assert brain.since == 0
    brain.tick(b.SLEEP_AFTER_MS * 2, quiet_for_ms=b.SLEEP_AFTER_MS * 2)
    assert brain.mood == mood  # no sleeping or idle moments meanwhile
    assert brain.request_mood(Mood.IDLE, b.SLEEP_AFTER_MS * 2) is True
    assert brain.mood == Mood.IDLE


def test_request_mood_ttl_ends_it(brain):
    assert brain.request_mood(Mood.ALERT, 0, ttl_ms=5_000)
    brain.tick(4_999)
    assert brain.mood == Mood.ALERT
    brain.tick(5_000)
    assert brain.mood == Mood.IDLE


def test_requested_happy_is_a_short_reaction(brain):
    assert brain.request_mood(Mood.HAPPY, 0)
    assert brain.mood == Mood.HAPPY
    brain.tick(b.HAPPY_MS)
    assert brain.mood == Mood.IDLE


def test_request_mood_overrides_sulking_and_sleep(brain):
    brain.poke(0); brain.poke(100); brain.poke(200)
    assert brain.request_mood(Mood.THINKING, 300)
    assert brain.mood == Mood.THINKING
    brain.request_mood(Mood.IDLE, 400)
    brain.tick(500, quiet_for_ms=b.SLEEP_AFTER_MS)
    assert brain.mood == Mood.SLEEPING
    assert brain.request_mood(Mood.ALERT, 600)
    assert brain.mood == Mood.ALERT


@pytest.mark.parametrize("setup", ["held", "falling", "hard_landing"])
def test_request_mood_is_refused_until_she_lands(brain, setup):
    brain.grab(0)
    if setup != "held":
        brain.release(10)
    if setup == "hard_landing":
        brain.land(20, high=True)
    before = brain.mood
    assert brain.request_mood(Mood.TALKING, 30) is False
    assert brain.mood == before
    if setup == "falling":
        brain.land(40)
        assert brain.request_mood(Mood.TALKING, 50) is True


def test_request_idle_while_away_walks_home(brain):
    brain.request_mood(Mood.WORKING, 0)
    brain.away_from_home = True
    brain.request_mood(Mood.IDLE, 100)
    assert brain.mood == Mood.WALKING


def test_request_mood_rejects_body_moods(brain):
    with pytest.raises(ValueError):
        brain.request_mood(Mood.HELD, 0)


def test_busy_is_held_or_falling(brain):
    assert not brain.busy
    brain.grab(0)
    assert brain.busy
    brain.release(10)
    assert brain.busy
    brain.land(20, high=True)
    assert not brain.busy
