"""Count flicker frames in a capture: frames whose 'her' region suddenly differs
from both neighbours (a blink-out or garbage frame), as opposed to animation.

Usage: uv run flicker_check.py out/capture_x.mp4 [x y w h]   (crop in capture px)
"""
import subprocess
import sys

import numpy as np

path = sys.argv[1]
x, y, w, h = (int(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else (220, 60, 200, 400)
raw = subprocess.run(
    ["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"crop={w}:{h}:{x}:{y},format=gray",
     "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
f = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.int16)
n = len(f)
diff = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))  # diff[i] = |f[i+1]-f[i]|
# spike: frame i differs a lot from i-1 and i+1, but i-1 ~ i+1
skip = np.abs(f[2:] - f[:-2]).mean(axis=(1, 2))
spikes = [i + 1 for i in range(n - 2)
          if min(diff[i], diff[i + 1]) > 4 * (skip[i] + 0.5) and min(diff[i], diff[i + 1]) > 3]
dup = int((diff < 0.05).sum())
print(f"{path}: frames={n} mean_diff={diff.mean():.2f} p99_diff={np.percentile(diff, 99):.2f} "
      f"max_diff={diff.max():.2f} identical_consecutive={dup} flicker_spikes={len(spikes)} at {spikes[:20]}")
