"""Offscreen GIFs of Raphael's 2D chibi (the casual-coat sprite pack) and the scenes mixing her
3D frames (recorded by render3d.py), drawn with the overlay's own code: SpriteModel, Brain,
Physics, the rig maps, PoseWheel/paint_wheel, the HUD Painter and the thinking core.
A fake clock stands in for time.monotonic, so every frame is deterministic.

usage: python render_gifs.py OUT_DIR [scene ...] [clip name ...]   (docs/wiki/making-the-gifs.md)
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "overlay"), str(REPO / "shared")]

CLOCK = [1000.0]
time.monotonic = lambda: CLOCK[0]  # noqa: E731 (every module calls time.monotonic())

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QRadialGradient, QTransform)

app = QGuiApplication([])

from chibi_overlay import hud  # noqa: E402
from chibi_overlay.body import motion  # noqa: E402
from chibi_overlay.body.brain import Brain, Mood, Moment  # noqa: E402
from chibi_overlay.body.physics import Physics, Rect  # noqa: E402
from chibi_overlay.core_fx import CoreFX  # noqa: E402
from chibi_overlay.sprites import NEUTRAL, SpriteModel  # noqa: E402
from chibi_overlay.stage import (FLAT_IMPACT_S, PERFORM, THROW_SPEED, TRANSFORM_S, Overlays,  # noqa: E402
                                 Particle)
from chibi_overlay.wheel import POSES, PoseWheel, paint_wheel  # noqa: E402
from chibi_shared.protocol import Confirm, Hud  # noqa: E402

PACK = r"D:\Projects\Chibi-Agent-Project\Deployments\Raphael\assets\chibi\casual-coat\v01"
G3D = Path(os.environ.get("RAPHAEL_GIF_WORK", Path(os.environ.get("TEMP", ".")) / "raphael-gifs")) / "g3d"
FPS = 15
DT = 1.0 / FPS
RIG2D = motion.load(REPO / "overlay/rigs/raphael_sprites.toml")
RIG3D = motion.load(REPO / "overlay/rigs/raphael_3d.toml")
hud.load_fonts(r"D:\Projects\Chibi-Agent-Project\ChibiAgent\fonts")


def tick(dt: float = DT) -> None:
    CLOCK[0] += dt


def now_ms() -> int:
    return int(CLOCK[0] * 1000)


# --- drawing helpers --------------------------------------------------------------------------------
def background(w: int, h: int, taskbar: int = 0) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.fillRect(0, 0, w, h, QColor("#3a4d72"))  # flat: GIFs stay small
    if taskbar:
        p.fillRect(0, h - taskbar, w, taskbar, QColor(18, 22, 34, 235))
        p.fillRect(0, h - taskbar, w, 1, QColor(255, 255, 255, 40))
    p.end()
    return img


def caption(img: QImage, text: str, taskbar: int) -> None:
    if not text:
        return
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont("Segoe UI", 10)
    p.setFont(f)
    p.setPen(QColor(235, 240, 250))
    p.drawText(QRectF(12, img.height() - taskbar, img.width() - 24, taskbar),
               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.end()


def cursor(img: QImage, x: float, y: float, pressed: bool = False, ring: float = 0.0) -> None:
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if ring > 0:  # a click: an expanding ring
        p.setPen(QPen(QColor(255, 255, 255, int(220 * (1 - ring))), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), 6 + 20 * ring, 6 + 20 * ring)
    path = QPainterPath(QPointF(x, y))
    for dx, dy in ((0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)):
        path.lineTo(x + dx, y + dy)
    path.closeSubpath()
    p.setPen(QPen(QColor(0, 0, 0), 1.2))
    p.setBrush(QColor(255, 220, 120) if pressed else QColor(255, 255, 255))
    p.drawPath(path)
    p.end()


class Chibi:
    """The sprite chibi as the overlay drives it: rig-map clips (Puppet.play) plus stage params."""

    def __init__(self, height_px: float):
        self.model = SpriteModel(PACK, None)
        t = self.model.pack._walk_thread
        if t is not None:
            t.join()
        self.h = height_px
        neutral = self.model.pack.get(NEUTRAL)
        self.k = height_px / (self.model.pack.feet - neutral.top)
        self.half_w = self.model.pack.canvas[0] * self.k * 0.32
        self.clip = None

    def play(self, clip) -> None:
        if clip == self.clip:
            return
        self.clip = clip
        if clip.motion:
            self.model.StartMotion(clip.motion)
        self.model.SetExpression(clip.expression or "neutral")

    def draw(self, img: QImage, fx: float, fy: float, params: dict | None = None, left: bool = False,
             look: tuple[float, float] | None = None, alpha: float = 1.0) -> None:
        m = self.model
        m._applied = params or {}
        p = QPainter(img)
        p.setOpacity(alpha)
        cw = m.pack.canvas[0]
        p.translate(fx, fy)
        p.scale(-self.k if left else self.k, self.k)
        p.translate(-cw / 2, -m.pack.feet)
        m._xf = p.transform()
        if look is not None:
            m.Drag(*look)
        m.paint(p, CLOCK[0])
        p.end()


class Frames3D:
    """A recorded 3D clip (render3d.py): frames scaled to her on-screen height, feet at the bottom
    centre of the 520x1000 preview (30 px up, at 640 px tall)."""

    PREVIEW_H, FEET_UP = 640.0, 30.0

    def __init__(self, name: str, height_px: float, skip: int = 6):
        files = sorted((G3D / name).glob("f*.png"))[skip:]
        low = {"sleep": 360, "carried": 400, "fallflat": 400, "flatimpact": 400, "getup": 400}
        k = height_px / low.get(name, self.PREVIEW_H)
        self.frames = []
        for f in files:
            q = QImage(str(f))
            self.frames.append(q.scaled(int(q.width() * k), int(q.height() * k),
                                        Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        self.k, self.h = k, height_px

    def draw(self, img: QImage, i: int, fx: float, fy: float, hold: bool = False, alpha: float = 1.0,
             rotate: float = 0.0, left: bool = False) -> None:
        q = self.frames[min(i, len(self.frames) - 1) if hold else i % len(self.frames)]
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(alpha)
        p.translate(fx, fy)
        if rotate:
            p.rotate(rotate)
        if left:
            p.scale(-1, 1)
        p.drawImage(QPointF(-q.width() / 2, -q.height() + self.FEET_UP * self.k), q)
        p.end()


class Gif:
    def __init__(self, path: Path, fps: int = FPS):
        self.path, self.fps, self.frames = path, fps, []

    def add(self, img: QImage) -> None:
        q = img.convertToFormat(QImage.Format.Format_RGBA8888)
        self.frames.append(Image.frombuffer("RGBA", (q.width(), q.height()), bytes(q.constBits()),
                                            "raw", "RGBA", 0, 1).convert("RGB"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # one palette for the whole GIF, from a montage of frames: no flicker, smaller deltas
        pick = self.frames[:: max(1, len(self.frames) // 8)]
        w, h = self.frames[0].size
        mont = Image.new("RGB", (w * len(pick), h))
        for i, f in enumerate(pick):
            mont.paste(f, (i * w, 0))
        ref = mont.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pal = [f.quantize(palette=ref, dither=Image.Dither.NONE) for f in self.frames]
        pal[0].save(self.path, save_all=True, append_images=pal[1:], duration=int(1000 / self.fps),
                    loop=0, optimize=True, disposal=1)
        print(f"{self.path.name}: {len(self.frames)} frames, {self.path.stat().st_size // 1024} KB", flush=True)


def stage_stub(feet, h, half_w, form="chibi"):
    """What hud.Painter reads off a Stage."""
    st = SimpleNamespace(feet=feet, size={form: (h, half_w)}, form=form, core=CoreFX(), hidden=False,
                         ov=Overlays(), panels_on_chibi=True, character=None, particles=[], _t0=None)
    st.draw_form = lambda: st.form
    st.transform_progress = lambda: None if st._t0 is None else (CLOCK[0] - st._t0) / TRANSFORM_S
    return st


def particles(x: float, y: float, h: float, scale: float) -> list[Particle]:
    """Stage._start_transform's puff."""
    rnd = random.Random(3)
    return [Particle(x + rnd.uniform(-0.3, 0.3) * h, y - rnd.uniform(0, 1) * h, rnd.uniform(-60, 60),
                     rnd.uniform(-260, -80), rnd.random() < 0.35, rnd.uniform(0, 6.28)) for _ in range(140)]


