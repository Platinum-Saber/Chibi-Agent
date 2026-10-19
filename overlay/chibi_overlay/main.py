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

from chibi_shared.protocol import Fullscreen

from . import env, outfits
from .link import QtLink
from .stage import Stage
from .tray import Tray
from .window import MonitorWindow

PKG = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)


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
    wardrobe = outfits.parse(cfg)
    log.info("outfits: %s; wearing %s", ", ".join(wardrobe.names), wardrobe.current)
    primary = QGuiApplication.primaryScreen()

    link = QtLink()
    stage = Stage(wardrobe, PKG, primary.devicePixelRatio(), link, own_windows=set())
    stage.chibi_only = bool(cfg.get("chibi_only", False))
    if stage.chibi_only:
        log.info("chibi_only: the serious form is off")
    link.connected.connect(stage.send_outfit_state)
    windows: list[MonitorWindow] = []
    # One window that follows her between monitors (see MonitorWindow._follow).
    windows.append(MonitorWindow(primary, stage, True, windows))
    app.setQuitOnLastWindowClosed(False)  # the tray keeps her alive while hidden
    win = windows[0]
    fullscreen = {"exe": None}

    def update_visibility() -> None:
        hidden = tray.user_hidden or stage.hidden or fullscreen["exe"] is not None
        if hidden and win.isVisible():
            win.hide()  # no frames at all while hidden: nothing drawn, no GPU work
        elif not hidden and not win.isVisible():
            win.show()
            win.update()

    def watch_fullscreen() -> None:
        exe = env.fullscreen_app(stage.ground.own)
        if exe != fullscreen["exe"]:
            fullscreen["exe"] = exe
            link.send(Fullscreen(active=exe is not None, exe=exe or ""))
        update_visibility()

    tray = Tray(link, stage, update_visibility)
    link.received.connect(stage.on_message)
    link.received.connect(tray.on_message)
    link.received.connect(lambda _m: update_visibility())
    stage._quit_cb = app.quit
    link.start()
    for w in windows:
        w.show()
    fs_timer = QTimer()
    fs_timer.timeout.connect(watch_fullscreen)
    fs_timer.start(500)

    def watch_power() -> None:
        cap = 1 / 30 if env.on_battery() else 0.0
        if cap != win.min_frame_s:
            log.info("on %s: %s fps", "battery" if cap else "AC power", 30 if cap else "vsync")
            win.min_frame_s = cap
    power_timer = QTimer()
    power_timer.timeout.connect(watch_power)
    power_timer.start(10_000)
    watch_power()

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
