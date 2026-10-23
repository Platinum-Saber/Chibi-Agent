"""Kryo's character customization: %APPDATA%\\ChibiAgent\\character.toml, written by the Customize window.

It sits beside the hand-edited user config.toml (which it never touches) and
layers over the repo's rig maps and defaults:

    outfit = "casual_coat"            # the outfit she wears at start

    [behaviour]                       # eye follow, blink, idle moments, sleep, effects
    gaze = true
    sleep_after_s = 60.0

    [outfits.casual_coat]             # per outfit: size and mood -> clip overrides
    height_dip = 320
    [outfits.casual_coat.moods]
    walking = { motion = "Dance", expression = "happy" }

    [voice]                           # only when saved: overrides config.toml's [voice] F5 defaults
    engine = "kokoro"                 # "f5" (her cloned voice) or "kokoro" (preset voices)
    voice = "bf_emma"                 # f5: a reference .wav path ("" = config's); kokoro: a voice id
    speed = 0.9

    [sequences.Walk]                  # sprite sequences (chibi_overlay/sprites.py)
    frames = [["poses/walk_contact_left", 0.15], ["poses/walk_pass_left", 0.15]]
    loop = true

Pure Python; the stage applies it, the sprite models take the sequences and behaviour.
"""
from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from .body.motion import Clip, RigMap

log = logging.getLogger(__name__)
FILE_NAME = "character.toml"


@dataclass
class Behaviour:
    gaze: bool = True           # eyes move at all (sprite packs with gaze art)
    look_at: str = "clicks"     # what she looks at: "clicks" (where Kryo last clicked), "cursor" or "off"
    look_hold_s: float = 4.0    # how long she keeps looking at a click
    gaze_reach: float = 0.45    # x her canvas width: how far out the cursor counts as fully to one side
    blink_min_s: float = 2.0
    blink_max_s: float = 6.0
    moment_min_s: float = 8.0   # gap between idle moments (wave, stretch, sit, wander...)
    moment_max_s: float = 20.0
    sleep_after_s: float = 60.0  # untouched this long: she falls asleep
    effects: bool = True        # zzz, sparkles, notes, hearts, "!"


@dataclass
class VoiceSettings:
    engine: str = "f5"  # "f5" | "kokoro"
    voice: str = ""     # f5: reference .wav path ("" = config.toml's); kokoro: voice id
    speed: float = 0.90
    nfe: int = 8        # f5 only


@dataclass
class OutfitTweaks:
    height_dip: int | None = None
    mask: bool = False  # drawn outfits: the mask worn on her head (off for now: sprites.MASK_ENABLED)
    sword: bool = True  # drawn outfits: the sheathed sword at her hip
    walk: str = ""      # drawn outfits: the walk set (a folder with walk.json); "" = the newest
    moods: dict[str, dict] = field(default_factory=dict)    # mood -> {motion, expression}
    moments: dict[str, dict] = field(default_factory=dict)  # moment -> {motion, expression}


@dataclass
class Character:
    outfit: str | None = None
    behaviour: Behaviour = field(default_factory=Behaviour)
    outfits: dict[str, OutfitTweaks] = field(default_factory=dict)
    sequences: dict[str, dict] = field(default_factory=dict)  # name -> {frames, loop, effect}
    voice: VoiceSettings | None = None  # None: config.toml's [voice] as is

    def tweaks(self, outfit: str) -> OutfitTweaks:
        return self.outfits.setdefault(outfit, OutfitTweaks())


# --- applying ---------------------------------------------------------------------------------------
def _clip(d: dict) -> Clip:
    return Clip(d.get("motion") or None, d.get("index"), d.get("expression") or None)


def apply_to_map(rig: RigMap, tw: OutfitTweaks | None) -> RigMap:
    """The outfit's rig map with Kryo's size and clip overrides on top."""
    if tw is None:
        return rig
    return replace(
        rig,
        height_dip=int(tw.height_dip) if tw.height_dip else rig.height_dip,
        moods={**rig.moods, **{k: _clip(v) for k, v in tw.moods.items()}},
        moments={**rig.moments, **{k: _clip(v) for k, v in tw.moments.items()}},
    )


# --- reading ----------------------------------------------------------------------------------------
def _behaviour(d: dict) -> Behaviour:
    b = Behaviour()
    for f in fields(Behaviour):
        if f.name in d:
            default = getattr(b, f.name)
            try:
                if isinstance(default, str):
                    if d[f.name] in ("clicks", "cursor", "off"):
                        setattr(b, f.name, d[f.name])
                else:
                    setattr(b, f.name, bool(d[f.name]) if isinstance(default, bool) else float(d[f.name]))
            except (TypeError, ValueError):
                log.warning("character.toml: bad behaviour.%s = %r", f.name, d[f.name])
    return b