def step_particles(ps: list[Particle], dt: float, scale: float) -> None:
    for p in ps:  # Stage._step_transform
        p.phase += dt * 6
        p.x += (p.vx + 80 * math.sin(p.phase)) * dt * scale
        p.y += p.vy * dt * scale


# --- 2D poses: one GIF per clip -------------------------------------------------------------------
POSES_2D = {
    # name: (mood or moment key, seconds, params)
    "idle": ("idle", 4.0, None),
    "wave": ("m:wave", 2.4, None),
    "cheer": ("happy", 2.0, None),
    "think": ("thinking", 2.0, {"ParamAngleY": 10.0}),
    "look_around": ("m:look_around", 2.4, None),
    "stretch": ("m:stretch", 2.0, None),
    "dance": ("dancing_excited", 3.0, None),
    "dance_vibe": ("dancing", 3.2, None),
    "sit": ("m:sit", 3.6, None),
    "sleep": ("sleeping", 2.4, {"ParamEyeLOpen": 0.0, "ParamEyeROpen": 0.0}),
    "talk": ("talking", 2.4, "lip"),
    "surprised": ("surprised", 1.2, None),
    "pout": ("pout", 1.6, None),
    "upset": ("crying", 1.6, None),
    "held": ("held", 1.2, "sway"),
    "fall": ("falling", 0.8, None),
    "land": ("soft_landing", 1.0, None),
    "walk": ("walking", 1.8, None),
    "analyse": ("working", 2.0, None),
    "notice": ("alert", 2.0, None),
}


