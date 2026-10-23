"""Her chibi from a pack of drawn images (svg-rig branch), standing in for live2d.Model.

A rig path `sprites:<pack dir>` in config.toml selects it. The first pack is
Kryo's casual-coat art (D:/Character Design/output/assets/chibi/casual-coat/v01):
1024 x 1536 PNGs in expressions/, states/, poses/ and extras/, plus SVG effects.

- An expression is a whole standing image. The expressions and states are
  drawn registered to the neutral master, so the states serve as lip sync and
  blink: neutral swaps to `states/mouth_open_N` / `states/blink_*`, and other
  expressions get the mouth area of `mouth_open_N` pasted over theirs.
- A motion group (the rig map's names) plays a pose or a short sequence of
  poses (`SEQUENCES`); once a one-shot sequence ends, the expression shows.
- The poses don't share a baseline, so every image is placed by its own
  lowest opaque row (her feet), lined up with the neutral master's.
- Eye follow (pack v02, `gaze-map.json`): on the neutral face (and its talking
  states) the cursor picks one of eight `gaze/eyes_look_*` drawings by the
  nearest 45-degree sector outside a centre dead zone. As the map recommends,
  only its two eye rectangles are drawn over the fixed body. Blinks and
  reaction faces override gaze.

`Puppet` and `MonitorWindow` call the live2d-py API; this class answers the
calls they use, in the same units (one view unit = half the framebuffer
height, y up, offsets from the viewport centre).
"""
from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QImage, QPainter, QRadialGradient, QTransform
from PySide6.QtSvg import QSvgRenderer

log = logging.getLogger(__name__)

PREFIX = "sprites:"
STORE_H = 760  # images are kept downscaled to this height (she shows at ~320-640 px)
NEUTRAL = "expressions/neutral"
BLINK_S = 0.14
OPEN_EYES = frozenset({"neutral", "focused", "thinking", "warning", "pout"})  # can blink
GAZE_FACES = frozenset({NEUTRAL, "states/mouth_open_1", "states/mouth_open_2", "states/mouth_open_3"})
GAZE_RADIUS = 0.45  # x canvas width: how far from her eyes the cursor counts as fully to one side
GAZE_HOLD_S = 0.12  # a new direction must hold this long before her eyes switch (no flicker on a sector edge)


WALK_LOCK = "walk/"  # keys of the built walk frames (frame 01's head on each)
HEAD_SEAM = 700      # canvas row: frame 01's head (whole chin included) ends where its scarf begins; this if not found
HEAD_FEATHER = 20    # rows each side of that seam that blend (the long hair at her sides crosses it)
SCARF_GROW = 3       # stored px the scarf mask grows by (its ink outline), with a soft edge
WALK_BOB = 6.0       # canvas px: the even head bob the walk frames are placed toward
WALK_DEDUPE = 0.10   # walk frames whose legs change less than this (pixel share) from the last kept one are dropped
WALK_PLANT = 0.5     # the body: 1 plants each support sole exactly, 0 follows the even bob (the head always does)
ORB, MASK, SWORD, SLIME = "extras/orb", "extras/mask", "extras/sword_sheathed", "extras/slime"
MASK_ENABLED = False  # Kryo, 2026-10-23: no mask for now (worn or held); the drawing code stays
PROPS = (ORB, MASK, SWORD) if MASK_ENABLED else (ORB, SWORD)  # what she can hold
SEATS = (SLIME,)            # what she can sit on
SEAT_W = 760.0      # the slime's visible width, canvas px
SEAT_SINK = 0.15    # her seat line sinks this far (x the slime's height) into the slime
SEAT_LINE = 0.80    # a seated pose's seat line: this far from its top to its lowest row


@dataclass(frozen=True)
class Seq:
    frames: tuple[tuple[str, float], ...] = ()  # (image, seconds); none: the expression shows
    loop: bool = False
    effect: str | None = None  # an SVG from effects/, placed by her head
    prop: str | None = None    # extras/ image she holds: the orb, the mask or the sword
    drawn_left: bool = False   # the frames face viewer-left; the overlay's unmirrored facing is right
    seat: str | None = None    # extras/ image she sits on (the slime), drawn under her

    @property
    def length(self) -> float:
        return sum(s for _, s in self.frames)


