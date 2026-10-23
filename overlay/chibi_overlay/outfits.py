"""Her outfits: one exported model per outfit and form (docs/character.md -> Outfits).

`[overlay]` names the current `outfit` and lists them under `[overlay.outfits.<name>]`,
each with `chibi_rig` / `serious_rig` and optional `chibi_map` / `serious_map` (the
top-level maps are the shared default). The old single `chibi_rig` / `serious_rig`
keys still work: without an `outfits` table they make one outfit, "default".
Pure Python; the stage loads the maps, the windows load the models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .body import motion
from .body.motion import RigMap
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

    def load_maps(self, pkg: Path) -> dict[str, RigMap]:
        return {form: motion.load(pkg / self.maps[form]) for form in FORMS}

    def missing_models(self) -> list[str]:
        return [p for p in self.rigs.values()
                if not p.startswith(VECTOR) and not Path(p.removeprefix(SPRITES)).exists()]


@dataclass(frozen=True)
class Wardrobe:
    current: str
    outfits: dict[str, Outfit]

    @property
    def names(self) -> list[str]:
        return list(self.outfits)


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