def pose_gifs(out: Path, names) -> None:
    W, H = 300, 300
    her = Chibi(220)
    for name, (key, secs, extra) in POSES_2D.items():
        if names and name not in names:
            continue
        clip = RIG2D.moments[key[2:]] if key.startswith("m:") else RIG2D.moods[key]
        her.clip = None
        her.play(clip)
        her.model._blink_at = CLOCK[0] + 1.5
        gif = Gif(out / f"2d-{name}.gif")
        t0 = CLOCK[0]
        for i in range(int(secs * FPS)):
            t = CLOCK[0] - t0
            params = extra if isinstance(extra, dict) else {}
            if extra == "lip":
                params = {"ParamMouthOpenY": abs(math.sin(t * 9)) * (0.6 + 0.4 * math.sin(t * 2.3))}
            elif extra == "sway":
                params = {"ParamBodyAngleX": 8 * math.sin(t * 5)}
            if name == "walk":
                her.model.motion = clip.motion
            img = background(W, H)
            her.draw(img, W / 2, H - 28, params)
            gif.add(img)
            tick()
        gif.save()


# --- interactions (2D) ----------------------------------------------------------------------------
class Scene:
    """A strip of desktop with a taskbar, her, the real Brain and Physics, and a cursor."""

    def __init__(self, w=640, h=400, taskbar=36, body="2d", height_px=200.0):
        self.w, self.h, self.tb = w, h, taskbar
        self.floor = h - taskbar
        self.scale = height_px / 320.0  # her 2D height is 320 dip at 100 %
        self.brain = Brain(random.Random(5))
        self.brain._next_moment_at = 10 ** 15  # no idle moments in a scripted scene
        self.ph = Physics(self.scale, [Rect(0, 0, w, h - taskbar)], lambda x: self.floor)
        self.ph.place(w * 0.5, self.floor)
        self.body = body
        self.her = Chibi(height_px) if body == "2d" else None
        self.h3: dict[str, Frames3D] = {}
        self.height_px = height_px
        self.half_w = (self.her.half_w if self.her else height_px * 0.22)
        self.ph.half_width, self.ph.head_height = self.half_w, height_px
        self.cur = (w * 0.85, h * 0.4)
        self.pressed = False
        self.ring = 0.0
        self.text = ""
        self.params: dict = {}
        self.left = False
        self.look = None
        self.wheel = PoseWheel()
        self.st = stage_stub((self.ph.x, self.ph.y), height_px, self.half_w)
        self.mood_since = None
        self.clip3d = None
        self.clip3d_t0 = 0.0
        self.fall_flat = False
        self.landed_flat = False
        self.grab_low = False
        self.thrown = False
        self.overlay_3d = None  # (Frames3D, frame) override

    # clips
    def clip(self, rig):
        b = self.brain
        if b.mood == Mood.DANCING and b.performing and "dancing_excited" in rig.moods:
            return rig.moods["dancing_excited"]
        if b.mood == Mood.HELD and self.grab_low and "held_low" in rig.moods:
            return rig.moods["held_low"]
        if b.mood == Mood.FALLING and self.fall_flat and "falling_flat" in rig.moods:
            return rig.moods["falling_flat"]
        if b.mood == Mood.HARD_LANDING and not self.landed_flat and "hard_landing_high" in rig.moods:
            return rig.moods["hard_landing_high"]
        if b.mood == Mood.HARD_LANDING and "hard_landing_up" in rig.moods \
                and now_ms() - b.since >= FLAT_IMPACT_S * 1000:
            return rig.moods["hard_landing_up"]
        return rig.clip(b.mood, b.moment)

    def frames(self, motion_name: str) -> Frames3D:
        names = {"Idle": "idle", "Held": "held", "Carried": "carried", "Fall": "fall", "Land": "land",
                 "HardLand": "hardland", "FallFlat": "fallflat", "FlatImpact": "flatimpact",
                 "GetUp": "getup", "Upset": "upset", "Surprised": "surprised", "Pout": "pout",
                 "Happy": "cheer", "Sit": "sit", "Sleep": "sleep", "DanceExcited": "dance",
                 "Talk": "talk", "Think": "think", "Wave": "wave", "Walk": "walk"}
        key = names.get(motion_name, "idle")
        if key not in self.h3:
            self.h3[key] = Frames3D(key, self.height_px)
        return self.h3[key]

    # input
    def press(self):
        self.pressed, self.ring = True, 0.01
        self.press_at = (self.cur, CLOCK[0])
        self.grab = (self.ph.x - self.cur[0], self.ph.y - self.cur[1])
        self.dragging = False
        self.trail = []

    def move(self, x, y):
        self.cur = (x, y)
        if not self.pressed:
            return
        if not self.dragging and math.hypot(x - self.press_at[0][0], y - self.press_at[0][1]) > 6:
            self.dragging = True
            self.grab_low = self.grab[1] < 0.5 * self.height_px and self.body == "3d"
            self.brain.grab(now_ms())
        if self.dragging:
            self.trail.append((x, y, CLOCK[0]))
            self.ph.place(x + self.grab[0], y + self.grab[1])

    def release(self):
        self.pressed = False
        if self.dragging:
            tr = [q for q in self.trail if CLOCK[0] - q[2] < 0.1 + 1e-6]
            vx = vy = 0.0
            if len(tr) >= 2 and tr[-1][2] > tr[0][2]:
                d = tr[-1][2] - tr[0][2]
                vx, vy = (tr[-1][0] - tr[0][0]) / d, (tr[-1][1] - tr[0][1]) / d
            self.fall_flat = self.grab_low
            self.brain.release(now_ms())
            self.ph.throw_at(vx, vy)
            self.thrown = math.hypot(vx, vy) / self.scale >= THROW_SPEED
        else:
            self.brain.poke(now_ms())
            self.ring = 0.01
        self.dragging = False

    # one frame
    def step(self, gif: Gif, dt: float = DT):
        b, ph = self.brain, self.ph
        if not getattr(self, "dragging", False):
            if ph.step(dt) is not None:
                self.landed_flat = self.fall_flat
                b.land(now_ms(), flat=self.landed_flat, high=ph.y - ph.top_y > self.h * 0.5,
                       hurt=self.thrown or ph.wall_hit >= 900)
                self.fall_flat = self.thrown = False
        b.tick(now_ms(), quiet_for_ms=0, music=False)
        if self.wheel.open:
            self.wheel.track(self.cur)
        img = background(self.w, self.h, self.tb)
        params = dict(self.params)
        if b.mood == Mood.HELD and getattr(self, "trail", None):
            tr = [q for q in self.trail if CLOCK[0] - q[2] < 0.1 + 1e-6]
            vx = (tr[-1][0] - tr[0][0]) / max(1e-3, tr[-1][2] - tr[0][2]) if len(tr) > 1 else 0.0
            params["ParamBodyAngleX"] = max(-10, min(10, -vx / (60 * self.scale)))
        if b.mood == Mood.SLEEPING:
            params.update(ParamEyeLOpen=0.0, ParamEyeROpen=0.0)
        if self.body == "2d":
            self.her.play(self.clip(RIG2D))
            self.her.draw(img, ph.x, ph.y, params, self.left, self.look)
        elif self.overlay_3d is None:
            c = self.clip(RIG3D)
            if c != self.clip3d:
                self.clip3d, self.clip3d_t0 = c, CLOCK[0]
            fr = self.frames(c.motion)
            i = int((CLOCK[0] - self.clip3d_t0) * FPS)
            once = c.motion in ("HardLand", "FlatImpact", "GetUp", "Land", "Carried", "Surprised", "Happy", "Wave")
            fr.draw(img, i, ph.x, ph.y, hold=once)
        else:
            fr, i = self.overlay_3d
            fr.draw(img, i, ph.x, ph.y)
        self.st.feet = (ph.x, ph.y)
        self.st.core.update(dt, thinking=b.mood == Mood.THINKING, speaking=b.mood == Mood.TALKING,
                            level=params.get("ParamMouthOpenY", 0.0))
        hud.Painter(img, (0, 0), 1.0, self.st).paint()
        paint_wheel(img, (0, 0), 1.0, self.wheel)
        caption(img, self.text, self.tb)
        cursor(img, *self.cur, self.pressed, self.ring)
        if self.ring:
            self.ring = self.ring + 0.12 if self.ring < 1 else 0.0
        gif.add(img)
        tick(dt)

    def glide(self, gif, to, secs, ease=True):
        x0, y0 = self.cur
        n = max(1, int(secs * FPS))
        for i in range(1, n + 1):
            t = i / n
            if ease:
                t = t * t * (3 - 2 * t)
            self.move(x0 + (to[0] - x0) * t, y0 + (to[1] - y0) * t)
            self.step(gif)

    def wait(self, gif, secs):
        for _ in range(int(secs * FPS)):
            self.step(gif)


