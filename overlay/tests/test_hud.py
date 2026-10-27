import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chibi_overlay import hud  # noqa: E402

app = QApplication.instance() or QApplication([])  # widgets too: test_customize builds a window


class Img:
    def __init__(self, w=1000, h=700):
        self.img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        self.img.fill(Qt.GlobalColor.transparent)

    def width(self):
        return self.img.width()

    def height(self):
        return self.img.height()


class Stage:
    def __init__(self):
        self.ov = type("Ov", (), {"rects": {}})()


def panel_rect(x, w=1000):
    target, st = Img(w), Stage()
    painter = hud.Painter(target, (0, 0), 1.0, st)
    p = QPainter(target.img)
    painter._bubble(p, "Answer. I've opened Spotify for you.", x, 300, 60, 320)
    p.end()
    return st.ov.rects["bubble"]


def test_panel_sits_beside_her_level_with_her_face():
    x0, y0, x1, y1 = panel_rect(300)
    assert x0 >= 300 + 60  # right of her body
    assert 300 <= y0 < 300 + 320 / 2  # beside her head, not above it


def test_panel_moves_to_her_left_near_the_screen_edge():
    x0, _, x1, _ = panel_rect(900)
    assert x1 <= 900 - 60


def test_thinking_clears_the_text_instead_of_an_ellipsis_cloud(monkeypatch, tmp_path):
    from chibi_shared.protocol import MoodReq
    from tests.test_stage_outfit import st as st_fixture  # noqa: F401
    import chibi_overlay.stage as stage_mod
    from tests import test_stage_outfit as t
    monkeypatch.setattr(stage_mod, "Ground", t.FakeGround)
    monkeypatch.setattr(stage_mod, "MediaWatcher", t.FakeMedia)
    from chibi_overlay import outfits
    for n in ("haru", "mao"):
        (tmp_path / f"{n}.model3.json").write_text("{}")
    w = outfits.parse({"outfit": "robe", "chibi_map": "rigs/haru.toml", "serious_map": "rigs/mao.toml",
                       "outfits": {"robe": {"chibi_rig": str(tmp_path / "haru.model3.json"),
                                            "serious_rig": str(tmp_path / "mao.model3.json")}}})
    s = stage_mod.Stage(w, t.PKG, 1.0, t.FakeLink(), own_windows=set())
    s.ov.bubble = "earlier reply"
    s.on_message(MoodReq(mood="thinking"))
    assert s.ov.bubble == ""


def test_load_fonts_registers_a_folder_and_ignores_a_missing_one(tmp_path):
    from pathlib import Path
    assert hud.load_fonts(None) == [] and hud.load_fonts(tmp_path / "nope") == []
    real = Path(r"D:/Projects/Chibi-Agent-Project/ChibiAgent/fonts")
    if real.is_dir():  # Kryo's fonts live outside git
        assert "Electroharmonix" in hud.load_fonts(real)
        from PySide6.QtGui import QFontInfo
        assert QFontInfo(hud.panel_font()).family() == "Electroharmonix"


def panels(x, w=1000, confirm=False):
    """Draw her words plus a status-report card (or a confirm) and return both rects."""
    from types import SimpleNamespace as NS
    target, st = Img(w), Stage()
    st.ov.hud = NS(title="Status report", items=["Phone Link: Duolingo", "Poya Day · tomorrow"], progress=None)
    st.ov.confirm = NS(summary="Open the Recycle Bin", detail="") if confirm else None
    painter = hud.Painter(target, (0, 0), 1.0, st)
    p = QPainter(target.img)
    speech = painter._bubble(p, "Report. Two items require your attention. End of report.", x, 300, 60, 320)
    painter._panel(p, st, x, 300, 60, 320, speech)
    p.end()
    return st.ov.rects["bubble"], st.ov.rects["hud"], target


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_the_list_takes_the_side_her_words_leave_free():
    words, card, _ = panels(820, w=1100)  # near the right edge: words on her left
    assert words[2] <= 820 - 60 and card[0] >= 820 + 60 and not overlaps(words, card)
    assert card[2] <= 1100 - 8  # narrowed to the free space, text wrapped


def test_the_list_goes_under_her_words_when_neither_side_is_free():
    words, card, _ = panels(500, w=640)  # her words on her left, no room on her right
    assert not overlaps(words, card) and card[1] >= words[3]


def test_confirm_buttons_are_recorded_inside_the_card():
    target, st = Img(), Stage()
    from types import SimpleNamespace as NS
    st.ov.hud, st.ov.confirm = None, NS(summary="Open the Recycle Bin", detail="shell:RecycleBinFolder")
    painter = hud.Painter(target, (0, 0), 1.0, st)
    p = QPainter(target.img)
    painter._panel(p, st, 400, 300, 60, 320)
    p.end()
    card = st.ov.rects["hud"]
    for k in ("yes", "no"):
        b = st.ov.rects[k]
        assert card[0] <= b[0] and b[2] <= card[2] and card[1] <= b[1] and b[3] <= card[3]
