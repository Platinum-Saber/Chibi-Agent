"""The Customize window builds and applies (it is only imported when the tray opens it, so a
broken module failed silently there: a SyntaxError kept the window from ever opening)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chibi_overlay import character, customize  # noqa: E402

from tests.test_stage_outfit import st  # noqa: E402,F401  (the stage fixture)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_builds_shows_and_applies(app, st):  # noqa: F811
    sent = []
    d = customize.CustomizeDialog(st, sent.append)
    d.show_current()
    assert d.isVisible() and d.tabs.count() == 5
    d.height.setValue(400)
    d.b_dance.setText("LiSA")
    d.apply()
    assert st.character.outfits[st.outfit].height_dip == 400
    assert st.character.behaviour.dance_words == "LiSA"
    assert isinstance(st.character, character.Character)
    d.hide()