def chest(sc: Scene) -> tuple[float, float]:
    return sc.ph.x, sc.ph.y - sc.height_px * 0.55


def scene_drag_throw(out: Path, body: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=720, h=440)
    gif = Gif(out / f"{body}-drag-throw.gif")
    sc.wait(gif, 0.4)
    sc.text = "Drag her: she hangs from the cursor and leans against the motion"
    sc.glide(gif, chest(sc), 0.6)
    sc.press()
    sc.glide(gif, (sc.cur[0] - 120, sc.cur[1] - 170), 0.8)
    sc.glide(gif, (sc.cur[0] + 90, sc.cur[1] - 10), 0.6)
    sc.text = "Let go fast: thrown. She flies, bounces off the edge, lands and cries"
    for i in range(4):
        sc.move(sc.cur[0] - 70, sc.cur[1] - 20)
        sc.step(gif)
    sc.release()
    sc.wait(gif, 3.6)
    gif.save()


def scene_drop(out: Path, body: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=720, h=440)
    gif = Gif(out / f"{body}-drop.gif")
    sc.wait(gif, 0.3)
    sc.text = "A short drop (under half the screen): a soft landing"
    sc.glide(gif, chest(sc), 0.5)
    sc.press()
    sc.glide(gif, (sc.cur[0] - 40, sc.cur[1] - 60), 0.6)
    sc.wait(gif, 0.3)
    sc.release()
    sc.wait(gif, 1.6)
    sc.text = "A high drop (over half the screen): the hard landing"
    sc.glide(gif, chest(sc), 0.5)
    sc.press()
    sc.glide(gif, (sc.cur[0] + 60, 60 + sc.height_px * 0.55), 0.9)
    sc.wait(gif, 0.3)
    sc.release()
    sc.wait(gif, 3.0)
    gif.save()


