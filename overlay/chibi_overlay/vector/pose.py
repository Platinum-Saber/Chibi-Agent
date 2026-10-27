"""Everything the vector rig needs for one frame (svg-rig branch, step 1).

Ported in spirit from the Saber-Theme mascot's Pose: numbers blend, variants
(eyes, mouth, brows, effects) switch. Rig units: the box is 100 x 140, feet at
(50, 140), y down. Angles are degrees; arm and leg angles are outward from
hanging straight down. Pure Python, unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import Enum


class Eyes(Enum):
    OPEN = "open"        # calm, half-lidded; `lid` droops or widens it
    CLOSED = "closed"    # a soft downward curve (blink, sleep)
    HAPPY = "happy"      # ^ ^
    SQUEEZE = "squeeze"  # > <
    DIZZY = "dizzy"      # @ @
    BLANK = "blank"      # white, no iris (shock)


class Brows(Enum):
    NONE = "none"
    CALM = "calm"
    ANGRY = "angry"
    WORRIED = "worried"
    RAISED = "raised"


class Mouth(Enum):
    NEUTRAL = "neutral"  # a short line
    SMILE = "smile"
    FROWN = "frown"
    SHOCK = "shock"      # triangle
    WAIL = "wail"
    POUT = "pout"
    OPEN = "open"


REST_ARM = 14.0
NUMBERS = ("body_tilt", "head_tilt", "head_turn", "head_nod", "gaze_x", "gaze_y", "lid",
           "arm_l", "arm_r", "leg_l", "leg_r", "squash", "lift", "blush", "mouth_open",
           "hair_sway", "halo_glow", "orb")


@dataclass(frozen=True)
class Pose:
    body_tilt: float = 0.0
    head_tilt: float = 0.0
    head_turn: float = 0.0   # -1 (her right, viewer's left) .. 1: shifts the face in the hood
    head_nod: float = 0.0    # -1 up .. 1 down
    gaze_x: float = 0.0      # iris inside the eye, -1..1
    gaze_y: float = 0.0
    lid: float = 0.0         # OPEN eyes: -1 wide .. 0 calm half-lid .. 1 nearly shut
    arm_l: float = REST_ARM  # viewer's left (her bare arm)
    arm_r: float = REST_ARM  # viewer's right (the sleeve)
    leg_l: float = 0.0
    leg_r: float = 0.0
    squash: float = 1.0      # vertical scale around the feet
    lift: float = 0.0        # off the ground, rig units
    blush: float = 0.0
    mouth_open: float = 0.0  # lip sync, 0..1
    hair_sway: float = 0.0   # -1..1, bends the long hair's ends
    halo_glow: float = 0.0   # 0 dim (chibi) .. 1 bright
    orb: float = 0.0         # 0..1, the analyse orb between her hands
    eyes: Eyes = Eyes.OPEN
    brows: Brows = Brows.NONE
    mouth: Mouth = Mouth.NEUTRAL
    tears: bool = False
    zzz: bool = False
    sweat: bool = False
    dots: bool = False       # thinking "..."
    alert: bool = False      # "!" above her
    sparkles: bool = False
    dizzy: bool = False      # circling stars

    def lerp(self, to: Pose, t: float) -> Pose:
        """Numbers move `t` of the way; variants switch at the halfway point."""
        base = to if t >= 0.5 else self
        return replace(base, **{n: getattr(self, n) + (getattr(to, n) - getattr(self, n)) * t
                                for n in NUMBERS})

    def approach(self, to: Pose, t: float) -> Pose:
        """Per-frame easing: numbers move `t` of the way, variants switch at once."""
        nums = {n: getattr(self, n) + (getattr(to, n) - getattr(self, n)) * t for n in NUMBERS}
        return replace(to, **nums)


assert set(NUMBERS) == {f.name for f in fields(Pose) if f.type == "float"}

NEUTRAL = Pose()

# The rig map's expression names (overlay/rigs/raphael_chibi.toml, docs/character.md).
EXPRESSIONS: dict[str, Pose] = {
    "neutral": NEUTRAL,
    "happy": Pose(eyes=Eyes.HAPPY, mouth=Mouth.SMILE, blush=1.0, head_tilt=6, arm_l=55, arm_r=55, sparkles=True),
    "surprised": Pose(eyes=Eyes.BLANK, mouth=Mouth.SHOCK, brows=Brows.RAISED, arm_l=70, arm_r=70, lift=3),
    "pout": Pose(lid=0.3, gaze_x=-0.9, mouth=Mouth.POUT, brows=Brows.ANGRY, blush=1.0, head_turn=-0.6,
                 head_tilt=-6, arm_l=18, arm_r=18),
    "upset": Pose(eyes=Eyes.SQUEEZE, mouth=Mouth.WAIL, brows=Brows.WORRIED, tears=True, head_tilt=4,
                  arm_l=60, arm_r=60),
    "sleepy": Pose(eyes=Eyes.CLOSED, mouth=Mouth.OPEN, mouth_open=0.25, head_tilt=9, head_nod=0.6,
                   arm_l=14, arm_r=14, zzz=True),
    "thinking": Pose(lid=0.2, gaze_x=0.7, gaze_y=-0.8, brows=Brows.WORRIED, mouth=Mouth.FROWN,
                     head_tilt=-7, head_turn=0.4, dots=True),
    "focused": Pose(lid=0.45, brows=Brows.CALM, arm_l=30, arm_r=30, orb=1.0, halo_glow=0.6),
    "warning": Pose(lid=-0.6, brows=Brows.ANGRY, mouth=Mouth.FROWN, halo_glow=1.0, alert=True, sweat=True),
}

# Extra review poses: reaction eyes and states that motions will reach in step 2.
GALLERY: list[tuple[str, Pose]] = [
    *EXPRESSIONS.items(),
    ("blink", Pose(eyes=Eyes.CLOSED)),
    ("talking", Pose(mouth_open=0.8)),
    ("look left", Pose(gaze_x=-1.0, head_turn=-0.5)),
    ("look right", Pose(gaze_x=1.0, head_turn=0.5)),
    ("dizzy", Pose(eyes=Eyes.DIZZY, mouth=Mouth.OPEN, mouth_open=0.4, dizzy=True, head_tilt=-9, body_tilt=4)),
    ("held", Pose(eyes=Eyes.BLANK, mouth=Mouth.OPEN, mouth_open=0.6, arm_l=95, arm_r=95, leg_l=18,
                  leg_r=-12, hair_sway=0.8, squash=1.04)),
    ("wave", Pose(eyes=Eyes.HAPPY, mouth=Mouth.SMILE, arm_r=150, head_tilt=-5, blush=0.5)),
    ("lean + sway", Pose(body_tilt=-8, head_tilt=-10, hair_sway=-1.0, gaze_x=-0.6)),
]
