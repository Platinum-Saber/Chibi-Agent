"""Overlay entry point: Qt app, one Live2D window per monitor, the stage, the agent link."""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

import live2d
from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from chibi_shared import config, paths

from .body import motion
from .link import QtLink
from .stage import Stage
from .window import MonitorWindow

PKG = Path(__file__).resolve().parents[1]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="chibi_overlay")
    ap.add_argument("--debug-throw", metavar="VX,VY", help="throw her at VX,VY px/s 4 s after start")
    args = ap.parse_args()
    paths.ensure()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load()["overlay"]

    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(1)  # vsync: 60 fps on this laptop's screens
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    # One GL share group for all monitor windows: each live2d model's textures stay valid
    # whichever window's context draws (without it, monitor 2 drew white quads).
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    live2d.init()
    app = QApplication(sys.argv)
    rigs = {"chibi": motion.load(PKG / cfg["chibi_map"]), "serious": motion.load(PKG / cfg["serious_map"])}
    models = {"chibi": cfg["chibi_rig"], "serious": cfg["serious_rig"]}
    primary = QGuiApplication.primaryScreen()

    link = QtLink()
    stage = Stage(rigs, primary.devicePixelRatio(), link, own_windows=set())
    windows: list[MonitorWindow] = []
    # One window that follows her between monitors (see MonitorWindow._follow).
    windows.append(MonitorWindow(primary, stage, models, True, windows))
    link.received.connect(stage.on_message)
    stage._quit_cb = app.quit
    link.start()
    for w in windows:
        w.show()

    if args.debug_throw:
        vx, vy = (float(v) for v in args.debug_throw.split(","))
        QTimer.singleShot(4000, lambda: stage.physics.throw_at(vx, vy))

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)  # lets Python see Ctrl+C
    tick.start(200)
    app.exec()
    stage.media.stop()
    link.stop()
    live2d.dispose()