def scene_carried(out: Path) -> None:
    sc = Scene(body="3d", height_px=230, w=720, h=440)
    gif = Gif(out / "3d-carried-drop.gif")
    sc.wait(gif, 0.3)
    sc.text = "Picked up below the waist: carried flat"
    sc.glide(gif, (sc.ph.x, sc.ph.y - sc.height_px * 0.3), 0.5)
    sc.press()
    sc.glide(gif, (sc.cur[0] - 60, sc.cur[1] - 90), 0.8)
    sc.wait(gif, 0.8)
    sc.text = "Dropped: face down, flat on the floor, then she gets up"
    sc.release()
    sc.wait(gif, 3.6)
    gif.save()


def scene_pokes(out: Path, body: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=520, h=400)
    gif = Gif(out / f"{body}-pokes.gif")
    sc.wait(gif, 0.3)

    def poke():
        sc.press()
        sc.step(gif)
        sc.release()
        sc.step(gif)
        sc.step(gif)

    sc.text = "One poke: surprised"
    sc.glide(gif, chest(sc), 0.5)
    poke()
    sc.wait(gif, 1.4)
    sc.text = "Three pokes within 2 s: she pouts"
    for _ in range(3):
        poke()
    sc.wait(gif, 1.6)
    sc.brain._set(Mood.IDLE, now_ms(), None)
    sc.brain._pokes.clear()
    sc.wait(gif, 0.3)
    sc.text = "Five pokes: she cries"
    for _ in range(5):
        poke()
    sc.wait(gif, 2.2)
    gif.save()


