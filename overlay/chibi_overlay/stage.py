"""Her body on the desktop: brain + physics + form + what to draw, independent of windows.

Positions are virtual-desktop physical px (feet point). The per-monitor GL
windows ask the stage what to draw each frame; the primary window calls
`tick()` once per vsync. Agent messages and mouse input arrive here.
"""
from __future__ import annotations

import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from chibi_shared.protocol import (Bubble, Confirm, ConfirmResult, FormReq, Hud, Lip, MoodAck,
                                   MoodReq, OutfitReq, OutfitState, Quit, Touch, Visibility)

from .body import motion
from .body.brain import Brain, Mood
from .body.motion import Clip, RigMap
from .body.physics import Physics, Rect
from .character import Character, apply_to_map
from .env import Ground, MediaWatcher
from .outfits import Wardrobe

log = logging.getLogger(__name__)

LONG_PRESS_S = 0.6
DRAG_PX = 6
WALK_SPEED = 90.0      # px/s at 96 dpi
WANDER_SPEED = 60.0
NEAR_RADIUS = 220.0    # px at 96 dpi from her chest: the cursor counts as "near"
SERIOUS_HOLD_S = 10.0  # stay serious this long after the work ends
TRANSFORM_S = 0.6
BUBBLE_HOLD_S = 6.0
BUBBLE_AFTER_SPEECH_S = 3.0
CONFIRM_TIMEOUT_S = 60.0


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    gold: bool
    phase: float


@dataclass
class Overlays:
    bubble: str = ""
    bubble_until: float = 0.0
    hud: Hud | None = None
    confirm: Confirm | None = None
    confirm_until: float = 0.0
    # hit rects in desktop px, filled in by the drawing code each frame
    rects: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)


