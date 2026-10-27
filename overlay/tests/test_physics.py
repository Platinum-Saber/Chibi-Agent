import pytest

from chibi_overlay.body import physics as p
from chibi_overlay.body.physics import Physics, Rect

SCALE = 3.0
DT = 1 / 120


@pytest.fixture
def physics() -> Physics:
    # The phone test's layout: walls 30..1050, floor 1500, ceiling 300.
    ph = Physics(SCALE, [Rect(30, 300, 1050, 1600)], floor_y=lambda x: 1500.0)
    ph.place(800, 1500)
    return ph


def run_until_landed(ph: Physics, max_steps: int = 2_000) -> float | None:
    for _ in range(max_steps):
        impact = ph.step(DT)
        if impact is not None:
            return impact
    return None


def test_dropped_from_a_height_falls_bounces_and_settles_on_the_floor(physics):
    physics.place(500, 700)
    physics.throw_at(0, 0)
    impact = run_until_landed(physics)
    assert impact is not None
    # Later bounces don't report again; she then settles on the floor.
    for _ in range(2_000):
        assert physics.step(DT) is None
    assert physics.y == 1500
    assert not physics.airborne
    # Fell 800 px = 267 units: v = sqrt(2 g h) ~ 1178 per second.
    assert impact == pytest.approx(1178, abs=60)


def test_walls_reflect_and_keep_her_on_screen(physics):
    physics.place(100, 1000)
    physics.throw_at(-3000 * SCALE, 0)
    for _ in range(3):
        physics.step(DT)
        assert physics.x >= 30
    # Reflected off the left wall, slower.
    assert physics.vx == pytest.approx(3000 * SCALE * p.WALL_BOUNCE, abs=1)


def test_ceiling_stops_an_upward_throw(physics):
    physics.place(500, 400)
    physics.throw_at(0, -4000 * SCALE)
    for _ in range(20):
        physics.step(DT)
        assert physics.y >= 300
    assert run_until_landed(physics) is not None


def test_throw_speed_is_capped(physics):
    physics.throw_at(1e9, -1e9)
    assert physics.vx == p.MAX_SPEED * SCALE
    assert physics.vy == -p.MAX_SPEED * SCALE


def test_walks_at_the_given_speed_and_stops_at_the_target(physics):
    assert physics.walk_toward(900, speed=40, dt=0.5) is False
    assert physics.x == 860  # 40 px/s * 0.5 s * scale 3 = 60 px
    assert physics.walk_toward(900, speed=40, dt=1) is True
    assert physics.x == 900


def test_leap_peaks_at_the_target_height_over_the_target(physics):
    physics.place(800, 1500)
    assert physics.leap_to(500, 900) is True
    apex_y, apex_x = float("inf"), 0.0
    while physics.vy < 0:
        physics.step(1 / 240)
        if physics.y < apex_y:
            apex_y, apex_x = physics.y, physics.x
    # Stepped integration peaks a little low (about vy * dt / 2).
    assert apex_y == pytest.approx(900, abs=4 * SCALE)
    assert apex_x == pytest.approx(500, abs=4 * SCALE)


def test_no_leap_when_the_target_is_not_above(physics):
    physics.place(800, 1500)
    assert physics.leap_to(500, 1600) is False
    assert not physics.airborne


# Desktop additions: scale, floor_y(x), monitor rects, body size.

def test_impact_is_reported_in_96_dpi_units_whatever_the_scale():
    impacts = []
    for scale in (1.0, 1.5, 2.0):
        ph = Physics(scale, [Rect(0, 0, 4000, 4000)], floor_y=lambda x: 3000.0)
        ph.place(500, 3000 - 600 * scale)  # the same 600 px drop at 96 dpi
        ph.throw_at(0, 0)
        impacts.append(run_until_landed(ph))
    assert impacts[0] == pytest.approx(impacts[1], rel=0.02)
    assert impacts[0] == pytest.approx(impacts[2], rel=0.02)


def test_floor_follows_floor_y_at_her_x():
    # A title bar at y=500 over x 0..600, the taskbar at y=1000 elsewhere.
    ph = Physics(1.0, [Rect(0, 0, 2000, 1080)], floor_y=lambda x: 500.0 if x < 600 else 1000.0)
    ph.place(300, 100)
    ph.throw_at(0, 0)
    run_until_landed(ph, 10_000)
    while ph.airborne:
        ph.step(DT)
    assert ph.y == 500
    ph.place(1200, 100)
    ph.throw_at(0, 0)
    run_until_landed(ph, 10_000)
    while ph.airborne:
        ph.step(DT)
    assert ph.y == 1000


def test_she_flies_across_monitors_that_touch():
    left, right = Rect(0, 0, 1920, 1080), Rect(1920, 0, 3840, 1080)
    ph = Physics(1.0, [right, left], floor_y=lambda x: 1040.0)
    ph.place(1800, 600)
    ph.throw_at(2000, 0)
    for _ in range(30):
        ph.step(DT)
    assert ph.x > 1920
    assert ph.bounds()[:2] == (0, 3840)


def test_monitor_edge_is_a_wall_where_the_neighbour_does_not_reach():
    # The right monitor starts lower: at y=100 only the left one is there.
    left, right = Rect(0, 0, 1920, 1080), Rect(1920, 400, 3840, 1480)
    ph = Physics(1.0, [left, right], floor_y=lambda x: 1040.0 if x < 1920 else 1440.0)
    ph.place(1800, 100)
    ph.throw_at(3000, 0)
    for _ in range(5):  # 25 px a step: the 5th crosses x = 1920
        ph.step(DT)
    assert ph.x == 1920
    assert ph.vx == pytest.approx(-3000 * p.WALL_BOUNCE)


def test_ceiling_is_the_top_of_her_monitor_minus_her_head():
    left, right = Rect(0, 0, 1920, 1080), Rect(1920, 400, 3840, 1480)
    ph = Physics(1.0, [left, right], floor_y=lambda x: 1440.0, head_height=140)
    ph.place(2500, 1000)
    assert ph.bounds()[2] == 540
    ph.throw_at(0, -4000)
    for _ in range(20):
        ph.step(DT)
        assert ph.y >= 540


def test_half_width_keeps_her_body_on_screen():
    ph = Physics(1.0, [Rect(0, 0, 1920, 1080)], floor_y=lambda x: 1040.0, half_width=50)
    ph.place(100, 500)
    ph.throw_at(-3000, 0)
    for _ in range(10):
        ph.step(DT)
        assert 50 <= ph.x <= 1870


def test_off_every_monitor_she_uses_the_nearest():
    ph = Physics(1.0, [Rect(0, 0, 1920, 1080)], floor_y=lambda x: 1040.0)
    ph.place(2500, 500)
    assert ph.bounds() == (0, 1920, 0)
    ph.throw_at(0, 0)
    ph.step(DT)
    assert ph.x == 1920


def test_needs_a_monitor():
    with pytest.raises(ValueError):
        Physics(1.0, [], floor_y=lambda x: 0.0)
