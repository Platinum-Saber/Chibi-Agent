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


@dataclass(frozen=True)
class Seq:
    frames: tuple[tuple[str, float], ...] = ()  # (image, seconds); none: the expression shows
    loop: bool = False
    effect: str | None = None  # an SVG from effects/, placed by her head
    prop: str | None = None    # an image from extras/, held in front of her (the orb)
    drawn_left: bool = False   # the frames face viewer-left; the overlay's unmirrored facing is right

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
    "Sleep": Seq((("poses/sleep", 1.0),), loop=True, effect="zzz"),
    "Sit": Seq((("poses/sit", 0.9), ("poses/sit_legs", 0.9)), loop=True),
    "Think": Seq((("poses/think", 1.0),), loop=True, effect="thought_dots"),
    "Analyse": Seq((("poses/analyse", 1.0),), loop=True, prop="extras/orb"),
    "Notice": Seq((("poses/notice", 1.6),), effect="alert_mark"),
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


def _bounds(img: QImage) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of the opaque pixels."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), 3]
    ys, xs = np.nonzero(a > 128)
    return None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


class Pack:
    """The pack's images, loaded on first use and kept downscaled."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
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
            img = QImage(str(self.root / f"{key}.png"))
            if img.isNull():
                log.warning("sprite pack: missing %s", key)
                self.sprites[key] = None
                return None
            b = _bounds(img) or (0, 0, img.width(), img.height())
            k = STORE_H / img.height()
            small = img.scaledToHeight(STORE_H, Qt.TransformationMode.SmoothTransformation)
            self.sprites[key] = Sprite(small.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), k, b[3], b[1])
        return self.sprites[key]

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

    def svg(self, name: str) -> QSvgRenderer | None:
        if name not in self.svgs:
            r = QSvgRenderer(str(self.root / "effects" / f"{name}.svg"))
            self.svgs[name] = r if r.isValid() else None
        return self.svgs[name]


class SpriteModel:
    def __init__(self, pack_dir: str, widget):
        self.pack = Pack(pack_dir)
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
        if group not in SEQUENCES:
            log.debug("sprite pack: no sequence for motion %r", group)
        self.motion, self._motion_t0 = group, time.monotonic()

    def StartRandomMotion(self, group: str, _priority=None) -> None:
        self.StartMotion(group)

    def IsMotionFinished(self) -> bool:
        seq = SEQUENCES.get(self.motion or "")
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
        seq = SEQUENCES.get(self.motion or "")
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
        p.translate(0, self.pack.feet - sp.feet)  # this image's feet on the shared baseline
        if seq and seq.drawn_left and key.startswith("poses/"):  # face the way the stage walks her
            p.translate(cw / 2, 0)
            p.scale(-1, 1)
            p.translate(-cw / 2, 0)
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
        if seq and seq.prop:
            self._prop(p, seq.prop, sp, now)
        if seq and seq.effect:
            self._effect(p, seq.effect, sp, now)
        p.restore()

    def gaze(self, now: float) -> str | None:
        """The gaze drawing to show: the cursor's sector, switched only after it holds GAZE_HOLD_S."""
        rects = self.pack.eye_rects
        if self._look is None or not rects:
            return None
        cx = sum(r.center().x() for r in rects) / len(rects)
        cy = sum(r.center().y() for r in rects) / len(rects)
        radius = GAZE_RADIUS * self.pack.canvas[0]
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
            self._blink_at = now + random.uniform(2, 6)
        return now >= self._blink_at

    def _prop(self, p: QPainter, key: str, sp: Sprite, now: float) -> None:
        prop = self.pack.get(key)
        if prop is None:
            return
        cw, _ = self.pack.canvas
        size = 300.0  # canvas px
        bob = 10 * math.sin((now - self._t0) * 2.0)
        r = QRectF(cw / 2 - size / 2, sp.top + 0.6 * (sp.feet - sp.top) - size / 2 + bob, size, size)
        p.drawImage(r, prop.image)

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
