"""Pre-rendered fixed lines ("Answer.", "Understood, Master.", ...) in the clip cache.

A clip is `<slug>-<hash>.wav` in %LOCALAPPDATA%\\ChibiAgent\\clips. The hash covers the
voice (reference audio + transcript + F5 settings) and the text, so changing her
voice re-renders every clip. The agent asks for a clip by its text: `clip="Answer."`.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

LINES = [
    "Answer.", "Notice.", "Understood.", "Confirmed.", "Warning.", "Report.",
    "End of report.", "Understood, Master.", "Good morning, Master.", "Yes, Master.",
]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def voice_id(ref_wav: Path, ref_text: str, speed: float, nfe: int,
             model: str = "F5TTS_v1_Base") -> str:
    h = hashlib.sha256(Path(ref_wav).read_bytes())
    h.update(f"\0{ref_text.strip()}\0{speed:g}\0{nfe}\0{model}".encode())
    return h.hexdigest()


def clip_hash(voice: str, text: str) -> str:
    return hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()[:12]


class ClipCache:
    def __init__(self, root: Path, voice: str, lines: list[str] = LINES):
        self.root = Path(root)
        self.voice = voice
        self._by_slug = {slug(t): t for t in lines}

    def path(self, text: str) -> Path:
        return self.root / f"{slug(text)}-{clip_hash(self.voice, text)}.wav"

    def lookup(self, text: str) -> Path | None:
        """The rendered clip for a fixed line, matched by slug ("answer" finds "Answer.")."""
        line = self._by_slug.get(slug(text))
        if line is None:
            return None
        p = self.path(line)
        return p if p.exists() else None

    def missing(self) -> list[str]:
        return [t for t in self._by_slug.values() if not self.path(t).exists()]

    def ensure(self, synth: Callable[[str], tuple[np.ndarray, int]]) -> list[str]:
        """Render the missing clips with `synth` and drop stale renders of the same lines."""
        import soundfile as sf

        self.root.mkdir(parents=True, exist_ok=True)
        made = []
        for text in self.missing():
            audio, sr = synth(text)
            p = self.path(text)
            tmp = p.with_suffix(".part")
            sf.write(tmp, audio, sr, format="WAV", subtype="FLOAT")
            tmp.replace(p)
            made.append(text)
            log.info("rendered clip %r -> %s", text, p.name)
        for text in self._by_slug.values():
            keep = self.path(text)
            for old in self.root.glob(f"{slug(text)}-*.wav"):
                if old != keep and old.stem.rsplit("-", 1)[0] == slug(text):
                    old.unlink(missing_ok=True)
        return made
