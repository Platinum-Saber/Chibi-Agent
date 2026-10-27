"""Her outfits: one exported model per outfit and form (docs/character.md -> Outfits).

`[overlay]` names the current `outfit` and lists them under `[overlay.outfits.<name>]`,
each with `chibi_rig` / `serious_rig` and optional `chibi_map` / `serious_map` (the
top-level maps are the shared default). The old single `chibi_rig` / `serious_rig`
keys still work: without an `outfits` table they make one outfit, "default".
Pure Python; the stage loads the maps, the windows load the models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from .body import motion
from .body.motion import RigMap
from .godot3d import PREFIX as GODOT, missing as godot_missing
from .sprites import PREFIX as SPRITES
from .vector import PREFIX as VECTOR

log = logging.getLogger(__name__)
FORMS = ("chibi", "serious")
LEGACY = "default"


@dataclass(frozen=True)
class Outfit:
    name: str
    rigs: dict[str, str]  # form -> .model3.json
    maps: dict[str, str]  # form -> rig map TOML, relative to overlay/
    chibi_only: bool = False  # its serious model is missing: she stays in the chibi form

    def load_maps(self, pkg: Path) -> dict[str, RigMap]:
        return {form: motion.load(pkg / self.maps[form]) for form in FORMS}

    def missing_models(self) -> list[str]:
        out = []
        for p in self.rigs.values():
            if p.startswith(GODOT):
                out += godot_missing(p.removeprefix(GODOT))
            elif not p.startswith(VECTOR) and not Path(p.removeprefix(SPRITES)).exists():
                out.append(p)
        return list(dict.fromkeys(out))

    @property
    def body(self) -> str:
        """"3d" for her Godot body, else "2d" (Live2D, sprite pack, vector rig)."""
        return "3d" if self.rigs["chibi"].startswith(GODOT) else "2d"


@dataclass(frozen=True)
class Wardrobe:
    current: str
    outfits: dict[str, Outfit]

    @property
    def names(self) -> list[str]:
        return list(self.outfits)


def usable(w: Wardrobe) -> Wardrobe:
    """The outfits whose models are on disk. One with its chibi model but not its serious one
    (a 3D serious body whose VRM isn't installed) stays, in the chibi form only."""
    keep = {}
    for name, o in w.outfits.items():
        chibi_gone = [m for m in Outfit(name, {"chibi": o.rigs["chibi"]}, {}).missing_models()]
        if chibi_gone:
            log.info("outfit %s skipped: model not found: %s", name, ", ".join(chibi_gone))
            continue
        if o.missing_models():
            log.info("outfit %s: serious model not found, chibi form only", name)
            o = replace(o, rigs={**o.rigs, "serious": o.rigs["chibi"]},
                        maps={**o.maps, "serious": o.maps["chibi"]}, chibi_only=True)
        keep[name] = o
    if not keep:
        return w  # nothing on disk: leave it to the stage to report
    current = w.current if w.current in keep else next(iter(keep))
    return Wardrobe(current, keep)


def parse(cfg: dict) -> Wardrobe:
    """`cfg` is the merged `[overlay]` table."""
    tables = cfg.get("outfits") or {}
    if not tables:
        tables = {LEGACY: {}}
    elif any(f"{f}_rig" in cfg for f in FORMS):
        log.warning("[overlay] chibi_rig/serious_rig only fill gaps in [overlay.outfits.*]")
    outfits = {}
    for name, t in tables.items():
        rigs, maps = {}, {}
        for form in FORMS:
            rig = t.get(f"{form}_rig") or cfg.get(f"{form}_rig")
            mp = t.get(f"{form}_map") or cfg.get(f"{form}_map")
            if not rig:
                raise ValueError(f"outfit {name!r} has no {form}_rig")
            if not mp:
                raise ValueError(f"outfit {name!r} has no {form}_map (and [overlay] has no shared one)")
            rigs[form], maps[form] = str(rig), str(mp)
        outfits[name] = Outfit(name, rigs, maps)
    current = cfg.get("outfit") or next(iter(outfits))
    if current not in outfits:
        first = next(iter(outfits))
        log.warning("unknown outfit %r in config; wearing %r", current, first)
        current = first
    return Wardrobe(current, outfits)