def scene_long_press(out: Path) -> None:
    sc = Scene(body="2d", w=520, h=400)
    gif = Gif(out / "2d-long-press.gif")
    sc.wait(gif, 0.3)
    sc.text = "Hold the button on her for 0.6 s: happy, and she giggles (voice)"
    sc.glide(gif, chest(sc), 0.5)
    sc.press()
    sc.ring = 0.0
    sc.wait(gif, 0.6)
    sc.brain.long_press(now_ms())
    sc.wait(gif, 1.6)
    sc.pressed = False
    sc.wait(gif, 0.6)
    gif.save()


def scene_wheel(out: Path, body: str, pick: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=640, h=440)
    sc.ph.place(sc.w * 0.36, sc.floor)
    gif = Gif(out / f"{body}-pose-wheel.gif")
    sc.wait(gif, 0.3)
    sc.text = "Right-click her: the pose wheel"
    sc.glide(gif, chest(sc), 0.5)
    sc.ring = 0.01
    sc.wheel.show((sc.ph.x, sc.ph.y), sc.height_px, sc.half_w, sc.scale * (230 / 230),
                  (0, 0, sc.w, sc.floor))
    sc.wait(gif, 0.4)
    cx, cy = sc.wheel.centre
    r = (sc.wheel.outer + sc.wheel.inner) / 2
    target = [p.key for p in POSES].index(pick)
    for i in range(target + 1):  # sweep clockwise from Wave to the pick
        a = math.radians(i * 45)
        sc.glide(gif, (cx + r * math.sin(a), cy - r * math.cos(a)), 0.35)
    sc.text = f"Click {POSES[target].label}: she plays it"
    sc.wait(gif, 0.3)
    sc.ring = 0.01
    sc.wheel.close()
    mood, moment, ms = PERFORM[pick]
    sc.brain.perform(mood, now_ms(), ms, moment)
    sc.glide(gif, (sc.w - 40, sc.h * 0.3), 0.6)
    sc.wait(gif, 3.0)
    gif.save()


def scene_talk(out: Path, body: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=640, h=420)
    sc.ph.place(sc.w * 0.3, sc.floor)
    sc.cur = (sc.w + 50, -50)
    gif = Gif(out / f"{body}-answer.gif")
    sc.text = "Asked something: the thinking core spins above her"
    sc.brain.request_mood(Mood.THINKING, now_ms())
    if body == "2d":
        sc.params = {"ParamAngleY": 10.0}
    sc.wait(gif, 2.0)
    sc.params = {}
    sc.text = "Her answer: words in the glass panel, the core pulses with her voice"
    sc.brain.request_mood(Mood.TALKING, now_ms())
    sc.st.ov.bubble = "Answer. Your next meeting is at 15:30, Saber: the design review."
    sc.st.ov.bubble_until = CLOCK[0] + 60
    t0 = CLOCK[0]
    if body == "3d":
        sc.h3["talk"] = Frames3D("answer_point", sc.height_px)
    for _ in range(int(3.2 * FPS)):
        t = CLOCK[0] - t0
        sc.params = {"ParamMouthOpenY": abs(math.sin(t * 9)) * (0.5 + 0.4 * math.sin(t * 2.3))}
        sc.step(gif)
    gif.save()


def scene_confirm(out: Path) -> None:
    sc = Scene(body="2d", w=640, h=420)
    sc.ph.place(sc.w * 0.3, sc.floor)
    gif = Gif(out / "2d-confirm.gif")
    sc.text = "A tool run: the task card beside her (she analyses with her orb)"
    sc.brain.request_mood(Mood.WORKING, now_ms())
    sc.st.ov.hud = Hud(title="Searching files", items=["D:\\Projects  ·  *.pdf", "12 found"], progress=0.0)
    for i in range(int(2.0 * FPS)):
        sc.st.ov.hud = Hud(title="Searching files", items=["D:\\Projects  ·  *.pdf", f"{i // 3} found"],
                           progress=i / (2.0 * FPS))
        sc.step(gif)
    sc.st.ov.hud = None
    sc.text = "A side-effect tool asks first: Yes / No beside her"
    sc.brain.request_mood(Mood.WORKING, now_ms())
    sc.st.ov.confirm = Confirm(call_id="c1", tool="move_file", summary="move 3 files",
                               detail="to D:\\Archive\\2026")
    sc.wait(gif, 0.6)
    yes = sc.st.ov.rects.get("yes")
    sc.glide(gif, ((yes[0] + yes[2]) / 2, (yes[1] + yes[3]) / 2), 0.7)
    sc.ring, sc.pressed = 0.01, True
    sc.step(gif)
    sc.pressed = False
    sc.st.ov.confirm = None
    sc.brain.request_mood(Mood.HAPPY, now_ms())
    sc.wait(gif, 1.4)
    gif.save()


