"""Customize Raphael (tray): what each mood plays, her size and outfit, behaviour, sprite
sequences and her voice, with a live preview of her.

Edits go into a working copy of `character.Character`. Apply hands it to the stage (and
the voice process, through the agent); Save also writes %APPDATA%\\ChibiAgent\\character.toml.
The preview is a second SpriteModel on the same pack, painted in the window; Live2D
outfits can be mapped and resized here but show only on the desktop.
"""
from __future__ import annotations

import copy
import json
import logging
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QTransform
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QPushButton, QSlider, QSpinBox,
                               QTableWidget, QTabWidget, QVBoxLayout, QWidget)

from chibi_shared import config, paths
from chibi_shared.protocol import Command, VoiceTune

from . import character, sprites

log = logging.getLogger(__name__)
KOKORO_GROUPS = {"af": "American female", "am": "American male", "bf": "British female", "bm": "British male"}
TEST_LINE = "Understood, Sir. The report is ready."


def voice_msg(v: character.VoiceSettings) -> VoiceTune:
    return VoiceTune(engine=v.engine if v.engine in ("f5", "kokoro") else "f5", voice=v.voice,
                     speed=v.speed, nfe=v.nfe)


def _model3_options(path: str) -> tuple[list[str], list[str]]:
    """A Live2D model's motion groups and expression names."""
    try:
        refs = json.loads(Path(path).read_text(encoding="utf-8-sig"))["FileReferences"]
    except (OSError, ValueError, KeyError):
        return [], []
    return sorted(refs.get("Motions", {})), sorted(e.get("Name", "") for e in refs.get("Expressions", []))


