import json
import time
import tomllib
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage

from chibi_overlay import outfits, sprites

PKG = Path(__file__).resolve().parents[1]
REAL_PACK = Path(r"D:/Character Design/output/assets/chibi/casual-coat/v01")


def _png(root: Path, key: str, feet: int, w: int = 100, h: int = 150) -> None:
    """A canvas with one opaque block standing on row `feet`."""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    for y in range(feet - 60, feet + 1):
        for x in range(40, 60):
            img.setPixelColor(x, y, QColor("navy"))
    (root / key).parent.mkdir(parents=True, exist_ok=True)
    img.save(str(root / f"{key}.png"))


@pytest.fixture
def pack(tmp_path):
    _png(tmp_path, "expressions/neutral", 140)
    _png(tmp_path, "expressions/happy", 140)
    _png(tmp_path, "poses/held", 120)
    return tmp_path


def test_every_mapped_motion_has_a_sequence():
    m = tomllib.loads((PKG / "rigs" / "raphael_sprites.toml").read_text(encoding="utf-8"))
    motions = {c["motion"] for table in ("moods", "moments") for c in m[table].values()}
    assert motions <= set(SEQUENCES := sprites.SEQUENCES), motions - set(SEQUENCES)


@pytest.mark.skipif(not REAL_PACK.exists(), reason="Kryo's art pack is outside git")
def test_real_pack_has_every_image_the_sequences_use():
    keys = {k for s in sprites.SEQUENCES.values() for k, _ in s.frames}
    keys |= {s.prop for s in sprites.SEQUENCES.values() if s.prop}
    assert [k for k in keys if not (REAL_PACK / f"{k}.png").exists()] == []
    effects = {s.effect for s in sprites.SEQUENCES.values() if s.effect}
    assert [e for e in effects if not (REAL_PACK / "effects" / f"{e}.svg").exists()] == []


def test_feet_line_up_across_poses(pack):
    p = sprites.Pack(pack)
    assert p.feet == 140
    assert p.get("poses/held").feet == 120  # drawn 20 canvas px lower to share the baseline
    assert p.canvas == pytest.approx((100, 150), abs=1)


def test_drawn_feet_land_on_the_neutral_baseline(pack):
    m = sprites.SpriteModel(str(pack), None)
    img = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
    m.Resize(300, 300)

    def bottom(motion):
        m.StartMotion(motion)
        img.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter
        painter = QPainter(img)
        painter.setTransform(m.transform())
        m.paint(painter, time.monotonic())
        painter.end()
        rows = [y for y in range(300) if any(img.pixelColor(x, y).alpha() > 128 for x in range(0, 300, 2))]
        return rows[-1]

    assert abs(bottom("Idle") - bottom("Held")) <= 2


def test_one_shot_sequence_ends_and_loops_never_do(pack):
    m = sprites.SpriteModel(str(pack), None)
    m.SetExpression("happy")
    m.StartMotion("Land")
    assert not m.IsMotionFinished()
    assert m.frame(time.monotonic())[0] == "poses/land_squash"
    m._motion_t0 -= 10
    assert m.IsMotionFinished()
    assert m.frame(time.monotonic())[0] == "expressions/happy"
    m.StartMotion("Walk")
    m._motion_t0 -= 10
    assert not m.IsMotionFinished()


def test_walk_frames_are_flipped_to_face_right_unmirrored():
    # the overlay mirrors her when she walks left, so unmirrored frames must face right
    walk = sprites.SEQUENCES["Walk"]
    assert walk.drawn_left and all(k.startswith("poses/walk") for k, _ in walk.frames)


def test_unknown_expression_falls_back_to_neutral(pack):
    m = sprites.SpriteModel(str(pack), None)
    m.SetExpression("no such face")
    assert m.expression == "neutral"


def _gaze_pack(root: Path) -> None:
    states = [{"x": x, "y": y, "file": f"gaze/{x}_{y}.png"} for x in (-1, 0, 1) for y in (-1, 0, 1)]
    (root / "gaze-map.json").write_text(json.dumps({
        "selection": {"center_deadzone": 0.15},
        "rendering": {"eye_rectangles_xywh": [[30, 20, 10, 8], [60, 20, 10, 8]]},
        "states": states}), encoding="utf-8")


def test_gaze_picks_the_nearest_45_degree_sector(pack):
    _gaze_pack(pack)
    p = sprites.Pack(pack)
    assert p.gaze_key(0.05, 0.05) == "gaze/0_0"   # dead zone
    assert p.gaze_key(1.0, 0.1) == "gaze/1_0"
    assert p.gaze_key(-0.7, 0.7) == "gaze/-1_1"   # up-left (y is up)
    assert p.gaze_key(0.2, -1.0) == "gaze/0_-1"


def test_pack_without_gaze_map_has_no_eye_follow(pack):
    p = sprites.Pack(pack)
    assert p.gaze_key(1.0, 0.0) is None and p.eye_rects == []


def test_gaze_switches_only_after_the_hold(pack):
    _gaze_pack(pack)
    m = sprites.SpriteModel(str(pack), None)
    m._look = (500.0, 24.0)  # far to the right of her eyes, level with them
    t = 100.0
    assert m.gaze(t) is None
    assert m.gaze(t + sprites.GAZE_HOLD_S / 2) is None
    assert m.gaze(t + sprites.GAZE_HOLD_S + 0.01) == "gaze/1_0"


@pytest.mark.skipif(not REAL_PACK.exists(), reason="Kryo's art pack is outside git")
def test_real_pack_has_every_gaze_drawing():
    p = sprites.Pack(REAL_PACK)
    assert len(p.gaze) == 9 and len(p.eye_rects) == 2
    assert [k for k in p.gaze.values() if not (REAL_PACK / f"{k}.png").exists()] == []


def test_missing_models_checks_the_pack_folder(tmp_path):
    o = outfits.Outfit("casual_coat", {"chibi": f"sprites:{tmp_path}", "serious": f"sprites:{tmp_path / 'nope'}"},
                       {"chibi": "rigs/raphael_sprites.toml", "serious": "rigs/mao.toml"})
    assert o.missing_models() == [f"sprites:{tmp_path / 'nope'}"]
