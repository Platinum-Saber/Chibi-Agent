"""One screenshot of the monitor the user is working on, for the multimodal model.

Never written to disk: the PNG goes straight into the next model turn and is
dropped afterwards. Downscaled to 1280 px so it fits the fixed 8k context
(spike 3: switching num_ctx per request reloads the model)."""
from __future__ import annotations

import base64
import ctypes
import io

from . import Result, tool

user32 = ctypes.windll.user32


def capture_b64(max_side: int = 1280) -> str:
    import mss
    from PIL import Image

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    with mss.MSS() as s:
        mons = s.monitors[1:]
        mon = next((m for m in mons if m["left"] <= pt.x < m["left"] + m["width"]
                    and m["top"] <= pt.y < m["top"] + m["height"]), mons[0])
        g = s.grab(mon)
    img = Image.frombytes("RGB", g.size, g.rgb)
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


@tool("look_at_screen", "Look at Kryo's screen to answer a question about it.",
      {"question": ("What to look for", True)})
def look_at_screen(question: str) -> Result:
    return Result(f"Screenshot attached for: {question}", untrusted=True, image_b64=capture_b64())
