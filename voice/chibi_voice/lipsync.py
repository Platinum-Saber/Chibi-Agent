"""Mouth openness from the playback buffer: RMS per 1/60 s block, normalised to 0..1."""
from __future__ import annotations

import numpy as np

FPS = 60
# Divide by the loudest block, but never by less than this (about -34 dBFS), so a
# near-silent buffer stays near zero instead of being blown up to a wide-open mouth.
FLOOR = 0.02


def block_size(sr: int, fps: int = FPS) -> int:
    return max(1, round(sr / fps))


def levels(audio: np.ndarray, sr: int, fps: int = FPS) -> np.ndarray:
    """One value in [0, 1] per 1/fps s block of `audio` (mono float)."""
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if a.size == 0:
        return np.zeros(0, dtype=np.float32)
    n = block_size(sr, fps)
    blocks = np.pad(a, (0, (-a.size) % n)).reshape(-1, n)
    rms = np.sqrt(np.mean(np.square(blocks, dtype=np.float64), axis=1))
    return np.clip(rms / max(float(rms.max()), FLOOR), 0.0, 1.0).astype(np.float32)
