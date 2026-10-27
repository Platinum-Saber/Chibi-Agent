"""A stand-in for live2d.Model that draws the vector rig with QPainter.

`Puppet` and `MonitorWindow` call the live2d-py API; this class answers the
calls they use, in the same units (one view unit = half the framebuffer
height, y up, offsets from the viewport centre), so the window's calibration,
placement, mirroring and alpha hit test work unchanged. Expressions pick a
base Pose by name (rig map names); motions are accepted but not animated yet
(step 2), so a clip reads as finished at once.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import replace

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter, QTransform

from .pose import EXPRESSIONS, NEUTRAL, Eyes, Pose
from .raphael import draw_raphael

RIG_H = 180.0  # rig units over two view units (the framebuffer height) at scale 1: room for the halo
CENTRE = (50.0, 64.0)
EASE_S = 0.12  # time constant for easing toward the target pose


class VectorModel:
    def __init__(self, outfit: str, widget):
        self.outfit, self.widget = outfit, widget  # one outfit for now: "coat"
        self.fb = (1, 1)
        self.scale_x = self.scale_y = 1.0
        self.offset = (0.0, 0.0)
        self.base = NEUTRAL
        self.pose = NEUTRAL
        self.params: dict[str, float] = {}
        self.gaze = (0.0, 0.0)
        self._xf = QTransform()
        self._t0 = self._t = time.monotonic()
        self._blink_at = self._t + random.uniform(2, 6)

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
        self.base = EXPRESSIONS.get(name, NEUTRAL)

    def ResetExpression(self) -> None:
        self.base = NEUTRAL

    def StartMotion(self, *_args) -> None:
        pass

    def StartRandomMotion(self, *_args) -> None:
        pass

    def IsMotionFinished(self) -> bool:
        return True

    def SetSaveParamById(self, pid: str, value: float, _weight: float = 1.0) -> None:
        self.params[pid] = value

    def Drag(self, x: float, y: float) -> None:
        """Look toward window px (x, y): the target mapped into rig units, relative to her eyes."""
        inv, ok = self._xf.inverted()
        if not ok:
            return
        q = inv.map(QPointF(x, y))
        self.gaze = (max(-1.0, min(1.0, (q.x() - 50) / 45)), max(-1.0, min(1.0, (q.y() - 70) / 60)))

    def Update(self) -> None:
        now = time.monotonic()
        dt, self._t = min(now - self._t, 0.1), now
        t = now - self._t0
        target = self._target(t, now)
        k = 1.0 - math.exp(-dt / EASE_S) if dt > 0 else 1.0
        self.pose = self.pose.approach(target, k)
        self.params.clear()  # the stage writes its procedural params every frame

    def Draw(self) -> None:
        w, h = self.fb
        u = h / 2
        xf = QTransform()
        xf.translate(w / 2 + self.offset[0] * u, h / 2 - self.offset[1] * u)
        xf.scale(self.scale_x * u * 2 / RIG_H, self.scale_y * u * 2 / RIG_H)
        xf.translate(-CENTRE[0], -CENTRE[1])
        self._xf = xf
        p = QPainter(self.widget)
        dpr = self.widget.devicePixelRatioF()
        p.setTransform(xf * QTransform.fromScale(1 / dpr, 1 / dpr))  # framebuffer px -> logical px
        draw_raphael(p, self.pose, self._t - self._t0)
        p.end()

    # --- pose ------------------------------------------------------------------------------------------
    def _target(self, t: float, now: float) -> Pose:
        b, prm = self.base, self.params
        breath = math.sin(t * 2 * math.pi / 3.6)
        pose = replace(
            b,
            squash=b.squash + 0.012 * breath,
            hair_sway=b.hair_sway + 0.25 * math.sin(t * 2 * math.pi / 4.4),
            mouth_open=prm.get("ParamMouthOpenY", b.mouth_open),
            body_tilt=b.body_tilt + 0.8 * prm.get("ParamBodyAngleX", 0.0),
            head_tilt=b.head_tilt + prm.get("ParamAngleZ", 0.0),
            head_nod=b.head_nod - prm.get("ParamAngleY", 0.0) / 30,
        )
        if b.eyes == Eyes.OPEN and b.gaze_x == 0 and b.gaze_y == 0:
            pose = replace(pose, gaze_x=self.gaze[0], gaze_y=self.gaze[1], head_turn=b.head_turn + 0.4 * self.gaze[0])
        if min(prm.get("ParamEyeLOpen", 1.0), prm.get("ParamEyeROpen", 1.0)) < 0.5:
            pose = replace(pose, eyes=Eyes.CLOSED)
        if pose.eyes == Eyes.OPEN:
            if now >= self._blink_at:
                if now >= self._blink_at + 0.12:
                    self._blink_at = now + random.uniform(2, 6)
                else:
                    pose = replace(pose, eyes=Eyes.CLOSED)
        return pose
