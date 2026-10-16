"""Overlay entry point: Qt app, the Live2D window on the primary monitor, agent link."""
from __future__ import annotations

import logging
import signal
import sys

import live2d
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from chibi_shared import config, paths

from .link import QtLink
from .window import Overlay


def main() -> None:
    paths.ensure()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load()["overlay"]

    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(1)  # vsync: 60 fps on this laptop's screens
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    live2d.init()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    link = QtLink()
    win = Overlay(QGuiApplication.primaryScreen(), cfg["chibi_rig"], cfg.get("height_dip", 360), link)
    link.received.connect(win.on_message)
    link.start()
    win.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)  # lets Python see Ctrl+C
    tick.start(200)
    app.exec()
    link.stop()
    live2d.dispose()
