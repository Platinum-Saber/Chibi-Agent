import asyncio
from types import SimpleNamespace

from chibi_agent.control import Controller
from chibi_shared.protocol import OutfitState


def _controller():
    hub = SimpleNamespace(on_message=lambda h: None, on_connect=lambda cb: None)
    return Controller(hub, orch=None, vram=SimpleNamespace(), memory=None, quit_cb=lambda: None)


def test_remembers_what_she_wears():
    c = _controller()
    asyncio.run(c.on_message("overlay", OutfitState(outfit="coat", outfits=["robe", "coat"])))
    assert c.outfit == "coat" and c.outfits == ["robe", "coat"]


def test_a_refusal_still_reports_the_current_outfit():
    c = _controller()
    asyncio.run(c.on_message("overlay", OutfitState(outfit="robe", outfits=["robe"], ok=False, error="no outfit 'cape'")))
    assert c.outfit == "robe"
