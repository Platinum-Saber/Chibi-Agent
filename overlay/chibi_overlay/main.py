"""Overlay entry point: Qt app, one Live2D window per monitor, the stage, the agent link."""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

import live2d
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from chibi_shared import config, paths

from .body import motion
from .link import QtLink
from .stage import Stage
from .window import MonitorWindow

PKG = Path(__file__).resolve().parents[1]


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
    rigs = {"chibi": motion.load(PKG / cfg["chibi_map"]), "serious": motion.load(PKG / cfg["serious_map"])}
    models = {"chibi": cfg["chibi_rig"], "serious": cfg["serious_rig"]}
    primary = QGuiApplication.primaryScreen()

    link = QtLink()
    stage = Stage(rigs, primary.devicePixelRatio(), link, own_windows=set())
    windows: list[MonitorWindow] = []
    for scr in QGuiApplication.screens():
        windows.append(MonitorWindow(scr, stage, models, scr is primary, windows))
    link.received.connect(stage.on_message)
    stage._quit_cb = app.quit
    link.start()
    for w in windows:
        w.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)  # lets Python see Ctrl+C
    tick.start(200)
    app.exec()
    stage.media.stop()
    link.stop()
    live2d.dispose()
