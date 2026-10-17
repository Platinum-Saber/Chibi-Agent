"""Frame-rate check: the VRM viewer in a transparent, frameless, always-on-top QWebEngineView,
the way an overlay would host three-vrm.

    overlay\\.venv\\Scripts\\python spikes\\vrm\\fps_qt.py --model export/raphael_chibi.vrm
        [--screen N] [--size 420x600|full] [--gpu default|low|high] [--duration 40] [--tag NAME]

Needs the viewer server (node spikes/vrm/serve.mjs). Every 10 s it prints fps p50, frame
time p50/p95/max (from requestAnimationFrame deltas inside the page) and CPU of this
process plus its QtWebEngineProcess children. `--gpu low/high` passes Chromium's
--force_low_power_gpu / --force_high_performance_gpu. Rows go to spikes/vrm/out/fps.csv.
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="export/raphael_serious.vrm")
ap.add_argument("--screen", type=int, default=0)
ap.add_argument("--size", default="420x600")
ap.add_argument("--gpu", choices=["default", "low", "high"], default="default")
ap.add_argument("--duration", type=float, default=40)
ap.add_argument("--cam", default="full")
ap.add_argument("--tag", default="")
args = ap.parse_args()

flags = {"low": "--force_low_power_gpu", "high": "--force_high_performance_gpu"}.get(args.gpu, "")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " " + flags).strip()

import psutil  # noqa: E402
from PySide6.QtCore import QTimer, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, msg, line, src):  # noqa: N802 (Qt name)
        print(f"js: {msg} ({src}:{line})", flush=True)


app = QApplication(sys.argv)
screen = app.screens()[args.screen]
geo = screen.geometry()
view = QWebEngineView()
view.setPage(Page(view))
view.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
view.setAttribute(Qt.WA_TranslucentBackground)
view.page().setBackgroundColor(QColor(0, 0, 0, 0))
if args.size == "full":
    view.setGeometry(geo)
else:
    w, h = map(int, args.size.split("x"))
    view.setGeometry(geo.right() - w - 40, geo.bottom() - h - 60, w, h)
view.load(QUrl(f"http://127.0.0.1:5179/?model={args.model}&bg=transparent&cam={args.cam}"))
view.show()

me = psutil.Process()
me.cpu_percent()
children = {}
rows = []
t0 = time.time()
gpu = ["?"]
out = Path(__file__).parent / "out"
out.mkdir(exist_ok=True)


def cpu():
    total = me.cpu_percent()
    for c in me.children(recursive=True):
        if c.pid not in children:
            children[c.pid] = c
            c.cpu_percent()
            continue
        try:
            total += children[c.pid].cpu_percent()
        except psutil.NoSuchProcess:
            pass
    return total


def report(dts):
    if not isinstance(dts, list) or len(dts) < 10:
        print(f"waiting for frames... got {type(dts).__name__} {len(dts) if isinstance(dts, list) else dts!r}", flush=True)
        return
    dts = sorted(dts[5:])  # drop the first frames after a drain
    p50 = statistics.median(dts)
    p95 = dts[int(len(dts) * 0.95)]
    c = cpu()
    row = dict(tag=args.tag, model=args.model, screen=args.screen, size=args.size, gpu_flag=args.gpu,
               gpu=gpu[0], t=round(time.time() - t0), frames=len(dts), fps_p50=round(1000 / p50, 2),
               ms_p50=round(p50, 2), ms_p95=round(p95, 2), ms_max=round(dts[-1], 1),
               cpu_core_pct=round(c, 1), cpu_machine_pct=round(c / psutil.cpu_count(), 2))
    rows.append(row)
    print(row, flush=True)


def tick():
    view.page().runJavaScript("window.spike ? window.spike.gpu : '?'", 0, lambda g: gpu.__setitem__(0, g or "?"))
    view.page().runJavaScript("JSON.stringify(window.spike ? window.spike.dts.splice(0) : null)", 0, lambda s: report(json.loads(s) if s else s))
    if time.time() - t0 > args.duration:
        f = out / "fps.csv"
        new = not f.exists()
        with f.open("a", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["tag"])
            if new:
                wr.writeheader()
            wr.writerows(rows)
        app.quit()


QTimer.singleShot(4000, lambda: view.page().runJavaScript("window.spike && window.spike.dts.splice(0)"))
timer = QTimer()
timer.timeout.connect(tick)
QTimer.singleShot(4000, lambda: timer.start(10000))
app.exec()
