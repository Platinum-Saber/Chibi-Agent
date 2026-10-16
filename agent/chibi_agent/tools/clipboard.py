"""Read and write the clipboard (text only)."""
from __future__ import annotations

from . import Result, tool


def _cb():
    import win32clipboard
    return win32clipboard


@tool("get_clipboard", "Read the text on the clipboard.")
def get_clipboard() -> Result:
    cb = _cb()
    cb.OpenClipboard()
    try:
        text = cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.IsClipboardFormatAvailable(cb.CF_UNICODETEXT) else ""
    finally:
        cb.CloseClipboard()
    return Result(text or "The clipboard has no text.", untrusted=True)


@tool("set_clipboard", "Put text on the clipboard.", {"text": ("The text", True)},
      side_effect=True, summary=lambda a: "Copy text to the clipboard")
def set_clipboard(text: str) -> Result:
    cb = _cb()
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardText(text, cb.CF_UNICODETEXT)
    finally:
        cb.CloseClipboard()
    return Result("Copied to the clipboard.")