class Stage:
    def __init__(self, wardrobe: Wardrobe, pkg: Path, scale: float, link, own_windows: set[int]):
        self.wardrobe, self.pkg = wardrobe, pkg
        self.outfit = wardrobe.current
        self.rigs: dict[str, RigMap] = wardrobe.outfits[self.outfit].load_maps(pkg)
        self.rig_paths: dict[str, str] = dict(wardrobe.outfits[self.outfit].rigs)  # form -> model3.json
        self.outfit_gen = 0  # bumped on each change; the windows reload their puppets
        self.character = Character()  # Kryo's customization (tray -> Customize Raphael)
        self.character_gen = 0  # bumped on each apply; the windows retune their puppets
        self._outfit_next: tuple[str, dict[str, RigMap]] | None = None  # waiting for its puff
        self._outfit_to: tuple[str, dict[str, RigMap]] | None = None    # puffing now
        self.scale = scale
        self.link = link
        self.brain = Brain()
        self.ground = Ground(own_windows)
        mons = [m for m, _, _ in self.ground.mons]
        self.physics = Physics(scale, mons, self.ground)
        self.home = self.ground.home()
        self.physics.place(*self.home)
        self.media = MediaWatcher()
        self.form = "chibi"
        self.form_target = "chibi"
        self.chibi_only = False  # [overlay] chibi_only: never switch to the serious form
        self.sticky = False
        self.serious_until = 0.0
        self.transform_t0: float | None = None
        self.particles: list[Particle] = []
        self.ov = Overlays()
        self.lip = 0.0
        self.lip_target = 0.0
        self.listening = False
        self.hidden = False
        self.facing_left = False
        self.cursor = (0, 0)
        self.look_at: tuple[float, float, float] | None = None  # last click: x, y (desktop px), when
        self._was_pressed = False
        self.cursor_on_her = False  # set by the window under the cursor (alpha test)
        self.size = {"chibi": (0.0, 0.0), "serious": (0.0, 0.0)}  # (height, half width) px
        self.geom: dict = {}  # rig -> puppet.Geom, measured once by the primary window
        self.last_touch = time.monotonic()
        self.press: tuple[float, float, float] | None = None  # x, y, t
        self.grab_offset = (0.0, 0.0)
        self.dragging = False
        self.long_pressed = False
        self.drag_trail: deque[tuple[float, float, float]] = deque(maxlen=8)
        self._last_ground = 0.0
        self._t = time.monotonic()
        self._quit_cb = None

    # --- what the windows draw ------------------------------------------------------------
    @property
    def feet(self) -> tuple[float, float]:
        return self.physics.x, self.physics.y

    def draw_form(self) -> str | None:
        """The form to draw now; None in the middle of a transform (particles only)."""
        if self.hidden:
            return None
        if self.transform_t0 is not None and abs(time.monotonic() - self.transform_t0 - TRANSFORM_S / 2) < 0.08:
            return None
        return self.form

    def clip(self, form: str) -> Clip:
        return self.rigs[form].clip(self.brain.mood, self.brain.moment)

    def params(self, t: float) -> dict[str, float]:
        """Procedural parameters layered over the clip (saved params survive Update)."""
        m = self.brain.mood
        p = {"ParamMouthOpenY": min(1.0, self.lip * 1.6)}
        if m == Mood.DANCING:  # ~110 bpm bob, beat-agnostic
            w = 2 * math.pi * 110 / 60
            p["ParamBodyAngleX"] = 8 * math.sin(w * t)
            p["ParamAngleZ"] = 6 * math.sin(w * t / 2)
        elif m == Mood.HELD:
            vx = self._drag_vx()
            p["ParamBodyAngleX"] = max(-10, min(10, -vx / (60 * self.scale)))
        elif m == Mood.SLEEPING:
            p["ParamEyeLOpen"] = p["ParamEyeROpen"] = 0.0
            p["ParamAngleY"] = -12 + 2 * math.sin(t * 1.2)
        elif m == Mood.THINKING:
            p["ParamAngleY"] = 10.0
        return p

    def gaze_target(self) -> tuple[float, float] | None:
        """Desktop px she looks at, or None to look ahead. By default she looks where Kryo last
        clicked, for a few seconds (Customize -> Behaviour: clicks / cursor / off)."""
        if self.brain.mood in (Mood.SLEEPING, Mood.DIZZY, Mood.CRYING):
            return None
        mode = self.character.behaviour.look_at
        if mode == "cursor":
            return self.cursor
        if mode == "clicks" and self.look_at is not None:
            x, y, t = self.look_at
            if time.monotonic() - t < self.character.behaviour.look_hold_s:
                return x, y
        return None

    # --- per frame --------------------------------------------------------------------------
    def tick(self, cursor: tuple[int, int], pressed: bool = False) -> None:
        """One frame. `pressed`: a mouse button is down anywhere (a new press is a click she looks at)."""
        now_s = time.monotonic()
        dt = min(now_s - self._t, 0.05)
        self._t = now_s
        now = int(now_s * 1000)
        self.cursor = cursor
        if pressed and not self._was_pressed:
            self.look_at = (cursor[0], cursor[1], now_s)
        self._was_pressed = pressed
        b, ph = self.brain, self.physics

        if now_s - self._last_ground > 0.1:
            self.ground.refresh()
            self._last_ground = now_s
        self.ground.feet_y = ph.y

        # input-driven states
        if self.press and not self.dragging and not self.long_pressed \
                and now_s - self.press[2] > LONG_PRESS_S:
            self.long_pressed = True
            b.long_press(now)
            self.last_touch = now_s

        # body
        h, hw = self.size[self.form]
        ph.half_width, ph.head_height = hw, h
        if not self.dragging:
            impact = ph.step(dt)
            if impact is not None:
                b.land(impact, now)
            if not ph.airborne:
                floor = self.ground(ph.x)
                if floor > ph.y + 1:
                    ph.throw_at(0.0, 0.0)  # what she stood on moved away: fall
                elif ph.y - 40 * self.scale < floor < ph.y - 1:
                    ph.y = floor
        hx, hy = self.home
        b.away_from_home = abs(ph.x - hx) > 30 * self.scale or abs(ph.y - hy) > 2
        if b.mood == Mood.WALKING and not ph.airborne:
            self.facing_left = hx < ph.x
            if ph.walk_toward(hx, WALK_SPEED, dt) and abs(ph.y - hy) <= 2:
                b.arrived(now)
        elif b.mood == Mood.WANDER and not ph.airborne:
            target = hx + b.wander_px * self.scale
            self.facing_left = target < ph.x
            if ph.walk_toward(target, WANDER_SPEED, dt):
                b.arrived(now)

        # cursor near her (hovering close) -> she reaches for it
        cx, cy = cursor
        chest = (ph.x, ph.y - h * 0.6)
        near = math.hypot(cx - chest[0], cy - chest[1]) < NEAR_RADIUS * self.scale
        if near and not self.cursor_on_her and not self.dragging:
            b.cursor_near(now)
            self.last_touch = now_s
        else:
            if not near:
                b.cursor_left()
            if b.mood == Mood.CURSOR_NEAR:
                b.cursor_gone(now)

        b.tick(now, quiet_for_ms=int((now_s - self.last_touch) * 1000), music=self.media.playing)

        # form
        if b.mood in motion.SERIOUS_MOODS:
            self.serious_until = now_s + SERIOUS_HOLD_S
        want = "chibi" if self.chibi_only else self.form_target if self.sticky else (
            "serious" if now_s < self.serious_until or self.ov.confirm else "chibi")
        if (want != self.form or self._outfit_next) and self.transform_t0 is None and not self.dragging:
            self._outfit_to, self._outfit_next = self._outfit_next, None  # a pending outfit rides along
            self._start_transform(want, now_s)
        self._step_transform(now_s, dt)

        # lip: fast attack, slower release; decays if the voice goes quiet
        k = 0.6 if self.lip_target > self.lip else 0.25
        self.lip += (self.lip_target - self.lip) * k
        self.lip_target *= 0.85

        if self.ov.confirm and now_s > self.ov.confirm_until:
            self._answer_confirm(False)

    def _start_transform(self, to: str, now_s: float) -> None:
        self.transform_t0 = now_s
        self._to = to
        x, y = self.feet
        h = max(self.size[self.form][0], 1)
        self.particles = [Particle(x + random.uniform(-0.3, 0.3) * h, y - random.uniform(0, 1) * h,
                                   random.uniform(-60, 60), random.uniform(-260, -80),
                                   random.random() < 0.35, random.uniform(0, 6.28))
                          for _ in range(140)]

    def _step_transform(self, now_s: float, dt: float) -> None:
        if self.transform_t0 is None:
            return
        age = now_s - self.transform_t0
        if age >= TRANSFORM_S / 2 and self.form != self._to:
            self.form = self._to
            log.info("form -> %s", self.form)
        if age >= TRANSFORM_S / 2 and self._outfit_to:
            self._wear(*self._outfit_to)
            self._outfit_to = None
        for p in self.particles:  # spiral up
            p.phase += dt * 6
            p.x += (p.vx + 80 * math.sin(p.phase)) * dt * self.scale
            p.y += p.vy * dt * self.scale
        if age >= TRANSFORM_S:
            self.transform_t0 = None
            self.particles = []

    # --- outfits -----------------------------------------------------------------------------
    def request_outfit(self, name: str) -> None:
        """Queue a change of outfit; `tick` plays it behind the puff. Bad names and missing
        files are refused here, so the windows never try to load a broken model."""
        outfit = self.wardrobe.outfits.get(name)
        if outfit is None:
            self.send_outfit_state(f"no outfit {name!r}")
            return
        heading_to = self._outfit_to[0] if self._outfit_to else self.outfit
        if name == heading_to:
            self._outfit_next = None
            self.send_outfit_state()
            return
        missing = outfit.missing_models()
        if missing:
            self.send_outfit_state(f"{name}: model not found: {', '.join(missing)}")
            return
        try:
            maps = outfit.load_maps(self.pkg)
        except (OSError, ValueError) as e:  # tomllib.TOMLDecodeError is a ValueError
            self.send_outfit_state(f"{name}: bad rig map: {e}")
            return
        self._outfit_next = (name, maps)

    def _wear(self, name: str, maps: dict[str, RigMap]) -> None:
        """Midway through the puff: swap the maps and model paths; the windows reload."""
        self.outfit, self.rigs = name, self._tweaked(name, maps)
        self.rig_paths = dict(self.wardrobe.outfits[name].rigs)
        self.geom = {}
        self.outfit_gen += 1
        log.info("outfit -> %s", name)
        self.send_outfit_state()

    # --- customization (tray -> Customize Raphael; character.py) -------------------------------------
    def apply_character(self, ch: Character) -> None:
        """Kryo's customization, live: brain timings and the chibi rig map's overrides. A size
        change re-measures her (the outfit reload path); character_gen makes the windows
        retune their puppets (sprite sequences, eye follow, blink, effects)."""
        old_height = self.rigs["chibi"].height_dip
        self.character = ch
        b = ch.behaviour
        self.brain.sleep_after_ms = int(b.sleep_after_s * 1000)
        lo = int(b.moment_min_s * 1000)
        self.brain.moment_gap_ms = (lo, max(lo + 1, int(b.moment_max_s * 1000)))
        try:
            self.rigs = self._tweaked(self.outfit, self.wardrobe.outfits[self.outfit].load_maps(self.pkg))
        except (OSError, ValueError) as e:  # tomllib.TOMLDecodeError is a ValueError
            log.warning("customize: can't reload the rig map for %s: %s", self.outfit, e)
        if self.rigs["chibi"].height_dip != old_height:
            self.geom = {}
            self.outfit_gen += 1
        self.character_gen += 1

    def _tweaked(self, outfit: str, maps: dict[str, RigMap]) -> dict[str, RigMap]:
        """The chibi map with Kryo's size and clip overrides for this outfit."""
        return {**maps, "chibi": apply_to_map(maps["chibi"], self.character.outfits.get(outfit))}

    def send_outfit_state(self, error: str = "") -> None:
        self.link.send(OutfitState(outfit=self.outfit, outfits=self.wardrobe.names,
                                   ok=not error, error=error))

    def transform_progress(self) -> float | None:
        if self.transform_t0 is None:
            return None
        return (time.monotonic() - self.transform_t0) / TRANSFORM_S

    # --- agent messages ---------------------------------------------------------------------
    def on_message(self, msg) -> None:
        now_s = time.monotonic()
        now = int(now_s * 1000)
        if isinstance(msg, Lip):
            self.lip_target = max(0.0, min(1.0, msg.rms))
            self.brain.talk(now, 1500)
            # The voice sends lip levels at 60 Hz while audio plays: keep her words up until
            # she has finished speaking them, not just until the text finished streaming.
            if self.ov.bubble:
                self.ov.bubble_until = max(self.ov.bubble_until, now_s + BUBBLE_AFTER_SPEECH_S)
        elif isinstance(msg, Bubble):
            self.ov.bubble = msg.text
            self.ov.bubble_until = now_s + (BUBBLE_HOLD_S if msg.done else 3600)
        elif isinstance(msg, MoodReq):
            self.last_touch = now_s
            self.listening = msg.mood == "listening"
            if msg.mood == "thinking":
                self.ov.bubble, self.ov.bubble_until = "…", now_s + 3600
            elif msg.mood == "listening":
                self.ov.bubble = ""
            target = motion.AGENT_TO_BRAIN.get(msg.mood)
            ok = target is not None and self.brain.request_mood(target, now, msg.ttl_ms or None)
            self.link.send(MoodAck(req_id=msg.id, accepted=bool(ok)))
        elif isinstance(msg, FormReq):
            self.sticky = msg.sticky
            self.form_target = msg.form
            if not msg.sticky:
                self.serious_until = now_s + SERIOUS_HOLD_S if msg.form == "serious" else 0.0
        elif isinstance(msg, OutfitReq):
            self.request_outfit(msg.outfit)
        elif isinstance(msg, Hud):
            self.ov.hud = msg if (msg.title or msg.items) else None
        elif isinstance(msg, Confirm):
            self.ov.confirm = msg
            self.ov.confirm_until = now_s + CONFIRM_TIMEOUT_S
        elif isinstance(msg, ConfirmResult):  # answered elsewhere (voice/timeout): drop the panel
            if self.ov.confirm and self.ov.confirm.call_id == msg.call_id:
                self.ov.confirm = None
        elif isinstance(msg, Visibility):
            self.hidden = msg.hidden
        elif isinstance(msg, Quit) and self._quit_cb:
            self._quit_cb()

    def _answer_confirm(self, ok: bool) -> None:
        c = self.ov.confirm
        if c:
            self.link.send(ConfirmResult(call_id=c.call_id, ok=ok))
            self.ov.confirm = None

    # --- mouse (desktop physical px) ---------------------------------------------------------
    def hit_overlay(self, x: float, y: float) -> str | None:
        for name, (l, t, r, b) in self.ov.rects.items():
            if l <= x <= r and t <= y <= b:
                return name
        return None

    def press_at(self, x: float, y: float) -> None:
        hit = self.hit_overlay(x, y)
        if hit in ("yes", "no"):
            self._answer_confirm(hit == "yes")
            return
        if hit:  # bubble/HUD: swallow the click
            return
        self.press = (x, y, time.monotonic())
        self.grab_offset = (self.physics.x - x, self.physics.y - y)
        self.long_pressed = False
        self.drag_trail.clear()

    def move_to(self, x: float, y: float) -> None:
        if not self.press:
            return
        now_s = time.monotonic()
        if not self.dragging and math.hypot(x - self.press[0], y - self.press[1]) > DRAG_PX:
            self.dragging = True
            self.brain.grab(int(now_s * 1000))
            self.link.send(Touch(t="hold", x=x, y=y))
        if self.dragging:
            self.drag_trail.append((x, y, now_s))
            self.physics.place(x + self.grab_offset[0], y + self.grab_offset[1])
            self.last_touch = now_s

    def release_at(self, x: float, y: float) -> None:
        if not self.press:
            return
        now_s = time.monotonic()
        now = int(now_s * 1000)
        self.last_touch = now_s
        if self.dragging:
            vx, vy = self._drag_v()
            self.brain.release(now)
            self.physics.throw_at(vx, vy)
            self.link.send(Touch(t="drop", x=x, y=y, speed=math.hypot(vx, vy) / self.scale))
        elif not self.long_pressed:
            self.brain.poke(now)
            self.link.send(Touch(t="poke", x=x, y=y))
        self.press, self.dragging = None, False

    def _drag_v(self) -> tuple[float, float]:
        tr = [p for p in self.drag_trail if time.monotonic() - p[2] < 0.1]
        if len(tr) < 2 or tr[-1][2] == tr[0][2]:
            return 0.0, 0.0
        d = tr[-1][2] - tr[0][2]
        return (tr[-1][0] - tr[0][0]) / d, (tr[-1][1] - tr[0][1]) / d

    def _drag_vx(self) -> float:
        return self._drag_v()[0]
