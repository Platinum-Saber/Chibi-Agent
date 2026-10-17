"""Tray icon and menu: show/hide, mute, gaming mode, memory, settings, Google accounts,
autostart, quit.

Show/hide is handled here (it's only about the window); everything else is a
`Command` to the agent, which owns the state and echoes it back as `State` so
the check marks always match what is really happening.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QSystemTrayIcon, QVBoxLayout)

from chibi_shared.protocol import Command, MemoryItems, State


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
        self.icon = QSystemTrayIcon(_icon())
        self.icon.setToolTip("Raphael")
        m = QMenu()
        self.a_show = self._action(m, "Hide Raphael", self._toggle_visible)
        m.addSeparator()
        self.a_mute = self._action(m, "Mute voice", lambda on: self._cmd("mute" if on else "unmute"), True)
        self.a_gaming = self._action(m, "Gaming mode (free GPU memory)",
                                     lambda on: self._cmd("gaming_on" if on else "gaming_off"), True)
        m.addSeparator()
        self._action(m, "Memory…", lambda: self._cmd("memory_list"))
        self._action(m, "Settings (config.toml)…", lambda: self._cmd("open_settings"))
        self.google_menu = m.addMenu("Google accounts")
        self._google_items([])
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
        elif isinstance(msg, MemoryItems):
            self.memory.show_items(msg.items)
