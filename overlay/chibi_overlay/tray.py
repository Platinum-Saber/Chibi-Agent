"""Tray icon and menu: show/hide, mute, gaming mode, body (2D art / 3D model), outfit, customize,
memory, settings, Google accounts, notification access, autostart, quit.

Show/hide, the body, the outfit and Customize Raphael (customize.py: moods, size, behaviour, sequences,
voice) are handled here (they're about her look); everything else is a
`Command` to the agent, which owns the state and echoes it back as `State` so
the check marks always match what is really happening.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QSystemTrayIcon, QVBoxLayout)

from chibi_shared import paths
from chibi_shared.protocol import Command, MemoryItems, State

from . import character

log = logging.getLogger(__name__)


def _icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(16, 22, 34))
    p.setPen(QColor(216, 180, 90))
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor(127, 227, 255))
    p.setFont(QFont("Segoe UI Semibold", 30))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    p.end()
    return QIcon(pm)


class MemoryDialog(QDialog):
    def __init__(self, send):
        super().__init__()
        self.send = send
        self.setWindowTitle("Raphael's memory")
        self.resize(520, 420)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        forget = QPushButton("Forget selected")
        forget.clicked.connect(self._forget)
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        buttons = QHBoxLayout()
        buttons.addWidget(forget)
        buttons.addStretch()
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("What she remembers about you. Select facts to forget them."))
        lay.addWidget(self.list)
        lay.addLayout(buttons)

    def show_items(self, items: list[tuple[int, str]]) -> None:
        self.list.clear()
        for fid, text in items:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, fid)
            self.list.addItem(it)
        if not items:
            self.list.addItem("(nothing yet)")
        self.show()
        self.raise_()

    def _forget(self) -> None:
        ids = [str(i.data(Qt.ItemDataRole.UserRole)) for i in self.list.selectedItems()
               if i.data(Qt.ItemDataRole.UserRole) is not None]
        if ids:
            self.send(Command(name="memory_delete", arg=",".join(ids)))


class Tray:
    def __init__(self, link, stage, on_visible):
        self.link, self.stage, self.on_visible = link, stage, on_visible
        self.user_hidden = False
        self.memory = MemoryDialog(link.send)
        self.customize = None  # CustomizeDialog, built on first use
        self.icon = QSystemTrayIcon(_icon())
        self.icon.setToolTip("Raphael")
        m = QMenu()
        self.a_show = self._action(m, "Hide Raphael", self._toggle_visible)
        m.addSeparator()
        self.a_mute = self._action(m, "Mute voice", lambda on: self._cmd("mute" if on else "unmute"), True)
        self.a_gaming = self._action(m, "Gaming mode (free GPU memory)",
                                     lambda on: self._cmd("gaming_on" if on else "gaming_off"), True)
        self.a_body = self._action(m, "", self.switch_body)  # her 2D art <-> her 3D model
        m.aboutToShow.connect(self._body_label)
        self._body_label()
        self.outfit_menu = m.addMenu("Outfit")
        self.outfit_menu.aboutToShow.connect(self._outfit_items)
        m.addSeparator()
        self._action(m, "Customize Raphael…", self._customize)
        self._action(m, "Memory…", lambda: self._cmd("memory_list"))
        self._action(m, "Settings (config.toml)…", lambda: self._cmd("open_settings"))
        self.google_menu = m.addMenu("Google accounts")
        self._google_items([])
        self.a_notif = self._action(m, "Allow notification access…", lambda: self._cmd("notif_access"))
        self.a_auto = self._action(m, "Start with Windows",
                                   lambda on: self._cmd("autostart_on" if on else "autostart_off"), True)
        m.addSeparator()
        self._action(m, "Quit Raphael", lambda: self._cmd("quit"))
        self.menu = m
        self.icon.setContextMenu(m)
        self.icon.activated.connect(self._clicked)
        self.icon.show()

    def _action(self, menu: QMenu, text: str, fn, checkable: bool = False) -> QAction:
        a = QAction(text, menu)
        a.setCheckable(checkable)
        (a.toggled if checkable else a.triggered).connect(fn)
        menu.addAction(a)
        return a

    def _google_items(self, accounts: list[str]) -> None:
        g = self.google_menu
        g.clear()
        for email in accounts:
            self._action(g, f"Sign out {email}", lambda _=False, e=email: self._cmd("google_signout", e))
        if accounts:
            g.addSeparator()
        self._action(g, "Add Google account…", lambda: self._cmd("google_signin"))
        if len(accounts) > 1:
            self._action(g, "Sign out of all", lambda: self._cmd("google_signout"))

    def _outfit_items(self) -> None:
        """Changing clothes is local (Kryo clicked it); the stage tells the agent."""
        o = self.outfit_menu
        o.clear()
        for name in self.stage.wardrobe.names:
            a = self._action(o, name.capitalize(), lambda _=False, n=name: self.stage.request_outfit(n), True)
            a.blockSignals(True)
            a.setChecked(name == self.stage.outfit)
            a.blockSignals(False)

    def _body_label(self) -> None:
        self.a_body.setText("Switch to 2D art" if self.stage.body == "3d" else "Switch to 3D model")
        self.a_body.setEnabled(self.stage.other_body_outfit() is not None)

    def switch_body(self) -> None:
        """One body at a time; she starts in the last one chosen (saved with Customize)."""
        if self.stage.switch_body():
            try:
                character.save(self.stage.character, paths.DATA / character.FILE_NAME)
            except OSError as e:
                log.warning("can't save the body choice: %s", e)

    def _customize(self) -> None:
        if self.customize is None:
            from .customize import CustomizeDialog  # numpy/svg imports only when first opened
            self.customize = CustomizeDialog(self.stage, self.link.send)
        self.customize.show_current()

    def _cmd(self, name: str, arg: str = "") -> None:
        self.link.send(Command(name=name, arg=arg))

    def _toggle_visible(self) -> None:
        self.user_hidden = not self.user_hidden
        self.a_show.setText("Show Raphael" if self.user_hidden else "Hide Raphael")
        self.on_visible()

    def _clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # left click: show/hide
            self._toggle_visible()

    def on_message(self, msg) -> None:
        if isinstance(msg, State):
            for a, on in ((self.a_mute, msg.muted), (self.a_gaming, msg.gaming), (self.a_auto, msg.autostart)):
                a.blockSignals(True)
                a.setChecked(on)
                a.blockSignals(False)
            self._google_items(msg.google_accounts)
            allowed = msg.notif_access == "allowed"
            self.a_notif.setText("Notifications: allowed" if allowed else "Allow notification access…")
            self.a_notif.setEnabled(not allowed)
        elif isinstance(msg, MemoryItems):
            self.memory.show_items(msg.items)