# Motion group (rig map names, rigs/raphael_sprites.toml) -> what plays.
SEQUENCES: dict[str, Seq] = {
    "Idle": Seq(loop=True),
    "Talk": Seq(loop=True),
    "Surprised": Seq(effect="alert_mark"),
    "Pout": Seq(),
    "Upset": Seq(),
    "Happy": Seq(effect="sparkle"),
    "Held": Seq((("poses/held", 1.0),), loop=True),
    "Fall": Seq((("poses/fall", 1.0),), loop=True),
    "Land": Seq((("poses/land_squash", 0.28),)),
    "Dizzy": Seq((("states/dizzy", 1.0),), loop=True, effect="dizzy_star"),
    "Walk": Seq((("poses/walk_contact_left", 0.15), ("poses/walk_pass_left", 0.15),
                 ("poses/walk_contact_right", 0.15), ("poses/walk_pass_right", 0.15)), loop=True,
                drawn_left=True),  # the pack's walk keys step toward viewer-left
    "Sleep": Seq((("poses/sleep", 1.0),), loop=True, effect="zzz", seat=SLIME),
    "Sit": Seq((("poses/sit", 0.9), ("poses/sit_legs", 0.9)), loop=True, seat=SLIME),
    "Think": Seq((("poses/think", 1.0),), loop=True, effect="thought_dots"),
    "Analyse": Seq((("poses/analyse", 1.0),), loop=True, prop="extras/orb"),
    "Notice": Seq((("poses/notice", 1.6),), effect="alert_mark", prop=SWORD),
    "LookAround": Seq((("poses/point", 1.2), ("poses/talk", 0.8))),
    "Stretch": Seq((("poses/stretch", 1.5),)),
    "Wave": Seq((("poses/wave", 1.6),), effect="heart"),
    "Dance": Seq((("poses/dance", 0.27), ("expressions/happy", 0.27)), loop=True, effect="music_note"),
}


@dataclass
class Sprite:
    image: QImage    # downscaled to STORE_H
    k: float         # stored px per canvas px
    feet: float      # lowest opaque row, canvas px
    top: float       # highest opaque row, canvas px
    box: tuple[float, float, float, float] = (0, 0, 0, 0)  # opaque bounds x0, y0, x1, y1, canvas px
    head: tuple[float, float, float] | None = None      # her hair dome: x0, x1, top row (canvas px)


def _alpha(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), 3]


def _bounds(img: QImage) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of the opaque pixels."""
    ys, xs = np.nonzero(_alpha(img) > 128)
    return None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _grow(mask: np.ndarray, r: int) -> np.ndarray:
    """A 0..1 mask grown by `r` px (max of shifted copies), then softened one step (mean of shifts)."""
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out = np.maximum(out, np.roll(np.roll(mask, dy, 0), dx, 1))
    soft = sum(np.roll(np.roll(out, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9
    return np.clip(soft, 0, 1)


def _distinct_steps(arrs: list[np.ndarray], dys: list[float], min_change: float = WALK_DEDUPE) -> list[int]:
    """Indexes of the walk frames to keep: a frame whose legs (the lowest quarter of the figure,
    each placed by its support-sole offset) differ from the last kept one by less than
    `min_change` of the pixels adds a hitch, not a step. The loop's last frame is checked
    against the first too."""
    h, w = arrs[0].shape[:2]
    legs = [(np.roll(a[:, :, 3], int(round(dy)), 0)[int(0.77 * h):, int(0.2 * w):int(0.83 * w)] > 128)
            for a, dy in zip(arrs, dys)]
    change = lambda i, j: float((legs[i] != legs[j]).mean())  # noqa: E731
    keep = [0]
    for i in range(1, len(arrs)):
        if change(i, keep[-1]) >= min_change:
            keep.append(i)
    if len(keep) > 2 and change(keep[-1], keep[0]) < min_change:
        keep.pop()
    return keep


def _scarf_top(rgba: np.ndarray) -> int | None:
    """The first row (below her eyes, above her waist) where the cream scarf crosses her centre:
    cream is red/green-high, clearly less blue (skin is nearly as blue as red). Her gold eyes
    pass that test too, so the search starts below them (~0.41 x height)."""
    h, w = rgba.shape[:2]
    band = rgba[int(0.41 * h):int(0.6 * h), int(0.42 * w):int(0.58 * w)]
    b, g, r, a = band[..., 0], band[..., 1], band[..., 2], band[..., 3]  # ARGB32 is BGRA in memory
    cream = (a > 200) & (r > 190) & (g > 160) & (r - b > 45)
    rows = np.nonzero(cream.mean(axis=1) > 0.5)[0]
    return int(0.41 * h) + int(rows[0]) if len(rows) else None


def _head(a: np.ndarray) -> tuple[float, float, float] | None:
    """Her hair dome in a character image: the topmost opaque row in the central columns (raised
    hands are off to the sides), then the opaque run through that point 0.1 x height lower,
    which is the dome's width. None when nothing sits in the middle (a prop image)."""
    h, w = a.shape
    band = a[:, int(0.38 * w):int(0.62 * w)] > 128
    rows = np.nonzero(band.any(axis=1))[0]
    if len(rows) == 0 or rows[0] > 0.4 * h:
        return None
    top = int(rows[0])
    cx = int(0.38 * w) + int(np.nonzero(band[top])[0].mean())
    r = min(h - 1, top + int(0.1 * h))
    row = a[r] > 128
    if not row[cx]:
        return None
    x0 = cx
    while x0 > 0 and row[x0 - 1]:
        x0 -= 1
    x1 = cx
    while x1 < w - 1 and row[x1 + 1]:
        x1 += 1
    return float(x0), float(x1), float(top)