class Preview(QWidget):
    """Her, painted from the pack in the window; her eyes follow the mouse over it."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 400)
        self.setMouseTracking(True)
        self.model: sprites.SpriteModel | None = None
        self.note = ""
        self._xf = QTransform()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

    def load(self, rig_path: str) -> None:
        self.model, self.note = None, ""
        if rig_path.startswith(sprites.PREFIX):
            try:
                self.model = sprites.SpriteModel(rig_path.removeprefix(sprites.PREFIX), None)
            except Exception as e:  # a broken pack must not break the window
                log.warning("preview: %s", e)
                self.note = f"Can't load this outfit's art:\n{e}"
        else:
            self.note = "The live preview is for drawn (sprite) outfits.\nLive2D outfits show on the desktop after Apply."
        self.update()

    def play(self, motion: str | None, expression: str | None) -> None:
        if self.model is not None:
            self.model.StartMotion(motion or "Idle")
            self.model.SetExpression(expression or "neutral")

    def showEvent(self, e) -> None:
        self.timer.start(33)
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self.timer.stop()
        super().hideEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self.model is not None:
            inv, ok = self._xf.inverted()
            if ok:
                q = inv.map(QPointF(e.position()))
                self.model._look = (q.x(), q.y())

    def leaveEvent(self, e) -> None:
        if self.model is not None:
            self.model._look = None

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#DDE2EA"))
        m = self.model
        if m is None:
            p.setPen(QColor("#40465A"))
            p.drawText(self.rect().adjusted(16, 16, -16, -16), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.note)
            return
        cw, ch = m.pack.canvas
        s = min(self.width() / cw, self.height() / ch) * 0.96
        xf = QTransform()
        xf.translate((self.width() - cw * s) / 2, (self.height() - ch * s) / 2)
        xf.scale(s, s)
        self._xf = xf
        p.setTransform(xf)
        m.Update()
        m.paint(p, time.monotonic())


class CustomizeDialog(QDialog):
    def __init__(self, stage, send):
        super().__init__()
        self.stage, self.send = stage, send
        self.setWindowTitle("Customize Raphael")
        self.resize(1040, 660)
        self.vcfg = config.load().get("voice", {})
        self.ch = character.Character()
        self.outfit = stage.outfit
        self.base = None  # the outfit's chibi RigMap without Kryo's overrides
        self._filling = False  # widgets being filled from self.ch: ignore their change signals
        self._voice_sent = False

        self.preview = Preview()
        self.play_combo = QComboBox()
        play = QPushButton("▶ Play")
        play.clicked.connect(lambda: self._play_row(self.play_combo.currentData()))
        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(self.play_combo, 1)
        row.addWidget(play)
        left.addLayout(row)
        left.addWidget(QLabel("Move the mouse over her: her eyes follow it."))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._moods_tab(), "Moods")
        self.tabs.addTab(self._look_tab(), "Look")
        self.tabs.addTab(self._behaviour_tab(), "Behaviour")
        self.tabs.addTab(self._sequences_tab(), "Sequences")
        self.tabs.addTab(self._voice_tab(), "Voice")

        self.status = QLabel("")
        buttons = QHBoxLayout()
        for text, fn in (("Apply", self.apply), ("Save", self.save_now), ("Reset to defaults", self.reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        right = QVBoxLayout()
        right.addWidget(self.tabs, 1)
        right.addLayout(buttons)
        lay = QHBoxLayout(self)
        lay.addLayout(left, 2)
        lay.addLayout(right, 3)

    # --- opening ---------------------------------------------------------------------------------
    def show_current(self) -> None:
        """Show it with what she wears and does now."""
        self.ch = copy.deepcopy(self.stage.character)
        self._load_outfit(self.stage.outfit)
        self._fill_behaviour()
        self._fill_voice()
        self.status.setText("")
        self.show()
        self.raise_()
        self.activateWindow()

    def _rig_path(self) -> str:
        return self.stage.wardrobe.outfits[self.outfit].rigs["chibi"]

    def _load_outfit(self, name: str) -> None:
        self.outfit = name
        try:
            self.base = self.stage.wardrobe.outfits[name].load_maps(self.stage.pkg)["chibi"]
        except (OSError, ValueError) as e:
            self.base = None
            self.status.setText(f"Can't read {name}'s mood map: {e}")
        self.preview.load(self._rig_path())
        if self.preview.model is not None:
            self.preview.model.tune(self.ch, self.outfit)
        self._filling = True
        self.outfit_combo.setCurrentText(name)
        tw = self.ch.outfits.get(name)
        self.height.setValue((tw.height_dip if tw and tw.height_dip else None) or (self.base.height_dip if self.base else 320))
        sprite = self.preview.model is not None
        self.wear_mask.setChecked(tw.mask if tw else False)
        self.wear_sword.setChecked(tw.sword if tw else True)
        self.wear_mask.setEnabled(sprite)
        self.wear_sword.setEnabled(sprite)
        self._filling = False
        self._fill_moods()
        self._fill_sequences()
        self.preview.play("Idle", "neutral")  # filling the sequence list previewed its first entry

    # --- Moods -----------------------------------------------------------------------------------
    def _moods_tab(self) -> QWidget:
        self.moods = QTableWidget(0, 4)
        self.moods.setHorizontalHeaderLabels(["When she is…", "She plays", "With the face", ""])
        h = self.moods.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.moods.verticalHeader().setVisible(False)
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("What each mood and idle moment shows. Moments play now and then while she idles."))
        v.addWidget(self.moods)
        return w

    def _options(self) -> tuple[list[str], list[str]]:
        m = self.preview.model
        if m is not None:
            return sorted(m.sequences), [k.split("/", 1)[1] for k in m.pack.keys("expressions")]
        return _model3_options(self._rig_path())

    def _rows(self) -> list[tuple[str, str]]:
        """(table, name) for every mood and moment in the outfit's map."""
        if self.base is None:
            return []
        return [("moods", k) for k in self.base.moods] + [("moments", k) for k in self.base.moments]

    def _clip(self, table: str, name: str) -> tuple[str | None, str | None]:
        tw = self.ch.outfits.get(self.outfit)
        over = getattr(tw, table).get(name) if tw else None
        if over:
            return over.get("motion"), over.get("expression")
        c = getattr(self.base, table)[name]
        return c.motion, c.expression

    def _fill_moods(self) -> None:
        self._filling = True
        motions, faces = self._options()
        rows = self._rows()
        self.moods.setRowCount(len(rows))
        self.play_combo.clear()
        for r, (table, name) in enumerate(rows):
            label = name.replace("_", " ") if table == "moods" else f"moment: {name.replace('_', ' ')}"
            self.moods.setCellWidget(r, 0, QLabel(f"  {label}  "))
            motion, face = self._clip(table, name)
            mc, fc = QComboBox(), QComboBox()
            mc.addItems(["(none)", *motions])
            fc.addItems(["(none)", *faces])
            mc.setCurrentText(motion or "(none)")
            fc.setCurrentText(face or "(none)")
            for c in (mc, fc):
                c.currentTextChanged.connect(lambda _t, t=table, n=name, a=mc, b=fc: self._set_clip(t, n, a, b))
            go = QPushButton("▶")
            go.setFixedWidth(34)
            go.clicked.connect(lambda _=False, t=table, n=name: self._play_row((t, n)))
            self.moods.setCellWidget(r, 1, mc)
            self.moods.setCellWidget(r, 2, fc)
            self.moods.setCellWidget(r, 3, go)
            self.play_combo.addItem(label, (table, name))
        self._filling = False

    def _set_clip(self, table: str, name: str, mc: QComboBox, fc: QComboBox) -> None:
        if self._filling:
            return
        pick = lambda c: None if c.currentText() == "(none)" else c.currentText()  # noqa: E731
        getattr(self.ch.tweaks(self.outfit), table)[name] = {
            k: v for k, v in (("motion", pick(mc)), ("expression", pick(fc))) if v}
        self._play_row((table, name))

    def _play_row(self, row) -> None:
        if row and self.base is not None:
            self.preview.play(*self._clip(*row))

    # --- Look ------------------------------------------------------------------------------------
    def _look_tab(self) -> QWidget:
        self.outfit_combo = QComboBox()
        self.outfit_combo.addItems(self.stage.wardrobe.names)
        self.outfit_combo.currentTextChanged.connect(self._outfit_picked)
        self.height = QSpinBox()
        self.height.setRange(100, 900)
        self.height.setSingleStep(10)
        self.height.setSuffix(" px (at 100 % scaling)")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(100, 900)
        self.height.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self.height.setValue)
        self.height.valueChanged.connect(self._height_set)
        w = QWidget()
        f = QFormLayout(w)
        self.wear_mask = QCheckBox("Mask worn on her head")
        self.wear_sword = QCheckBox("Sword slung at her hip")
        for c in (self.wear_mask, self.wear_sword):
            c.toggled.connect(self._wear_set)
        f.addRow("Outfit", self.outfit_combo)
        f.addRow("Height (feet to head)", self.height)
        f.addRow("", slider)
        f.addRow("Drawn outfits", self.wear_sword)
        if sprites.MASK_ENABLED:
            f.addRow("", self.wear_mask)
        f.addRow(QLabel("The outfit she starts in is the one saved here."))
        return w

    def _outfit_picked(self, name: str) -> None:
        if not self._filling and name and name != self.outfit:
            self._load_outfit(name)

    def _wear_set(self, *_):
        if not self._filling:
            tw = self.ch.tweaks(self.outfit)
            tw.mask, tw.sword = self.wear_mask.isChecked(), self.wear_sword.isChecked()
            if self.preview.model is not None:
                self.preview.model.tune(self.ch, self.outfit)

    def _height_set(self, v: int) -> None:
        if not self._filling:
            self.ch.tweaks(self.outfit).height_dip = int(v)

    # --- Behaviour -------------------------------------------------------------------------------
    def _behaviour_tab(self) -> QWidget:
        def spin(lo, hi, step, suffix, decimals=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setSuffix(suffix)
            s.valueChanged.connect(self._behaviour_set)
            return s

        self.b_look = QComboBox()
        self.b_look.addItem("Where you click (for a few seconds)", "clicks")
        self.b_look.addItem("The mouse pointer, always", "cursor")
        self.b_look.addItem("Straight ahead", "off")
        self.b_look.currentIndexChanged.connect(self._behaviour_set)
        self.b_hold = spin(0.5, 30, 0.5, " s")
        self.b_reach = spin(0.1, 2.0, 0.05, "", 2)
        self.b_blink = (spin(0.5, 30, 0.5, " s"), spin(0.5, 30, 0.5, " s"))
        self.b_moment = (spin(2, 600, 1, " s"), spin(2, 600, 1, " s"))
        self.b_sleep = spin(10, 3600, 10, " s", 0)
        self.b_effects = QCheckBox("Effects (zzz, sparkles, notes, \"!\")")
        self.b_effects.toggled.connect(self._behaviour_set)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("She looks at", self.b_look)
        f.addRow("Keeps looking at a click for", self.b_hold)
        f.addRow("Eye reach (smaller: eyes turn sooner)", self.b_reach)
        f.addRow("Blink every (min)", self.b_blink[0])
        f.addRow("Blink every (max)", self.b_blink[1])
        f.addRow("Idle moment every (min)", self.b_moment[0])
        f.addRow("Idle moment every (max)", self.b_moment[1])
        f.addRow("Fall asleep after no touches for", self.b_sleep)
        f.addRow(self.b_effects)
        return w

    def _fill_behaviour(self) -> None:
        self._filling = True
        b = self.ch.behaviour
        self.b_look.setCurrentIndex(max(0, self.b_look.findData(b.look_at if b.gaze else "off")))
        self.b_hold.setValue(b.look_hold_s)
        self.b_reach.setValue(b.gaze_reach)
        self.b_blink[0].setValue(b.blink_min_s)
        self.b_blink[1].setValue(b.blink_max_s)
        self.b_moment[0].setValue(b.moment_min_s)
        self.b_moment[1].setValue(b.moment_max_s)
        self.b_sleep.setValue(b.sleep_after_s)
        self.b_effects.setChecked(b.effects)
        self._filling = False

    def _behaviour_set(self, *_):
        if self._filling:
            return
        b = self.ch.behaviour
        b.look_at, b.look_hold_s = self.b_look.currentData(), self.b_hold.value()
        b.gaze = b.look_at != "off"
        b.gaze_reach, b.effects = self.b_reach.value(), self.b_effects.isChecked()
        b.blink_min_s, b.blink_max_s = self.b_blink[0].value(), max(self.b_blink[0].value(), self.b_blink[1].value())
        b.moment_min_s, b.moment_max_s = self.b_moment[0].value(), max(self.b_moment[0].value(),
                                                                       self.b_moment[1].value())
        b.sleep_after_s = self.b_sleep.value()
        if self.preview.model is not None:
            self.preview.model.tune(self.ch, self.outfit)

    # --- Sequences -------------------------------------------------------------------------------
    def _sequences_tab(self) -> QWidget:
        self.seq_list = QListWidget()
        self.seq_list.currentTextChanged.connect(self._seq_picked)
        self.frames = QTableWidget(0, 2)
        self.frames.setHorizontalHeaderLabels(["Image", "Seconds"])
        self.frames.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.frames.verticalHeader().setVisible(False)
        self.seq_loop = QCheckBox("Loop")
        self.seq_loop.toggled.connect(self._seq_store)
        self.seq_effect = QComboBox()
        self.seq_effect.currentTextChanged.connect(self._seq_store)
        self.seq_prop = QComboBox()
        self.seq_seat = QComboBox()
        held = [("(nothing)", ""), ("Orb", sprites.ORB), ("Sword", sprites.SWORD)]
        if sprites.MASK_ENABLED:
            held.insert(2, ("Mask", sprites.MASK))
        for c, items in ((self.seq_prop, tuple(held)),
                         (self.seq_seat, (("(stands)", ""), ("Slime", sprites.SLIME)))):
            for text, data in items:
                c.addItem(text, data)
            c.currentIndexChanged.connect(self._seq_store)
        btns = QHBoxLayout()
        for text, fn in (("Add frame", self._frame_add), ("Remove", self._frame_remove), ("Up", lambda: self._frame_move(-1)),
                         ("Down", lambda: self._frame_move(1)), ("Reset", self._seq_reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        self.seq_note = QLabel("")
        right = QVBoxLayout()
        right.addWidget(self.frames, 1)
        right.addLayout(btns)
        opts = QHBoxLayout()
        opts.addWidget(self.seq_loop)
        opts.addWidget(QLabel("Effect"))
        opts.addWidget(self.seq_effect, 1)
        right.addLayout(opts)
        opts2 = QHBoxLayout()
        opts2.addWidget(QLabel("Holds"))
        opts2.addWidget(self.seq_prop, 1)
        opts2.addWidget(QLabel("Sits on"))
        opts2.addWidget(self.seq_seat, 1)
        right.addLayout(opts2)
        right.addWidget(QLabel("No frames: the mood's face shows (for Idle, Talk, Happy...)."))
        w = QWidget()
        lay = QHBoxLayout(w)
        col = QVBoxLayout()
        col.addWidget(self.seq_list, 1)
        col.addWidget(self.seq_note)
        lay.addLayout(col, 1)
        lay.addLayout(right, 3)
        self._images: list[str] = []
        return w

    def _fill_sequences(self) -> None:
        self._filling = True
        m = self.preview.model
        self.seq_list.clear()
        self.frames.setRowCount(0)
        enabled = m is not None
        for wdg in (self.seq_list, self.frames, self.seq_loop, self.seq_effect, self.seq_prop, self.seq_seat):
            wdg.setEnabled(enabled)
        self.seq_note.setText("" if enabled else "Sequences are for drawn (sprite) outfits.")
        if m is not None:
            self._images = [k for d in ("poses", "walk-cycle/frames", "expressions", "states") for k in m.pack.keys(d)]
            self.seq_effect.clear()
            self.seq_effect.addItems(["(none)", *m.pack.effects()])
            self.seq_list.addItems(sorted(m.sequences))
        self._filling = False
        if m is not None and self.seq_list.count():
            self.seq_list.setCurrentRow(0)

    def _seq_dict(self, name: str) -> dict:
        if name in self.ch.sequences:
            return copy.deepcopy(self.ch.sequences[name])
        return self._seq_dict_builtin(name)

    def _seq_dict_builtin(self, name: str) -> dict:
        m = self.preview.model
        s = (m.pack.sequences if m is not None else sprites.SEQUENCES).get(name, sprites.Seq())
        return {"frames": [[k, sec] for k, sec in s.frames], "loop": s.loop, "effect": s.effect or "",
                "prop": s.prop or "", "seat": s.seat or ""}

    def _seq_picked(self, name: str) -> None:
        if not name:
            return
        d = self._seq_dict(name)
        self._filling = True
        self.frames.setRowCount(0)
        for key, sec in d["frames"]:
            self._frame_row(key, sec)
        self.seq_loop.setChecked(bool(d["loop"]))
        self.seq_effect.setCurrentText(d.get("effect") or "(none)")
        base = self._seq_dict_builtin(name)
        self.seq_prop.setCurrentIndex(max(0, self.seq_prop.findData(d.get("prop", base["prop"]))))
        self.seq_seat.setCurrentIndex(max(0, self.seq_seat.findData(d.get("seat", base["seat"]))))
        self._filling = False
        self.preview.play(name, "neutral")

    def _frame_row(self, key: str, sec: float, at: int | None = None) -> None:
        r = self.frames.rowCount() if at is None else at
        self.frames.insertRow(r)
        img = QComboBox()
        img.addItems(self._images if key in self._images else [key, *self._images])
        img.setCurrentText(key)
        img.currentTextChanged.connect(self._seq_store)
        s = QDoubleSpinBox()
        s.setRange(0.03, 10.0)
        s.setSingleStep(0.05)
        s.setDecimals(2)
        s.setValue(sec)
        s.valueChanged.connect(self._seq_store)
        self.frames.setCellWidget(r, 0, img)
        self.frames.setCellWidget(r, 1, s)

    def _frames(self) -> list[list]:
        return [[self.frames.cellWidget(r, 0).currentText(), round(self.frames.cellWidget(r, 1).value(), 3)]
                for r in range(self.frames.rowCount())]

    def _seq_store(self, *_):
        name = self.seq_list.currentItem().text() if self.seq_list.currentItem() else ""
        if self._filling or not name:
            return
        eff = self.seq_effect.currentText()
        self.ch.sequences[name] = {"frames": self._frames(), "loop": self.seq_loop.isChecked(),
                                   "effect": "" if eff == "(none)" else eff,
                                   "prop": self.seq_prop.currentData() or "", "seat": self.seq_seat.currentData() or ""}
        if self.preview.model is not None:
            self.preview.model.tune(self.ch, self.outfit)
            self.preview.play(name, "neutral")

    def _frame_add(self) -> None:
        if self._images:
            r = self.frames.currentRow()
            self._frame_row(self._images[0], 0.3, r + 1 if r >= 0 else None)
            self._seq_store()

    def _frame_remove(self) -> None:
        r = self.frames.currentRow()
        if r >= 0:
            self.frames.removeRow(r)
            self._seq_store()

    def _frame_move(self, d: int) -> None:
        r = self.frames.currentRow()
        rows = self._frames()
        if 0 <= r < len(rows) and 0 <= r + d < len(rows):
            rows[r], rows[r + d] = rows[r + d], rows[r]
            self._filling = True
            self.frames.setRowCount(0)
            for k, sec in rows:
                self._frame_row(k, sec)
            self._filling = False
            self.frames.setCurrentCell(r + d, 0)
            self._seq_store()

    def _seq_reset(self) -> None:
        item = self.seq_list.currentItem()
        if item is not None:
            self.ch.sequences.pop(item.text(), None)
            if self.preview.model is not None:
                self.preview.model.tune(self.ch, self.outfit)
            self._seq_picked(item.text())

    # --- Voice -----------------------------------------------------------------------------------
    def _voice_tab(self) -> QWidget:
        self.v_engine = QComboBox()
        self.v_engine.addItem("Her voice (F5 clone of the reference clip)", "f5")
        self.v_engine.addItem("Kokoro preset voices (CPU, fast)", "kokoro")
        self.v_engine.currentIndexChanged.connect(self._engine_picked)
        self.v_voice = QComboBox()
        self.v_voice.currentIndexChanged.connect(self._voice_set)
        self.v_speed = QDoubleSpinBox()
        self.v_speed.setRange(0.5, 1.6)
        self.v_speed.setSingleStep(0.05)
        self.v_speed.setDecimals(2)
        self.v_speed.valueChanged.connect(self._voice_set)
        self.v_nfe = QSpinBox()
        self.v_nfe.setRange(4, 32)
        self.v_nfe.valueChanged.connect(self._voice_set)
        self.v_text = QLineEdit(TEST_LINE)
        say = QPushButton("Say it")
        say.clicked.connect(self._say)
        default = QPushButton("Use config.toml's voice")
        default.clicked.connect(self._voice_default)
        row = QHBoxLayout()
        row.addWidget(self.v_text, 1)
        row.addWidget(say)
        self.v_note = QLabel("")
        self.v_note.setWordWrap(True)
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Engine", self.v_engine)
        f.addRow("Voice", self.v_voice)
        f.addRow("Speed", self.v_speed)
        f.addRow("Quality steps (F5 only)", self.v_nfe)
        f.addRow("Test line", row)
        f.addRow(default)
        f.addRow(self.v_note)
        return w

    def _f5_refs(self) -> list[Path]:
        ref = self.vcfg.get("reference")
        return sorted(Path(ref).parent.glob("*.wav")) if ref else []

    def _kokoro_voices(self) -> list[str]:
        d = self.vcfg.get("kokoro_dir")
        try:
            with np.load(Path(d) / "voices-v1.0.bin") as z:
                names = list(z.files)
        except (OSError, ValueError, TypeError):
            return []
        english = [n for n in names if n[:2] in KOKORO_GROUPS]
        return sorted(english, key=lambda n: (list(KOKORO_GROUPS).index(n[:2]), n)) + sorted(set(names) - set(english))

    def _fill_voice_list(self, engine: str, voice: str) -> None:
        self.v_voice.clear()
        if engine == "kokoro":
            names = self._kokoro_voices()
            for n in names:
                self.v_voice.addItem(f"{n}  ({KOKORO_GROUPS.get(n[:2], 'other language')})", n)
            self.v_note.setText("" if names else "Kokoro's files aren't in config [voice] kokoro_dir.")
        else:
            self.v_voice.addItem("config.toml's reference (default)", "")
            for p in self._f5_refs():
                self.v_voice.addItem(p.name, str(p))
            self.v_note.setText("F5 clones whichever clip you pick (a .txt transcript must sit beside it). "
                                "Switching loads the model again (~15 s on the GPU).")
        i = self.v_voice.findData(voice)
        self.v_voice.setCurrentIndex(i if i >= 0 else 0)
        self.v_nfe.setEnabled(engine == "f5")

    def _fill_voice(self) -> None:
        self._filling = True
        v = self.ch.voice or character.VoiceSettings(speed=float(self.vcfg.get("speed", 0.9)),
                                                     nfe=int(self.vcfg.get("nfe", 8)))
        self.v_engine.setCurrentIndex(max(0, self.v_engine.findData(v.engine)))
        self._fill_voice_list(v.engine, v.voice)
        self.v_speed.setValue(v.speed)
        self.v_nfe.setValue(v.nfe)
        self._filling = False

    def _engine_picked(self, _i: int) -> None:
        if self._filling:
            return
        engine = self.v_engine.currentData()
        self._filling = True
        self._fill_voice_list(engine, "bf_emma" if engine == "kokoro" else "")
        if engine == "kokoro" and self.v_speed.value() < 0.95:
            self.v_speed.setValue(1.0)  # F5's 0.90 drags in Kokoro
        self._filling = False
        self._voice_set()

    def _voice_set(self, *_):
        if self._filling:
            return
        self.ch.voice = character.VoiceSettings(self.v_engine.currentData(), self.v_voice.currentData() or "",
                                                round(self.v_speed.value(), 2), self.v_nfe.value())

    def _voice_default(self) -> None:
        self.ch.voice = None
        self._fill_voice()
        self.status.setText("Voice: back to config.toml's on Apply.")

    def _send_voice(self) -> None:
        v = self.ch.voice
        if v is not None:
            self.send(voice_msg(v))
            self._voice_sent = True
        elif self._voice_sent:  # back to the config's voice
            self.send(voice_msg(character.VoiceSettings(speed=float(self.vcfg.get("speed", 0.9)),
                                                        nfe=int(self.vcfg.get("nfe", 8)))))
            self._voice_sent = False

    def _say(self) -> None:
        self._send_voice()
        self.send(Command(name="voice_test", arg=self.v_text.text()))
        self.status.setText("Speaking… (a new voice loads first)")

    # --- buttons ---------------------------------------------------------------------------------
    def apply(self) -> None:
        ch = copy.deepcopy(self.ch)
        ch.outfit = self.outfit
        self.stage.apply_character(ch)
        if self.outfit != self.stage.outfit:
            self.stage.request_outfit(self.outfit)
        self._send_voice()
        self.status.setText("Applied.")

    def save_now(self) -> None:
        self.apply()
        path = paths.DATA / character.FILE_NAME
        try:
            character.save(self.stage.character, path)
            self.status.setText(f"Saved to {path}")
        except OSError as e:
            self.status.setText(f"Couldn't save: {e}")

    def reset(self) -> None:
        self.ch = character.Character()
        self._load_outfit(self.outfit)
        self._fill_behaviour()
        self._fill_voice()
        self.status.setText("Defaults restored here; Apply or Save to use them.")
