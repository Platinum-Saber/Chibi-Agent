"""One Live2D model inside one window's GL context, placed by her feet position.

live2d-py draws a model centred in the viewport, where one offset/scale unit
is half the framebuffer height (measured in spike 1 and M2: k = h/2, y up).
So each rig is measured once, at scale 1 on the primary window (`Geom`), and
every window derives its scale and offsets from that; no per-window readback
(the readback went stale on the second monitor's window).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import live2d
import numpy as np
import OpenGL.GL as gl

from .body.motion import Clip, RigMap, looping_groups

log = logging.getLogger(__name__)


def read_bbox(w: int, h: int):
    a = np.frombuffer(gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE),
                      dtype=np.uint8).reshape(h, w, 4)[::-1, :, 3]
    ys, xs = np.nonzero(a > 8)
    return None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


@dataclass(frozen=True)
class Geom:
    """The rig at scale 1, offset 0, in view units (1 = half the framebuffer height)."""
    height: float
    half_width: float
    centre_x: float  # from the viewport centre, + right
    bottom: float    # from the viewport centre, + down

    @staticmethod
    def measure(bbox, fb: tuple[int, int]) -> Geom:
        x0, y0, x1, y1 = bbox
        w, h = fb
        u = h / 2
        return Geom((y1 - y0) / u, (x1 - x0) / 2 / u, ((x0 + x1) / 2 - w / 2) / u, (y1 - h / 2) / u)


class Puppet:
    def __init__(self, model_json: str, rig: RigMap, dpr: float, fb_size: tuple[int, int]):
        self.rig, self.dpr = rig, dpr
        self.model = live2d.Model()
        self.model.LoadModelJson(model_json)
        self.model.Resize(*fb_size)
        self.fb = fb_size
        self.scale = 1.0
        self.base = (0.0, 0.0)
        self.u = fb_size[1] / 2
        self.height = 0.0  # px, feet to head top
        self.half_width = 0.0
        self.clip: Clip | None = None
        self.loops = looping_groups(model_json)
        self.flip = False
        self.ready = False

    def configure(self, g: Geom, fb: tuple[int, int]) -> None:
        w, h = fb
        self.fb, self.u = fb, h / 2
        self.model.Resize(w, h)
        self.scale = self.rig.height_dip * self.dpr / (g.height * self.u)
        self.model.SetScale(self.scale)
        self.base = (w / 2 + g.centre_x * self.scale * self.u, h / 2 + g.bottom * self.scale * self.u)
        self.height = g.height * self.scale * self.u
        self.half_width = g.half_width * self.scale * self.u
        self.ready = True

    def place(self, x: float, y: float) -> None:
        """Feet at window-local physical px (x right, y down)."""
        self.model.SetOffset((x - self.base[0]) / self.u, -(y - self.base[1]) / self.u)

    def face(self, left: bool) -> None:
        if left != self.flip:
            self.flip = left
            self.model.SetScaleX(-self.scale if left else self.scale)

    def play(self, clip: Clip) -> None:
        if clip == self.clip:
            # live2d-py ignores motion3 Meta.Loop, so a looping clip is restarted here
            if clip.motion in self.loops and self.model.IsMotionFinished():
                self._start(clip)
            return
        self.clip = clip
        if clip.motion:
            self._start(clip)
        if clip.expression:
            self.model.SetExpression(clip.expression)
        else:
            self.model.ResetExpression()

    def _start(self, clip: Clip) -> None:
        if clip.index is None:
            self.model.StartRandomMotion(clip.motion, live2d.MotionPriority.FORCE)
        else:
            self.model.StartMotion(clip.motion, clip.index, live2d.MotionPriority.FORCE)

    def set_param(self, pid: str, value: float) -> None:
        self.model.SetSaveParamById(pid, value, 1.0)  # survives Update()
