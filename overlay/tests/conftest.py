"""Qt's offscreen platform (the tests' QT_QPA_PLATFORM) finds no fonts on Windows unless it's
told where they are: every family then resolves to "Sans Serif" and the font picker can't be
tested. Point it at the system fonts before any test starts a QApplication."""
import os
from pathlib import Path

_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
if _fonts.is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", str(_fonts))