def scene_gaze(out: Path) -> None:
    sc = Scene(body="2d", w=480, h=400, height_px=240)
    gif = Gif(out / "2d-eye-follow.gif")
    sc.text = "Her eyes follow the cursor (8 directions; Customize -> Behaviour)"
    hx, hy = sc.ph.x, sc.ph.y - sc.height_px * 0.62
    for i in range(int(4.0 * FPS)):
        a = i / (4.0 * FPS) * 2 * math.pi
        sc.cur = (hx + 170 * math.cos(a), hy + 120 * math.sin(a))
        sc.look = sc.cur
        sc.step(gif)
    gif.save()


def scene_walk(out: Path, body: str) -> None:
    sc = Scene(body=body, height_px=200 if body == "2d" else 230, w=600, h=380)
    sc.ph.place(sc.w * 0.25, sc.floor)
    sc.cur = (sc.w + 50, -50)
    gif = Gif(out / f"{body}-walk-home.gif")
    sc.text = "Away from her home spot: she walks back along the taskbar"
    home = sc.w * 0.7
    speed = (90.0 * sc.scale) if body == "2d" else (0.5 * sc.height_px)
    sc.brain.away_from_home = True
    sc.brain._set(Mood.WALKING, now_ms(), None)
    while True:
        done = sc.ph.walk_toward(home, speed, DT)
        sc.left = home < sc.ph.x
        sc.step(gif)
        if done:
            break
    sc.brain.away_from_home = False
    sc.brain.arrived(now_ms())
    sc.wait(gif, 0.8)
    gif.save()


