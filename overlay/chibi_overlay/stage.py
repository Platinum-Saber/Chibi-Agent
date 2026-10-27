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
                                   MoodReq, OutfitReq, OutfitState, Quit, React, Touch, Visibility)

from .body import motion, music
from .body.brain import Brain, Moment, Mood, moment_ms
from .body.motion import Clip, RigMap
from .body.physics import Physics, Rect
from chibi_shared import paths

from .character import FILE_NAME, Character, apply_to_map, save as save_character
from .core_fx import CoreFX
from .env import Ground, MediaWatcher
from .outfits import Wardrobe
from .sounds import Sfx, reaction_for
from .wheel import POSES, PoseWheel

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
ROTATE_DEG_PER_PX = 0.5  # middle-drag on her: degrees she turns per px of horizontal drag
# the pose wheel (right-click on her): key -> (mood, moment, ms); ms None: until something ends it
PERFORM = {
    "wave": (Mood.MOMENT, Moment.WAVE, moment_ms(Moment.WAVE)),
    "cheer": (Mood.HAPPY, None, 2_000),
    "think": (Mood.THINKING, None, 6_000),
    "look_around": (Mood.MOMENT, Moment.LOOK_AROUND, moment_ms(Moment.LOOK_AROUND)),
    "stretch": (Mood.MOMENT, Moment.STRETCH, moment_ms(Moment.STRETCH)),
    "dance": (Mood.DANCING, None, 15_000),
    "sit": (Mood.MOMENT, Moment.SIT, 20_000),
    "sleep": (Mood.SLEEPING, None, None),  # until a poke, a drag or the agent wakes her
}
GRAB_LOW = 0.5  # grabbed below this fraction of her height (her waist): the "held_low" clip, if the rig has one
FLAT_IMPACT_S = 1.6  # after a flat fall: lying on the floor this long ("hard_landing"), then "hard_landing_up"
# How she lands (Saber, 2026-10-26): dropped more than HIGH_DROP of the screen's height -> the hard
# landing, less -> the soft one; tears only when thrown (let go faster than THROW_SPEED) or slammed
# into a screen edge (WALL_HURT). Speeds in px/s at 96 dpi.
HIGH_DROP = 0.5
THROW_SPEED = 1_500.0
WALL_HURT = 900.0
ANSWER_POINT_S = 2.7  # an answer opens with "answer_point" (Mixamo "Pointing", 2.77 s), then "answer"
REACT_LIP_S = 4.0  # after a React, her voice moves only her mouth: a reaction doesn't turn a stretch into talking


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
        self.chibi_only_cfg = False  # [overlay] chibi_only: never switch to the serious form
        # [overlay] auto_serious: switch to the serious form by herself for work, alerts and
        # confirms. Off (Saber): she changes form only on "serious mode" / "chibi mode".
        self.auto_serious = False
        self.sticky = False
        self.serious_until = 0.0
        self.transform_t0: float | None = None
        self.particles: list[Particle] = []
        self.ov = Overlays()
        self.lip = 0.0
        self.lip_target = 0.0
        self.core = CoreFX()  # the geometric object above her while she thinks or speaks
        self.listening = False
        self.conversation = False  # a spoken conversation: from push-to-talk until her reply ends
        self.hidden = False
        self.facing_left = False
        self.cursor = (0, 0)
        self.look_at: tuple[float, float, float] | None = None  # last click: x, y (desktop px), when
        self._style_key: tuple | None = None
        self._style = music.VIBE
        self._was_pressed = False
        self.cursor_on_her = False  # set by the window under the cursor (alpha test)
        self.size = {"chibi": (0.0, 0.0), "serious": (0.0, 0.0)}  # (height, half width) px
        self.geom: dict = {}  # rig -> puppet.Geom, measured once by the primary window
        self.last_touch = time.monotonic()
        self.press: tuple[float, float, float] | None = None  # x, y, t
        self.press_alt = False  # Alt held at the press: the drag sets her home spot
        self.grab_offset = (0.0, 0.0)
        self.dragging = False
        self.grab_low = False  # this drag picked her up below the waist
        self.fall_flat = False  # dropped while carried flat: falls lying down, lands hard
        self.landed_flat = False  # her last hard landing was a flat one (FlatImpact, then GetUp)
        self.thrown = False  # let go fast (THROW_SPEED): she cries when she lands
        self.answer_since: float | None = None  # monotonic s when talking straight after thinking began
        self._prev_mood = Mood.IDLE
        self.yaw = 0.0  # degrees she faces at rest (3D body), set by middle-dragging her; + turns her left
        self._rotate_from: tuple[float, float] | None = None  # cursor x, yaw when the middle drag began
        self.long_pressed = False
        self.wheel = PoseWheel()  # right-click on her: pick a pose
        self._wheel_hover: int | None = None
        self.sfx = Sfx(None)  # UI sounds; main.py loads Kryo's files
        self._react_key = (self.brain.mood, self.brain.since)  # a new mood (or the same one again): maybe a reaction
        self.reacting_until = 0.0
        self.drag_trail: deque[tuple[float, float, float]] = deque(maxlen=8)
        self._last_ground = 0.0
        self._t = time.monotonic()
        self._quit_cb = None
        self.bodies: dict[str, str] = {}  # [overlay.bodies]: "2d"/"3d" -> the outfit each body wears
        self._last_of: dict[str, str] = {wardrobe.outfits[self.outfit].body: self.outfit}  # body -> last outfit worn

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
        rig = self.rigs[form]
        if self.brain.mood == Mood.DANCING and (self.brain.performing or self.music_style == music.EXCITED)                 and "dancing_excited" in rig.moods:
            return rig.moods["dancing_excited"]  # EDM and the like, or picked on the wheel: the real dance
        if self.brain.mood == Mood.HELD and self.grab_low and "held_low" in rig.moods:
            return rig.moods["held_low"]  # picked up by the legs: carried, not hanging
        if self.brain.mood == Mood.FALLING and self.fall_flat and "falling_flat" in rig.moods:
            return rig.moods["falling_flat"]  # still lying flat in the air, not flung upright
        if self.brain.mood == Mood.HARD_LANDING and not self.landed_flat and "hard_landing_high" in rig.moods:
            return rig.moods["hard_landing_high"]  # a high drop upright: Mixamo "Hard Landing", feet first
        if self.brain.mood == Mood.HARD_LANDING and "hard_landing_up" in rig.moods \
                and time.monotonic() * 1000 - self.brain.since >= FLAT_IMPACT_S * 1000:
            return rig.moods["hard_landing_up"]  # flat on the floor long enough: getting up
        if self.brain.mood == Mood.TALKING and self.answer_since is not None:
            key = "answer_point" if time.monotonic() - self.answer_since < ANSWER_POINT_S else "answer"
            if key in rig.moods:
                return rig.moods[key]  # answering a question: point first, then talk
        return rig.clip(self.brain.mood, self.brain.moment)

    @property
    def headset(self) -> str:
        """Her headset (3D body, overlay3d/props.gd): "talk" (with the mic) through a spoken
        conversation, "music" while media plays, else "". Not for voice reactions, poses,
        briefings or typed chat (Saber, 2026-10-26)."""
        if self.conversation:
            return "talk"
        return "music" if getattr(self.media, "playing", False) else ""

    @property
    def music_style(self) -> str:
        """"vibe" (the default) or "excited", for what's playing; worked out once per track."""
        now = self.media.now if getattr(self.media, "playing", False) else None
        key = (now, self.character.behaviour.dance_words)
        if key != self._style_key:
            self._style_key = key
            self._style = music.style(now, self.character.behaviour.dance_words)
            if now is not None:
                log.info("music: %s -> %s", now.label, self._style)
        return self._style

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
            if self.wheel.open and self.hit_overlay(*cursor) is None and not self.cursor_on_her:
                self.close_wheel()  # a click anywhere else
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
            if b.mood == Mood.HAPPY:  # she giggles; the agent's own "happy" stays quiet (reaction_for)
                self.reacting_until = now_s + REACT_LIP_S
                self.link.send(React(event="giggle"))

        # body
        h, hw = self.size[self.form]
        ph.half_width, ph.head_height = hw, h
        if not self.dragging:
            if ph.step(dt) is not None:  # first touch of the floor
                mon = self.ground.monitor_at(ph.x, ph.y - 1)
                self.landed_flat = self.fall_flat and "hard_landing" in self.rigs[self.form].moods
                b.land(now, flat=self.landed_flat, high=ph.y - ph.top_y > (mon.bottom - mon.top) * HIGH_DROP,
                       hurt=self.thrown or ph.wall_hit >= WALL_HURT)
                self.fall_flat = self.thrown = False
            if not ph.airborne:
                floor = self.ground(ph.x)
                if floor > ph.y + 1:
                    ph.throw_at(0.0, 0.0)  # what she stood on moved away: fall
                elif ph.y - 40 * self.scale < floor < ph.y - 1:
                    ph.y = floor
        hx, hy = self.home
        b.away_from_home = abs(ph.x - hx) > 30 * self.scale or abs(ph.y - hy) > 2
        rig = self.rigs[self.form]
        if b.mood == Mood.WALKING and not ph.airborne:
            self.facing_left = hx < ph.x
            if ph.walk_toward(hx, rig.walk_dip_s(WALK_SPEED), dt) and abs(ph.y - hy) <= 2:
                b.arrived(now)
        elif b.mood == Mood.WANDER and not ph.airborne:
            target = hx + b.wander_px * self.scale
            self.facing_left = target < ph.x
            if ph.walk_toward(target, rig.walk_dip_s(WANDER_SPEED), dt):  # one walk clip: one pace
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
        if b.mood == Mood.TALKING and self._prev_mood == Mood.THINKING:
            self.answer_since = now_s  # an answer: it opens with "answer_point", then "answer"
        elif b.mood != Mood.TALKING:
            self.answer_since = None
        prev_mood = self._prev_mood
        self._prev_mood = b.mood
        if (b.mood, b.since) != self._react_key:
            self._react_key = (b.mood, b.since)
            event = reaction_for(prev_mood, b.mood, b.moment, b.performing)
            if event:
                self.reacting_until = now_s + REACT_LIP_S
                self.link.send(React(event=event, picked=b.performing))
        # the thinking core above her: while she thinks, and while she speaks (it follows her voice);
        # not for a voice reaction ("Hm?"), which is her, not the agent answering
        reacting = now_s < self.reacting_until
        self.core.update(dt, thinking=b.mood == Mood.THINKING,
                         speaking=b.mood == Mood.TALKING or (self.lip > 0.03 and not reacting),
                         level=min(1.0, self.lip * 1.6))

        # form
        if b.mood in motion.SERIOUS_MOODS:
            self.serious_until = now_s + SERIOUS_HOLD_S
        want = "chibi" if self.chibi_only else self.form_target if self.sticky else (
            "serious" if self.auto_serious and (now_s < self.serious_until or self.ov.confirm) else "chibi")
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
        if self.wheel.open:
            self.wheel.track(cursor)
            if not self.wheel.open:  # timed out
                self.close_wheel()
            elif self.wheel.hover != self._wheel_hover:
                self._wheel_hover = self.wheel.hover
                if self.wheel.hover is not None:
                    self.sfx.play("hover")

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
    @property
    def chibi_only(self) -> bool:
        """Never the serious form: config says so, or the outfit has no serious model on disk."""
        o = self.wardrobe.outfits[self.outfit]
        # one model in both forms (the 3D Rimuru / Raphael): a "transform" would only resize her
        return self.chibi_only_cfg or o.chibi_only or o.rigs["chibi"] == o.rigs["serious"]

    @property
    def panels_on_chibi(self) -> bool:
        """Her task panel and confirm buttons show beside the chibi too, unless the serious
        form comes by itself for them (auto_serious)."""
        return self.chibi_only or not self.auto_serious

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
        self._last_of[self.wardrobe.outfits[name].body] = name
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
        self.home = self._saved_home(b)
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

    def _saved_home(self, b) -> tuple[float, float]:
        """Her Alt+dragged spot while it's still on a monitor's taskbar line, else the default
        (a monitor unplugged or rescaled since)."""
        if b.home_x >= 0:
            for _, work, _ in self.ground.mons:
                if work.left <= b.home_x < work.right and abs(work.bottom - b.home_y) < 1:
                    return b.home_x, b.home_y
        return self.ground.home()

    def set_home(self, x: float) -> None:
        """Alt+drag: the taskbar spot below `x` is her home now (where she returns to when idle);
        saved with her Customize settings."""
        hw = self.size[self.form][1]
        work = self.ground.work_area_at(x)
        x = min(max(x, work.left + hw), work.right - hw)
        self.home = (x, work.bottom)
        self.character.behaviour.home_x, self.character.behaviour.home_y = self.home
        self.sfx.play("click")
        log.info("new home: %.0f, %.0f", *self.home)
        try:
            save_character(self.character, paths.DATA / FILE_NAME)
        except OSError as e:
            log.warning("can't save her home spot: %s", e)

    def _tweaked(self, outfit: str, maps: dict[str, RigMap]) -> dict[str, RigMap]:
        """The chibi map with Kryo's size and clip overrides for this outfit."""
        return {**maps, "chibi": apply_to_map(maps["chibi"], self.character.outfits.get(outfit))}

    # --- bodies: her 2D art or her 3D model, one at a time (tray / Customize switch) ------------
    @property
    def body(self) -> str:
        return self.wardrobe.outfits[self.outfit].body

    def other_body_outfit(self) -> str | None:
        """The outfit to wear for the other body: the last one worn of that kind this session (e.g.
        her ruby-eyed 3D variant), else [overlay.bodies], else the first of that kind."""
        want = "2d" if self.body == "3d" else "3d"
        name = self._last_of.get(want) or self.bodies.get(want)
        if name in self.wardrobe.outfits and self.wardrobe.outfits[name].body == want:
            return name
        return next((n for n, o in self.wardrobe.outfits.items() if o.body == want), None)

    def switch_body(self) -> str | None:
        """Change to the other body (no form change: she keeps one form). Returns the outfit."""
        name = self.other_body_outfit()
        if name is None:
            self.send_outfit_state("no outfit for the other body in [overlay.outfits]")
            return None
        self.character.outfit = name  # she starts in it next time (saved by the caller)
        self.request_outfit(name)
        return name

    def body_failed(self, why: str) -> None:
        """The 3D renderer didn't come up: wear the 2D body now (no puff; nothing is drawn)."""
        fallback = self.other_body_outfit() if self.body == "3d" else None
        if fallback is None:
            return
        log.error("3D body unavailable (%s): back to %s", why, fallback)
        self._wear(fallback, self.wardrobe.outfits[fallback].load_maps(self.pkg))
        self.send_outfit_state(f"3D body unavailable: {why}")

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
            if now_s >= self.reacting_until:  # a reaction moves her mouth, not her pose
                self.brain.talk(now, 1500)
            # The voice sends lip levels at 60 Hz while audio plays: keep her words up until
            # she has finished speaking them, not just until the text finished streaming.
            # Only while her words are still up, and not for a reaction clip: a pick-up's "Where
            # are we going?" used to bring back the last reply's expired panel.
            if self.ov.bubble and now_s < self.ov.bubble_until and now_s >= self.reacting_until:
                self.ov.bubble_until = max(self.ov.bubble_until, now_s + BUBBLE_AFTER_SPEECH_S)
        elif isinstance(msg, Bubble):
            self.ov.bubble = msg.text
            self.ov.bubble_until = now_s + (BUBBLE_HOLD_S if msg.done else 3600)
        elif isinstance(msg, MoodReq):
            self.last_touch = now_s
            self.listening = msg.mood == "listening"
            if msg.mood == "listening":  # Saber is talking to her (push-to-talk)...
                self.conversation = True
            elif msg.mood == "idle":  # ...until her reply has been spoken
                self.conversation = False
            if msg.mood == "thinking":
                self.ov.bubble = ""  # the thinking core above her shows it; no "…" text cloud
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

    def press_at(self, x: float, y: float, alt: bool = False) -> None:
        """A left press; `alt` held: dragging her sets a new home spot where she's dropped."""
        hit = self.hit_overlay(x, y)
        if hit in ("yes", "no"):
            self.sfx.play("click")
            self._answer_confirm(hit == "yes")
            return
        if hit == "wheel":
            i = self.wheel.segment_at(x, y)
            if i is not None:
                self.perform(POSES[i].key)
            elif math.hypot(x - self.wheel.centre[0], y - self.wheel.centre[1]) < self.wheel.inner:
                self.close_wheel()  # the hole: never mind
            return
        if hit:  # bubble/HUD: swallow the click
            return
        self.press = (x, y, time.monotonic())
        self.press_alt = alt
        self.grab_offset = (self.physics.x - x, self.physics.y - y)
        self.long_pressed = False
        self.drag_trail.clear()

    def move_to(self, x: float, y: float) -> None:
        if not self.press:
            return
        now_s = time.monotonic()
        if not self.dragging and math.hypot(x - self.press[0], y - self.press[1]) > DRAG_PX:
            self.dragging = True
            h = self.size[self.form][0]
            self.grab_low = h > 0 and self.grab_offset[1] < GRAB_LOW * h  # grab point's height above her feet
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
            vx, vy = (0.0, 0.0) if self.press_alt else self._drag_v()  # Alt: put down, not thrown
            self.fall_flat = self.grab_low and "held_low" in self.rigs[self.form].moods
            self.brain.release(now)
            self.physics.throw_at(vx, vy)
            self.thrown = math.hypot(vx, vy) / self.scale >= THROW_SPEED
            if self.press_alt:
                self.set_home(self.physics.x)
            self.link.send(Touch(t="drop", x=x, y=y, speed=math.hypot(vx, vy) / self.scale))
        elif not self.long_pressed:
            self.brain.poke(now)
            self.link.send(Touch(t="poke", x=x, y=y))
        self.press, self.dragging = None, False

    # --- right-click: the pose wheel -------------------------------------------------------
    def open_wheel(self) -> None:
        x, y = self.feet
        m = self.ground.monitor_at(x, y - 1)
        h, hw = self.size[self.form]
        self.wheel.show((x, y), h, hw, self.scale, (m.left, m.top, m.right, m.bottom))
        self.ov.rects["wheel"] = self.wheel.rect
        self._wheel_hover = None  # opening is silent (Kryo); closing and picking make sounds

    def close_wheel(self, picked: bool = False) -> None:
        """Close it: with the click sound for a picked pose, the close sound for never mind
        (the hole, a click elsewhere, right-click again, the timeout)."""
        if self.ov.rects.pop("wheel", None) is not None:
            self.sfx.play("click" if picked else "close")
        self.wheel.close()

    def toggle_wheel(self) -> None:
        if self.wheel.open:
            self.close_wheel()
        else:
            self.open_wheel()

    def perform(self, key: str) -> bool:
        """Play a pose Kryo picked on the wheel; False while she can't (held, falling, dizzy)."""
        self.close_wheel(picked=True)
        mood, moment, ms = PERFORM[key]
        now_s = time.monotonic()
        if not self.brain.perform(mood, int(now_s * 1000), ms, moment):
            return False
        if mood != Mood.SLEEPING:  # a pose is a touch (idle timers restart); sleep wants quiet
            self.last_touch = now_s
        log.info("pose wheel: %s", key)
        return True

    # --- middle-drag: turn her (the 3D body; the 2D art ignores it) ---------------------------
    @property
    def rotating(self) -> bool:
        return self._rotate_from is not None

    def rotate_press(self, x: float) -> None:
        self._rotate_from = (x, self.yaw)

    def rotate_move(self, x: float) -> None:
        if self._rotate_from is not None:
            x0, yaw0 = self._rotate_from
            # drag right: she turns toward her left (the screen's right), like spinning a figure
            self.yaw = (yaw0 + (x - x0) * ROTATE_DEG_PER_PX + 180.0) % 360.0 - 180.0
            self.last_touch = time.monotonic()

    def rotate_release(self) -> None:
        self._rotate_from = None

    def _drag_v(self) -> tuple[float, float]:
        tr = [p for p in self.drag_trail if time.monotonic() - p[2] < 0.1]
        if len(tr) < 2 or tr[-1][2] == tr[0][2]:
            return 0.0, 0.0
        d = tr[-1][2] - tr[0][2]
        return (tr[-1][0] - tr[0][0]) / d, (tr[-1][1] - tr[0][1]) / d

    def _drag_vx(self) -> float:
        return self._drag_v()[0]