class Pack:
    """The pack's images, loaded on first use and kept downscaled."""

    def __init__(self, root: str | Path, background: bool = False):
        self.root = Path(root)
        self.background = background  # build the walk frames on a thread (the overlay); tests build inline
        self._walk_thread: threading.Thread | None = None
        self.sprites: dict[str, Sprite] = {}
        self.svgs: dict[str, QSvgRenderer] = {}
        self._mouth: QRect | None = None
        self._patches: dict[str, QImage | None] = {}
        neutral = self.get(NEUTRAL)
        if neutral is None:
            raise FileNotFoundError(f"sprite pack has no {NEUTRAL}.png: {self.root}")
        self.canvas = (neutral.image.width() / neutral.k, neutral.image.height() / neutral.k)
        self.feet = neutral.feet
        self.gaze, self.eye_rects, self.deadzone = self._load_gaze()
        # images placed by a given anchor instead of their lowest opaque row: key -> (dx, feet row)
        self.anchors: dict[str, tuple[float, float]] = {}
        self.walk_dir: Path | None = None
        self._walk_src: list = []
        self._walk_anchor = 1508.0
        self.use_walk()

    def walk_sets(self) -> list[Path]:
        """Folders with a walk.json: the pack's walk-cycle/ and sets beside the pack folder
        (casual-coat/<set>/walk.json), newest first."""
        cands = [self.root / "walk-cycle"] + [w.parent for w in self.root.parent.glob("*/walk.json")]
        found = {c.resolve(): c for c in cands if (c / "walk.json").exists()}
        return sorted(found.values(), key=lambda c: (c / "walk.json").stat().st_mtime, reverse=True)

    def use_walk(self, name: str = "") -> None:
        """Walk with the set named `name` (a folder from walk_sets), or the newest. Its frames are
        separate drawings, so each gets frame 01's head down to the chin (no face shimmer at 8 fps),
        placed exactly on an even bob; the body sits halfway between that and planting its support
        sole (walk.json's offsets). Planting alone made the head jump."""
        self.sequences = dict(SEQUENCES)
        self.walk_dir, self._walk_src = None, []
        for k in [k for k in self.sprites if k.startswith(WALK_LOCK)]:
            del self.sprites[k]
        sets = self.walk_sets()
        pick = next((d for d in sets if d.name == name), sets[0] if sets else None)
        if pick is None:
            return
        try:
            w = json.loads((pick / "walk.json").read_text(encoding="utf-8"))
            ay = float(w.get("anchor_xy", [0, 1508])[1])
            src = [(pick / f["file"], float(f.get("draw_offset_xy", [0, 0])[0]),
                    float(f.get("draw_offset_xy", [0, 0])[1]), f.get("duration_ms", 125) / 1000) for f in w["frames"]]
        except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
            log.warning("walk set %s unreadable: %s", pick, e)
            return
        self.walk_dir, self._walk_src, self._walk_anchor = pick, src, ay
        frames = tuple((f"{WALK_LOCK}{i}", sec) for i, (_, _, _, sec) in enumerate(src))
        left = "left" in str(w.get("facing", "left")).split(";")[0]
        self.sequences["Walk"] = Seq(frames, loop=bool(w.get("loop", True)), drawn_left=left)
        if self.background:  # ~0.7 s of blending: off the drawing thread
            self._walk_thread = threading.Thread(target=self._build_walk, name="walk-build", daemon=True)
            self._walk_thread.start()

    def _build_walk(self) -> None:
        """The walk frames with frame 01's head blended in above the scarf, and their anchors.
        Blended at the stored size (canvas rows scaled by kk)."""
        src_imgs = [QImage(str(path)) for path, *_ in self._walk_src]
        if not src_imgs or any(im.isNull() for im in src_imgs):
            log.warning("walk set %s: missing frames", self.walk_dir)
            self._walk_src = []
            return
        canvas_h = float(src_imgs[0].height())
        kk = STORE_H / canvas_h
        imgs = [im.scaledToHeight(STORE_H, Qt.TransformationMode.SmoothTransformation)
                .convertToFormat(QImage.Format.Format_ARGB32) for im in src_imgs]
        arrs = [np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine() // 4, 4)
                [:, :im.width()].astype(np.float32) for im in imgs]
        heads = [_head(a[:, :, 3].astype(np.uint8)) for a in arrs]
        ref, rh = arrs[0], heads[0]
        n = len(arrs)
        ref_scarf = _scarf_top(ref)
        ref_seam = ref_scarf if ref_scarf is not None else HEAD_SEAM * kk
        keep = _distinct_steps(arrs, [dy * kk for _, _, dy, _ in self._walk_src])
        if len(keep) < n:
            log.info("walk %s: dropped near-duplicate frames %s", self.walk_dir.name,
                     [i + 1 for i in range(n) if i not in keep])
        total = sum(sec for *_, sec in self._walk_src)
        arrs, heads, src = [arrs[i] for i in keep], [heads[i] for i in keep], [self._walk_src[i] for i in keep]
        n = len(arrs)
        tops = [h[2] if h else (rh[2] if rh else 0.0) for h in heads]  # stored px
        ups = [WALK_BOB * math.cos(2 * math.pi * 2 * i / n) for i in range(n)]  # even bob: low on contacts
        # the body: half planted on its support sole, half its own head on the even bob (canvas px down)
        drops =[round(WALK_PLANT * dy + (1 - WALK_PLANT) * ((tops[0] - top) / kk + up))
                 for top, up, (_, _, dy, _) in zip(tops, ups, src)]
        built, anchors = {}, {}
        for i, (a, h, (_, dx, _, _)) in enumerate(zip(arrs, heads, src)):
            out = a
            if rh is not None and h is not None and i > 0:
                sx = int(round((h[0] + h[1]) / 2 - (rh[0] + rh[1]) / 2))
                # frame 01's head exactly on the even bob, wherever this frame's body sits
                sy = int(round((drops[0] - drops[i] + ups[i] - ups[0]) * kk))
                head = np.roll(np.roll(ref, sy, 0), sx, 1)
                y = np.arange(a.shape[0], dtype=np.float32)[:, None]
                # the whole of frame 01's head, its chin outline included, down to its own scarf...
                m = np.clip((ref_seam + sy + HEAD_FEATHER * kk - y) / (2 * HEAD_FEATHER * kk), 0, 1)[:, :, None]
                m = np.repeat(m, a.shape[1], axis=1)  # per pixel from here on
                # ...and this frame's scarf in front of it, as a scarf is (it rises higher on some frames)
                low = int(0.41 * a.shape[0])
                b_, g_, r_, al_ = (a[low:, :, c] for c in range(4))
                cream = ((al_ > 200) & (r_ > 190) & (g_ > 160) & (r_ - b_ > 45)).astype(np.float32)
                cream = _grow(cream, SCARF_GROW)
                m[low:, :, 0] *= 1 - cream
                a1, a2 = head[:, :, 3:4] / 255, a[:, :, 3:4] / 255
                alpha = m * a1 + (1 - m) * a2
                rgb = (m * head[:, :, :3] * a1 + (1 - m) * a[:, :, :3] * a2) / np.maximum(alpha, 1e-6)
                out = np.concatenate([rgb, alpha * 255], 2)
            buf = np.ascontiguousarray(out.clip(0, 255).astype(np.uint8))
            img = QImage(buf.data, buf.shape[1], buf.shape[0], buf.shape[1] * 4, QImage.Format.Format_ARGB32).copy()
            built[f"{WALK_LOCK}{i}"] = self._make(img, canvas_h=canvas_h)
            anchors[f"{WALK_LOCK}{i}"] = (dx, self._walk_anchor - drops[i])
        # swap in all at once: the drawing thread may be reading the walk meanwhile
        self.anchors.update(anchors)
        self.sprites.update(built)
        walk = self.sequences["Walk"]
        self.sequences = {**self.sequences, "Walk": Seq(tuple((k, total / n) for k in built), walk.loop,
                                                       walk.effect, walk.prop, walk.drawn_left, walk.seat)}

    def _load_gaze(self) -> tuple[dict[tuple[int, int], str], list[QRectF], float]:
        """(x, y) direction -> image key, the eye rectangles (canvas px), the centre dead zone."""
        try:
            m = json.loads((self.root / "gaze-map.json").read_text(encoding="utf-8"))
            states = {(int(s["x"]), int(s["y"])): s["file"].removesuffix(".png") for s in m["states"]}
            rects = [QRectF(*r) for r in m["rendering"]["eye_rectangles_xywh"]]
            return states, rects, float(m["selection"].get("center_deadzone", 0.15))
        except (OSError, ValueError, KeyError, TypeError):
            return {}, [], 0.15  # an older pack: no eye follow

    def gaze_key(self, x: float, y: float) -> str | None:
        """The drawing for a cursor at (x, y), in eye-radius units (x right, y up)."""
        if not self.gaze:
            return None
        if math.hypot(x, y) < self.deadzone:
            d = (0, 0)
        else:
            a = round(math.atan2(y, x) / (math.pi / 4)) * (math.pi / 4)  # nearest 45-degree sector
            d = (round(math.cos(a)), round(math.sin(a)))
        return self.gaze.get(d)

    def exists(self, key: str) -> bool:
        return (self.root / f"{key}.png").exists()

    def get(self, key: str) -> Sprite | None:
        if key not in self.sprites:
            if key.startswith(WALK_LOCK):
                if self._walk_thread is None or not self._walk_thread.is_alive():
                    self._build_walk()  # (the overlay starts it in the background; tests build here)
                return self.sprites.get(key)  # None while building: she stands until it's ready
            img = QImage(str(self.root / f"{key}.png"))
            if img.isNull():
                log.warning("sprite pack: missing %s", key)
                self.sprites[key] = None
                return None
            self.sprites[key] = self._make(img, not key.startswith("extras/"))
        return self.sprites[key]

    @staticmethod
    def _make(img: QImage, figure: bool = True, canvas_h: float | None = None) -> Sprite:
        """An image -> its Sprite (downscaled to STORE_H) with bounds and, for a figure, its hair
        dome, in canvas px. `canvas_h`: the canvas height when `img` is already downscaled."""
        k = STORE_H / img.height() if canvas_h is None else img.height() / canvas_h
        a = _alpha(img)
        ys, xs = np.nonzero(a > 128)
        b = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else (0, 0, img.width(), img.height())
        head = _head(a) if figure else None
        small = img if canvas_h is not None else img.scaledToHeight(STORE_H, Qt.TransformationMode.SmoothTransformation)
        if canvas_h is not None:  # bounds were measured on the small image: back to canvas px
            b = tuple(v / k for v in b)
            head = tuple(v / k for v in head) if head else None
        return Sprite(small.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), k, b[3], b[1],
                      tuple(map(float, b)), head)

    def mouth_rect(self) -> QRect:
        """The mouth patch (stored px): a fixed box around the densest change between neutral
        and the widest talking state. The states are regenerations, so faint edge noise is
        scattered over the whole figure; the open mouth is the one dense cluster."""
        if self._mouth is None:
            self._mouth = QRect()
            base, wide = self.get(NEUTRAL), self.get("states/mouth_open_3")
            if wide is not None and wide.image.size() == base.image.size():
                img = base.image
                shape = (img.height(), img.bytesPerLine() // 4, 4)
                a = np.frombuffer(img.constBits(), np.uint8).reshape(shape).astype(np.int16)
                b = np.frombuffer(wide.image.constBits(), np.uint8).reshape(shape).astype(np.int16)
                diff = np.abs(a - b).max(axis=2) > 40
                blk = 8
                h, w = (diff.shape[0] // blk) * blk, (diff.shape[1] // blk) * blk
                dens = diff[:h, :w].reshape(h // blk, blk, w // blk, blk).sum(axis=(1, 3))
                dens[int(0.6 * dens.shape[0]):] = 0  # the face is in the upper part
                by, bx = np.unravel_index(int(dens.argmax()), dens.shape)
                cx, cy = bx * blk + blk // 2, by * blk + blk // 2
                pw, ph = int(0.15 * img.width()), int(0.075 * img.height())
                self._mouth = QRect(cx - pw // 2, cy - ph // 2, pw, ph)
        return self._mouth

    def mouth_patch(self, level: int) -> QImage | None:
        """The talking state's mouth box with an oval feathered edge, to paste over another expression."""
        key = f"mouth_patch_{level}"
        if key not in self._patches:
            src, r = self.get(f"states/mouth_open_{level}"), self.mouth_rect()
            patch = None
            if src is not None and not r.isEmpty():
                patch = src.image.copy(r)
                g = QRadialGradient(QPointF(r.width() / 2, r.height() / 2), r.width() / 2)
                g.setColorAt(0.0, Qt.GlobalColor.black)
                g.setColorAt(0.7, Qt.GlobalColor.black)
                g.setColorAt(1.0, Qt.GlobalColor.transparent)
                p = QPainter(patch)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                p.scale(1.0, r.height() / r.width())  # the gradient circle becomes an oval
                p.fillRect(QRectF(0, 0, r.width(), r.width()), QBrush(g))
                p.end()
            self._patches[key] = patch
        return self._patches[key]

    def keys(self, folder: str) -> list[str]:
        """The pack's images in one folder, as keys ("poses/wave")."""
        return sorted(f"{folder}/{f.stem}" for f in (self.root / folder).glob("*.png"))

    def effects(self) -> list[str]:
        return sorted(f.stem for f in (self.root / "effects").glob("*.svg"))

    def svg(self, name: str) -> QSvgRenderer | None:
        if name not in self.svgs:
            r = QSvgRenderer(str(self.root / "effects" / f"{name}.svg"))
            self.svgs[name] = r if r.isValid() else None
        return self.svgs[name]


class SpriteModel:
    def __init__(self, pack_dir: str, widget):
        self.pack = Pack(pack_dir, background=True)
        self.widget = widget
        self.fb = (1, 1)
        self.scale_x = self.scale_y = 1.0
        self.offset = (0.0, 0.0)
        self.expression = "neutral"
        self.motion: str | None = None
        self._motion_t0 = 0.0
        self.params: dict[str, float] = {}
        self._t0 = self._t = time.monotonic()
        self._blink_at = self._t + random.uniform(2, 6)
        self._applied: dict[str, float] = {}
        self._xf = QTransform()
        self._look: tuple[float, float] | None = None  # cursor in canvas px
        self._gaze_shown: str | None = None
        self._gaze_next: tuple[str | None, float] = (None, 0.0)
        # tunable from the Customize window (tune(); character.py)
        self._overrides: dict[str, Seq] = {}  # Kryo's sequences (Customize); the rest come from the pack
        self.gaze_on = True
        self.gaze_reach = GAZE_RADIUS
        self.blink_s = (2.0, 6.0)
        self.effects_on = True
        self.wear_mask = False   # the mask tilted on her head (Customize -> Look)
        self.wear_sword = False  # the sheathed sword at her hip

    def tune(self, ch, outfit: str | None = None) -> None:
        """Apply a character.Character: sequence overrides, behaviour, and what this outfit wears."""
        tw = ch.outfits.get(outfit) if outfit else None
        walk = tw.walk if tw else ""
        if (self.pack.walk_dir.name if self.pack.walk_dir else "") != walk and (walk or self.pack.walk_dir is None
                                                                               or self.pack.walk_sets()[:1] != [self.pack.walk_dir]):
            self.pack.use_walk(walk)
        self._overrides = {}
        for name, d in ch.sequences.items():
            frames = tuple((str(k), float(sec)) for k, sec in d.get("frames", []) if float(sec) > 0)
            base = self.pack.sequences.get(name, Seq())
            pick = lambda k, dflt: (d[k] or None) if k in d else dflt  # noqa: E731 ("" = none)
            self._overrides[name] = Seq(frames, bool(d.get("loop", base.loop)), d.get("effect") or None,
                                       pick("prop", base.prop), base.drawn_left, pick("seat", base.seat))
        self.wear_mask = MASK_ENABLED and (tw.mask if tw else True)
        self.wear_sword = tw.sword if tw else True
        b = ch.behaviour
        self.gaze_on, self.gaze_reach = b.gaze, max(0.05, b.gaze_reach)
        self.blink_s = (b.blink_min_s, max(b.blink_min_s, b.blink_max_s))
        self.effects_on = b.effects
        if not self.gaze_on:
            self._gaze_shown = None

    @property
    def sequences(self) -> dict[str, Seq]:
        """What plays: Kryo's overrides over the pack's sequences, read live (the pack swaps in
        its walk once the background build has trimmed and blended it)."""
        return {**self.pack.sequences, **self._overrides}

    # --- live2d.Model API used by Puppet / MonitorWindow ------------------------------------------
    def LoadModelJson(self, _path: str) -> None:
        pass

    def Resize(self, w: int, h: int) -> None:
        self.fb = (w, h)

    def SetScale(self, s: float) -> None:
        self.scale_x = math.copysign(s, self.scale_x)
        self.scale_y = s

    def SetScaleX(self, sx: float) -> None:
        self.scale_x = sx

    def SetOffset(self, x: float, y: float) -> None:
        self.offset = (x, y)

    def SetExpression(self, name: str) -> None:
        self.expression = name if self.pack.exists(f"expressions/{name}") else "neutral"

    def ResetExpression(self) -> None:
        self.expression = "neutral"

    def StartMotion(self, group: str, _index=None, _priority=None) -> None:
        if group not in self.sequences:
            log.debug("sprite pack: no sequence for motion %r", group)
        self.motion, self._motion_t0 = group, time.monotonic()

    def StartRandomMotion(self, group: str, _priority=None) -> None:
        self.StartMotion(group)

    def IsMotionFinished(self) -> bool:
        seq = self.sequences.get(self.motion or "")
        return seq is None or (not seq.loop and time.monotonic() - self._motion_t0 >= seq.length)

    def SetSaveParamById(self, pid: str, value: float, _weight: float = 1.0) -> None:
        self.params[pid] = value

    def Drag(self, x: float, y: float) -> None:
        """Look toward window px (x, y). Mapped into canvas px through the last frame's transform,
        so mirroring is already undone (the gaze map's directions are image directions)."""
        inv, ok = self._xf.inverted()
        if ok:
            q = inv.map(QPointF(x, y))
            self._look = (q.x(), q.y())

    def Update(self) -> None:
        self._t = time.monotonic()
        self._applied, self.params = self.params, {}  # the stage writes its params every frame

    def Draw(self) -> None:
        p = QPainter(self.widget)
        dpr = self.widget.devicePixelRatioF() if hasattr(self.widget, "devicePixelRatioF") else 1.0
        self._xf = self.transform()
        p.setTransform(self._xf * QTransform.fromScale(1 / dpr, 1 / dpr))  # fb px -> logical px
        self.paint(p, self._t)
        p.end()

    # --- drawing -----------------------------------------------------------------------------------
    def transform(self) -> QTransform:
        """Canvas px -> framebuffer px. At scale 1 the canvas height fills the framebuffer."""
        w, h = self.fb
        u = h / 2
        cw, ch = self.pack.canvas
        xf = QTransform()
        xf.translate(w / 2 + self.offset[0] * u, h / 2 - self.offset[1] * u)
        xf.scale(self.scale_x * h / ch, self.scale_y * h / ch)
        xf.translate(-cw / 2, -ch / 2)
        return xf

    def frame(self, now: float) -> tuple[str, Seq | None]:
        """The image to show now and the playing sequence."""
        seq = self.sequences.get(self.motion or "")
        if seq and seq.frames:
            t = now - self._motion_t0
            if seq.loop:
                t %= seq.length
            for key, s in seq.frames:
                if t < s:
                    return key, seq
                t -= s
        return f"expressions/{self.expression}", seq

    def paint(self, p: QPainter, now: float) -> None:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        key, seq = self.frame(now)
        prm = self._applied
        mouth = prm.get("ParamMouthOpenY", 0.0)
        level = 3 if mouth > 0.66 else 2 if mouth > 0.33 else 1 if mouth > 0.08 else 0
        patch = None
        if key == NEUTRAL:
            closed = min(prm.get("ParamEyeLOpen", 1.0), prm.get("ParamEyeROpen", 1.0)) < 0.5
            if level:
                key = f"states/mouth_open_{level}"
            elif closed or self._blinking(now):
                key = "states/blink_closed" if closed or self._blink_phase(now) == 1 else "states/blink_half"
        elif key.startswith("expressions/") and level:
            patch = level
        elif self.expression in OPEN_EYES and key.startswith("expressions/"):
            self._blinking(now)  # keep the blink clock running
        sp = self.pack.get(key) or self.pack.get(NEUTRAL)
        cw, _ = self.pack.canvas
        feet = QPointF(cw / 2, self.pack.feet)
        p.save()
        # stage params: lean (dance, held) and tilt, around her feet; breathing squash
        p.translate(feet)
        p.rotate(0.8 * prm.get("ParamBodyAngleX", 0.0) + 0.6 * prm.get("ParamAngleZ", 0.0))
        p.scale(1.0, 1.0 + 0.008 * math.sin((now - self._t0) * 2 * math.pi / 3.6))
        p.translate(-feet)
        dx, fy = self.pack.anchors.get(key, (0.0, sp.feet))
        seat = self.pack.get(seq.seat) if seq and seq.seat else None
        if seat is not None:  # the slime on the baseline, her seat line sunk into its top
            top = self._seat(p, seat)
            line = sp.top + SEAT_LINE * (sp.feet - sp.top)
            p.translate(dx, top + SEAT_SINK * (self.pack.feet - top) - line)
        else:
            p.translate(dx, self.pack.feet - fy)  # this image's feet on the shared baseline
        if seq and seq.drawn_left and not key.startswith(("expressions/", "states/")):  # face the way she walks
            p.translate(cw / 2, 0)
            p.scale(-1, 1)
            p.translate(-cw / 2, 0)
        held = seq.prop if seq and (seq.prop != MASK or MASK_ENABLED) else None
        if self.wear_sword and held != SWORD:
            self._worn_sword(p, sp)
        p.save()
        p.scale(1 / sp.k, 1 / sp.k)
        p.drawImage(0, 0, sp.image)
        if patch:
            img = self.pack.mouth_patch(patch)
            if img is not None:
                p.drawImage(self.pack.mouth_rect().topLeft(), img)
        p.restore()
        if key in GAZE_FACES:
            self._eyes(p, now)
        if self.wear_mask and held != MASK:
            self._worn_mask(p, sp)
        if held:
            self._prop(p, held, sp, now)
        if seq and seq.effect and self.effects_on:
            self._effect(p, seq.effect, sp, now)
        p.restore()

    def gaze(self, now: float) -> str | None:
        """The gaze drawing to show: the cursor's sector, switched only after it holds GAZE_HOLD_S."""
        rects = self.pack.eye_rects
        if self._look is None or not rects or not self.gaze_on:
            return None
        cx = sum(r.center().x() for r in rects) / len(rects)
        cy = sum(r.center().y() for r in rects) / len(rects)
        radius = self.gaze_reach * self.pack.canvas[0]
        want = self.pack.gaze_key((self._look[0] - cx) / radius, (cy - self._look[1]) / radius)
        if want == self._gaze_shown:
            self._gaze_next = (None, 0.0)
        elif want != self._gaze_next[0]:
            self._gaze_next = (want, now)
        elif now - self._gaze_next[1] >= GAZE_HOLD_S:
            self._gaze_shown, self._gaze_next = want, (None, 0.0)
        return self._gaze_shown

    def _eyes(self, p: QPainter, now: float) -> None:
        """The gaze drawing's two eye rectangles over the neutral face (already drawn)."""
        key = self.gaze(now)
        sp = self.pack.get(key) if key else None
        if sp is None:
            return
        for r in self.pack.eye_rects:
            src = QRectF(r.x() * sp.k, r.y() * sp.k, r.width() * sp.k, r.height() * sp.k)
            p.drawImage(r, sp.image, src)

    def _blink_phase(self, now: float) -> int:
        """0 half-closing, 1 closed, 2 opening."""
        return min(2, int((now - self._blink_at) / (BLINK_S / 3)))

    def _blinking(self, now: float) -> bool:
        if self.expression not in OPEN_EYES:
            return False
        if now >= self._blink_at + BLINK_S:
            self._blink_at = now + random.uniform(*self.blink_s)
        return now >= self._blink_at

    def _draw_extra(self, p: QPainter, key: str, centre: QPointF, width: float, angle: float = 0.0) -> None:
        """An extras/ image's opaque part, `width` canvas px wide, centred and rotated."""
        e = self.pack.get(key)
        if e is None:
            return
        x0, y0, x1, y1 = e.box
        src = QRectF(x0 * e.k, y0 * e.k, (x1 - x0) * e.k, (y1 - y0) * e.k)
        h = width * (y1 - y0) / max(1.0, x1 - x0)
        p.save()
        p.translate(centre)
        p.rotate(angle)
        p.drawImage(QRectF(-width / 2, -h / 2, width, h), e.image, src)
        p.restore()

    def _seat(self, p: QPainter, seat: Sprite) -> float:
        """Draws the seat on the baseline, centred under her; returns its top row (canvas px)."""
        cw, _ = self.pack.canvas
        x0, y0, x1, y1 = seat.box
        h = SEAT_W * (y1 - y0) / max(1.0, x1 - x0)
        top = self.pack.feet - h
        p.drawImage(QRectF(cw / 2 - SEAT_W / 2, top, SEAT_W, h), seat.image,
                    QRectF(x0 * seat.k, y0 * seat.k, (x1 - x0) * seat.k, (y1 - y0) * seat.k))
        return top

    def _worn_mask(self, p: QPainter, sp: Sprite) -> None:
        """Tilted on the viewer-left side of her head, like Kryo's reference."""
        if sp.head is None:
            return
        x0, x1, top = sp.head
        w = x1 - x0
        self._draw_extra(p, MASK, QPointF(x0 + 0.16 * w, top + 0.22 * w), 0.48 * w, -38)

    def _worn_sword(self, p: QPainter, sp: Sprite) -> None:
        """Sheathed, slung behind her at the hip (drawn before her, so only its ends show)."""
        cw, _ = self.pack.canvas
        y = sp.top + 0.70 * (sp.feet - sp.top)
        self._draw_extra(p, SWORD, QPointF(cw / 2 + 20, y - 40), 0.98 * cw, -24)

    def _prop(self, p: QPainter, key: str, sp: Sprite, now: float) -> None:
        """What she holds, in front of her: the orb floats at her chest, the sword lies across
        her hands, the mask is held up at her chest."""
        cw, _ = self.pack.canvas
        h = sp.feet - sp.top
        if key == ORB or key not in PROPS:
            prop = self.pack.get(key)
            if prop is None:
                return
            size = 300.0
            bob = 10 * math.sin((now - self._t0) * 2.0)
            p.drawImage(QRectF(cw / 2 - size / 2, sp.top + 0.6 * h - size / 2 + bob, size, size), prop.image)
        elif key == SWORD:
            self._draw_extra(p, SWORD, QPointF(cw / 2 + 40, sp.top + 0.66 * h), 0.80 * cw, -6)
        elif key == MASK:
            self._draw_extra(p, MASK, QPointF(cw / 2 - 40, sp.top + 0.60 * h), 0.30 * cw, -12)

    def _effect(self, p: QPainter, name: str, sp: Sprite, now: float) -> None:
        r = self.pack.svg(name)
        if r is None:
            return
        cw, _ = self.pack.canvas
        t = now - self._t0
        if name == "dizzy_star":  # three stars circling her head
            for k in range(3):
                a = t * 2.4 + k * 2 * math.pi / 3
                c = QPointF(cw / 2 + 260 * math.cos(a), sp.top + 90 + 50 * math.sin(a))
                r.render(p, QRectF(c.x() - 55, c.y() - 55, 110, 110))
            return
        size = 190.0
        bob = 14 * math.sin(t * 1.8)
        x = cw / 2 + 260 if name != "sparkle" else cw / 2 - 360
        r.render(p, QRectF(x, sp.top - 40 + bob, size, size))