def scene_transform(out: Path) -> None:
    """The chibi outfit: 2D chibi <-> its serious form, the 3D Raphael ("serious mode")."""
    W, H, TB = 560, 520, 36
    floor = H - TB
    her = Chibi(170)
    her.play(RIG2D.moods["idle"])
    idle3d = Frames3D("idle", 420)
    gif = Gif(out / "transform-serious.gif", fps=30)
    st = stage_stub((W / 2, floor), 170, her.half_w)
    dt = 1 / 30

    def frame(form, text, i):
        img = background(W, H, TB)
        if form == "chibi":
            her.draw(img, W / 2, floor)
        elif form == "serious":
            idle3d.draw(img, i // 2, W / 2, floor)
        hud.Painter(img, (0, 0), 1.0, st).paint()
        caption(img, text, TB)
        gif.add(img)
        CLOCK[0] += dt

    i = 0
    for _ in range(30):
        frame("chibi", '"Serious mode": the chibi turns into her serious form', i); i += 1
    for to in ("serious", "chibi"):
        st._t0 = CLOCK[0]
        st.particles = particles(W / 2, floor, 170 if to == "serious" else 420, 1.0)
        form = "chibi" if to == "serious" else "serious"
        while CLOCK[0] - st._t0 < TRANSFORM_S:
            age = CLOCK[0] - st._t0
            if age >= TRANSFORM_S / 2:
                form = to
            shown = None if abs(age - TRANSFORM_S / 2) < 0.08 else form
            step_particles(st.particles, dt, 1.0)
            frame(shown, "0.6 s of cyan and gold glyph particles; the form swaps halfway", i); i += 1
        st._t0, st.particles = None, []
        for _ in range(45 if to == "serious" else 30):
            frame(to, '"Chibi mode" turns her back' if to == "serious" else "", i); i += 1
    gif.save()


def scene_switch_body(out: Path) -> None:
    """Tray -> Switch to 3D model / Switch to 2D art: the same puff, no change of form."""
    W, H, TB = 520, 440, 36
    floor = H - TB
    her = Chibi(200)
    her.play(RIG2D.moods["idle"])
    idle3d = Frames3D("idle", 290)
    gif = Gif(out / "switch-body.gif", fps=30)
    st = stage_stub((W / 2, floor), 200, her.half_w)
    dt = 1 / 30
    i = 0
    seq = [("2d", 24, "Tray -> Switch to 3D model"), ("puff", 0, "3d"), ("3d", 45, "The 3D body, drawn by Godot"),
           ("puff", 0, "2d"), ("2d", 24, "Tray -> Switch to 2D art")]
    body = "2d"
    for kind, n, text in seq:
        if kind == "puff":
            st._t0 = CLOCK[0]
            st.particles = particles(W / 2, floor, 220, 1.0)
            while CLOCK[0] - st._t0 < TRANSFORM_S:
                age = CLOCK[0] - st._t0
                if age >= TRANSFORM_S / 2:
                    body = text
                step_particles(st.particles, dt, 1.0)
                img = background(W, H, TB)
                if abs(age - TRANSFORM_S / 2) >= 0.08:
                    her.draw(img, W / 2, floor) if body == "2d" else idle3d.draw(img, i // 2, W / 2, floor)
                hud.Painter(img, (0, 0), 1.0, st).paint()
                caption(img, "The outfit puff: the body swaps halfway", TB)
                gif.add(img)
                CLOCK[0] += dt
                i += 1
            st._t0, st.particles = None, []
            continue
        for _ in range(n):
            img = background(W, H, TB)
            her.draw(img, W / 2, floor) if body == "2d" else idle3d.draw(img, i // 2, W / 2, floor)
            caption(img, text, TB)
            gif.add(img)
            CLOCK[0] += dt
            i += 1
    gif.save()


def turn_gif(out: Path) -> None:
    W, H = 300, 380
    gif = Gif(out / "3d-turn.gif", fps=8)
    for deg in list(range(0, 360, 30)):
        fr = Frames3D(f"turn_{deg:03d}", 330, skip=4)
        img = background(W, H, 30)
        fr.draw(img, 0, W / 2, H - 30, hold=True)
        caption(img, f"Middle-drag: she turns ({deg} deg)", 30)
        gif.add(img)
    gif.save()


def pose_gifs_3d(out: Path, names) -> None:
    W, H = 300, 380
    for d in sorted(G3D.iterdir()):
        if not d.is_dir() or d.name.startswith(("turn_", "test", "wave20")) or (names and d.name not in names):
            continue
        if not list(d.glob("f*.png")):
            continue
        fr = Frames3D(d.name, 300)
        wide = d.name in ("sleep", "carried", "fallflat", "flatimpact")
        img_w = 380 if wide else W
        gif = Gif(out / f"3d-{d.name}.gif")
        for i in range(len(fr.frames)):
            img = background(img_w, H)
            fr.draw(img, i, img_w / 2, H - 22)
            gif.add(img)
        gif.save()


SCENES = {
    "poses2d": lambda o, n: pose_gifs(o, n),
    "poses3d": lambda o, n: pose_gifs_3d(o, n),
    "drag2d": lambda o, n: scene_drag_throw(o, "2d"),
    "drag3d": lambda o, n: scene_drag_throw(o, "3d"),
    "drop2d": lambda o, n: scene_drop(o, "2d"),
    "drop3d": lambda o, n: scene_drop(o, "3d"),
    "carried": lambda o, n: scene_carried(o),
    "pokes2d": lambda o, n: scene_pokes(o, "2d"),
    "pokes3d": lambda o, n: scene_pokes(o, "3d"),
    "longpress": lambda o, n: scene_long_press(o),
    "wheel2d": lambda o, n: scene_wheel(o, "2d", "dance"),
    "wheel3d": lambda o, n: scene_wheel(o, "3d", "sit"),
    "talk2d": lambda o, n: scene_talk(o, "2d"),
    "talk3d": lambda o, n: scene_talk(o, "3d"),
    "confirm": lambda o, n: scene_confirm(o),
    "gaze": lambda o, n: scene_gaze(o),
    "walk2d": lambda o, n: scene_walk(o, "2d"),
    "walk3d": lambda o, n: scene_walk(o, "3d"),
    "transform": lambda o, n: scene_transform(o),
    "switch": lambda o, n: scene_switch_body(o),
    "turn": lambda o, n: turn_gif(o),
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    args = sys.argv[2:]
    scenes = [a for a in args if a in SCENES] or list(SCENES)
    names = [a for a in args if a not in SCENES]
    for s in scenes:
        try:
            SCENES[s](out, names)
        except Exception as e:  # keep going; report
            import traceback
            traceback.print_exc()
            print(f"scene {s} failed: {e}", flush=True)