def _clips(d) -> dict[str, dict]:
    if not isinstance(d, dict):
        return {}
    return {k: {kk: v[kk] for kk in ("motion", "expression", "index") if kk in v}
            for k, v in d.items() if isinstance(v, dict)}


def parse(d: dict) -> Character:
    outfits = {}
    for name, t in (d.get("outfits") or {}).items():
        if isinstance(t, dict):
            h = t.get("height_dip")
            outfits[name] = OutfitTweaks(int(h) if isinstance(h, (int, float)) and h > 0 else None,
                                         bool(t.get("mask", False)), bool(t.get("sword", True)),
                                         str(t.get("walk", "")),
                                         _clips(t.get("moods")), _clips(t.get("moments")))
    seqs = {}
    for name, t in (d.get("sequences") or {}).items():
        if isinstance(t, dict) and isinstance(t.get("frames"), list):
            frames = [[str(f[0]), float(f[1])] for f in t["frames"]
                      if isinstance(f, list) and len(f) == 2 and isinstance(f[1], (int, float))]
            seqs[name] = {"frames": frames, "loop": bool(t.get("loop", False)), "effect": t.get("effect") or ""}
            for k in ("prop", "seat"):  # absent: the built-in choice; "": none
                if isinstance(t.get(k), str):
                    seqs[name][k] = t[k]
    outfit = d.get("outfit")
    return Character(outfit if isinstance(outfit, str) and outfit else None,
                     _behaviour(d.get("behaviour") or {}), outfits, seqs, _voice(d.get("voice")))


def _voice(d) -> VoiceSettings | None:
    if not isinstance(d, dict):
        return None
    v = VoiceSettings()
    if d.get("engine") in ("f5", "kokoro"):
        v.engine = d["engine"]
    if isinstance(d.get("voice"), str):
        v.voice = d["voice"]
    try:
        v.speed = float(d.get("speed", v.speed))
        v.nfe = int(d.get("nfe", v.nfe))
    except (TypeError, ValueError):
        log.warning("character.toml: bad voice speed/nfe")
    return v


def load(path: Path) -> Character:
    """Kryo's saved customization, or the defaults when there is none (or it can't be read)."""
    try:
        return parse(tomllib.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return Character()
    except (OSError, ValueError) as e:  # tomllib.TOMLDecodeError is a ValueError
        log.warning("character.toml unreadable, using defaults: %s", e)
        return Character()


# --- writing (a small TOML writer: strings, numbers, bools, lists, inline tables) --------------------
_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE.match(k) else json.dumps(k)


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(v, 4)) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON string escapes are valid TOML basic strings
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items() if x is not None) + " }"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def dumps(ch: Character) -> str:
    out = ["# Raphael's customization, written by tray -> Customize Raphael. Edits here are kept",
           "# until the next Save from that window.", ""]
    if ch.outfit:
        out += [f"outfit = {_value(ch.outfit)}", ""]
    out.append("[behaviour]")
    out += [f"{k} = {_value(v)}" for k, v in asdict(ch.behaviour).items()]
    for name, tw in ch.outfits.items():
        out += ["", f"[outfits.{_key(name)}]"]
        if tw.height_dip:
            out.append(f"height_dip = {int(tw.height_dip)}")
        out += [f"mask = {_value(tw.mask)}", f"sword = {_value(tw.sword)}"]
        if tw.walk:
            out.append(f"walk = {_value(tw.walk)}")
        for table in ("moods", "moments"):
            clips = getattr(tw, table)
            if clips:
                out += ["", f"[outfits.{_key(name)}.{table}]"]
                out += [f"{_key(k)} = {_value(v)}" for k, v in clips.items()]
    if ch.voice is not None:
        out += ["", "[voice]"] + [f"{k} = {_value(v)}" for k, v in asdict(ch.voice).items()]
    for name, s in ch.sequences.items():
        out += ["", f"[sequences.{_key(name)}]", f"frames = {_value(s.get('frames', []))}",
                f"loop = {_value(bool(s.get('loop', False)))}"]
        if s.get("effect"):
            out.append(f"effect = {_value(s['effect'])}")
        for k in ("prop", "seat"):
            if k in s:
                out.append(f"{k} = {_value(s[k])}")
    return "\n".join(out) + "\n"


def save(ch: Character, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(ch), encoding="utf-8")
    tmp.replace(path)
