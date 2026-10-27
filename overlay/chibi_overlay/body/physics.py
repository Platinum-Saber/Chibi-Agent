"""Where her feet are and how she moves, in desktop px.

A port of Saber-Theme's ``MascotPhysics`` (see tests/test_physics.py). Pure
Python. Speeds and constants are px/s on a 96-dpi desktop, multiplied by
``scale`` (the monitor's DPI scale) to get real px. The floor is whatever
``floor_y(x)`` says (the taskbar top, or a title bar later); the walls are the
edges of the monitors, so she flies from one monitor to the next where they
touch, and the ceiling stops her head at the top of the monitor she's on.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import NamedTuple

GRAVITY = 2600.0
MAX_SPEED = 4200.0
WALL_BOUNCE = 0.55
FLOOR_BOUNCE = 0.32
FLOOR_FRICTION = 0.6
SETTLE_SPEED = 260.0
"""Below this bounce speed (px/s at 96 dpi) she stops bouncing and stands."""


class Rect(NamedTuple):
    """A monitor (or work area) in virtual-desktop px; right and bottom are exclusive."""

    left: float
    top: float
    right: float
    bottom: float


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Physics:
    def __init__(
        self,
        scale: float,
        monitors: Sequence[Rect],
        floor_y: Callable[[float], float],
        half_width: float = 0.0,
        head_height: float = 0.0,
    ) -> None:
        if not monitors:
            raise ValueError("at least one monitor rect is needed")
        self.scale = scale
        self.monitors = list(monitors)
        self.floor_y = floor_y
        self.half_width = half_width
        """px from her feet to her side, so walls keep her whole body on screen."""
        self.head_height = head_height
        """px from her feet to the top of her head, so the ceiling stops her head."""
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.airborne = False
        self._peak_fall = 0.0
        """Fastest downward speed of the current fall, for the landing reaction (px/s at 96 dpi)."""
        self._hit_floor = False
        self.top_y = 0.0
        """Highest point (smallest y) of the current flight: how far she dropped when she lands."""
        self.wall_hit = 0.0
        """Fastest sideways speed she hit a wall (screen edge) at this flight (px/s at 96 dpi)."""

    def place(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.airborne = False

    def throw_at(self, vx: float, vy: float) -> None:
        """Let go at ``vx``, ``vy`` (px/s): she flies, bounces off walls and falls to the floor."""
        cap = MAX_SPEED * self.scale
        self.vx = _clamp(vx, -cap, cap)
        self.vy = _clamp(vy, -cap, cap)
        self.airborne = True
        self._peak_fall = 0.0
        self._hit_floor = False
        self.top_y = self.y
        self.wall_hit = 0.0

    def leap_to(self, target_x: float, apex_y: float) -> bool:
        """Jumps so that her feet peak at ``apex_y`` right over ``target_x`` (px).

        Returns False (no jump) when the apex isn't above her.
        """
        rise = self.y - apex_y
        if rise <= 0:
            return False
        g = GRAVITY * self.scale
        up = math.sqrt(2 * g * rise)
        t_apex = up / g
        self.throw_at((target_x - self.x) / t_apex, -up)
        return True

    def bounds(self) -> tuple[float, float, float]:
        """(min_x, max_x, ceiling) for her feet at the current position.

        The walls are the edges of the run of monitors that touch side by side
        at her height; the ceiling is the top of the monitor she's on.
        """
        x, y = self.x, self.y
        level = sorted((r for r in self.monitors if r.top <= y <= r.bottom), key=lambda r: r.left)
        if not level:
            level = [min(self.monitors, key=lambda r: self._distance(r, x, y))]
        runs: list[list[Rect]] = []
        for r in level:
            if runs and r.left <= max(m.right for m in runs[-1]):
                runs[-1].append(r)
            else:
                runs.append([r])

        def gap(run: list[Rect]) -> float:
            lo, hi = min(r.left for r in run), max(r.right for r in run)
            return 0.0 if lo <= x <= hi else min(abs(x - lo), abs(x - hi))

        run = min(runs, key=gap)
        lo, hi = min(r.left for r in run), max(r.right for r in run)
        here = min(run, key=lambda r: self._distance(r, x, y))
        min_x, max_x = lo + self.half_width, hi - self.half_width
        return min_x, max(min_x, max_x), here.top + self.head_height

    @staticmethod
    def _distance(r: Rect, x: float, y: float) -> float:
        dx = max(r.left - x, 0.0, x - r.right)
        dy = max(r.top - y, 0.0, y - r.bottom)
        return math.hypot(dx, dy)

    def step(self, dt: float) -> float | None:
        """Advances ``dt`` seconds.

        Returns the impact speed (px/s at 96 dpi) on her first contact with the
        floor after a throw (she may still bounce), else None.
        """
        if not self.airborne:
            return None
        min_x, max_x, ceiling = self.bounds()
        self.vy += GRAVITY * self.scale * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < min_x or self.x > max_x:
            self.x = min_x if self.x < min_x else max_x
            self.wall_hit = max(self.wall_hit, abs(self.vx) / self.scale)
            self.vx = -self.vx * WALL_BOUNCE
        if self.y < ceiling:
            self.y = ceiling
            self.vy = abs(self.vy) * WALL_BOUNCE
        self.top_y = min(self.top_y, self.y)
        if self.vy > 0:
            self._peak_fall = max(self._peak_fall, self.vy / self.scale)
        floor = self.floor_y(self.x)
        if self.y >= floor and self.vy >= 0:
            self.y = floor
            impact = None if self._hit_floor else self._peak_fall
            self._hit_floor = True
            if self.vy / self.scale > SETTLE_SPEED:
                self.vy = -self.vy * FLOOR_BOUNCE
                self.vx *= FLOOR_FRICTION
            else:
                self.vx = 0.0
                self.vy = 0.0
                self.airborne = False
            return impact
        return None

    def walk_toward(self, target_x: float, speed: float, dt: float) -> bool:
        """Walks toward ``target_x`` at ``speed`` px/s (96 dpi) on the floor; returns True once there."""
        if self.airborne:
            return False
        d = target_x - self.x
        step_px = speed * self.scale * dt
        if abs(d) <= step_px:
            self.x = target_x
            return True
        self.x += math.copysign(step_px, d)
        return False
