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
    root = tmp_path / "v01"  # its own parent: walk sets beside the pack stay private to the test
    _png(root, "expressions/neutral", 140)
    _png(root, "expressions/happy", 140)
    _png(root, "poses/held", 120)
    return root


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


def _walk_pack(root: Path) -> None:
    """Two walk frames whose lowest rows differ; walk.json's offsets put both boots on row 145."""
    _png(root, "walk-cycle/frames/walk_01", 140)
    _png(root, "walk-cycle/frames/walk_02", 130)
    img = QImage(str(root / "walk-cycle/frames/walk_02.png"))  # a step: its legs move over
    for y in range(110, 131):
        for x in range(40, 60):
            img.setPixelColor(x, y, QColor(0, 0, 0, 0))
            img.setPixelColor(x + 25, y, QColor("navy"))
    img.save(str(root / "walk-cycle/frames/walk_02.png"))
    (root / "walk-cycle" / "walk.json").write_text(json.dumps({
        "anchor_xy": [50, 145], "loop": True, "facing": "three-quarter toward viewer-left",
        "frames": [{"file": "frames/walk_01.png", "duration_ms": 125, "draw_offset_xy": [0, 5]},
                   {"file": "frames/walk_02.png", "duration_ms": 125, "draw_offset_xy": [2, 15]}]}),
        encoding="utf-8")


def test_walk_json_replaces_the_walk_and_anchors_its_frames(pack):
    _walk_pack(pack)
    p = sprites.Pack(pack)
    walk = p.sequences["Walk"]
    assert [k for k, _ in walk.frames] == [f"{sprites.WALK_LOCK}0", f"{sprites.WALK_LOCK}1"]
    assert walk.drawn_left and walk.loop and walk.length == pytest.approx(0.25)
    assert p.walk_dir.name == "walk-cycle"
    assert p.get(f"{sprites.WALK_LOCK}1") is not None  # built on first use
    dx, feet = p.anchors[f"{sprites.WALK_LOCK}1"]
    assert dx == 2.0 and 130 <= feet <= 145  # between the planted sole and the even bob


def test_newest_walk_set_beside_the_pack_wins(pack, tmp_path):
    _walk_pack(pack)
    other = pack.parent / "white-segment-walk"
    (other / "frames").mkdir(parents=True)
    import shutil
    for f in ("walk_01", "walk_02"):
        shutil.copy(pack / "walk-cycle" / "frames" / f"{f}.png", other / "frames" / f"{f}.png")
    data = json.loads((pack / "walk-cycle" / "walk.json").read_text(encoding="utf-8"))
    (other / "walk.json").write_text(json.dumps(data), encoding="utf-8")
    import os
    os.utime(other / "walk.json", (time.time() + 10, time.time() + 10))
    p = sprites.Pack(pack)
    assert [d.name for d in p.walk_sets()] == ["white-segment-walk", "walk-cycle"]
    assert p.walk_dir.name == "white-segment-walk"
    p.use_walk("walk-cycle")
    assert p.walk_dir.name == "walk-cycle"


def test_near_duplicate_walk_frames_are_dropped(pack):
    _walk_pack(pack)
    _png(pack, "walk-cycle/frames/walk_03", 140)  # the same legs as frame 1 again
    w = json.loads((pack / "walk-cycle" / "walk.json").read_text(encoding="utf-8"))
    w["frames"].insert(1, {"file": "frames/walk_03.png", "duration_ms": 125, "draw_offset_xy": [0, 5]})
    (pack / "walk-cycle" / "walk.json").write_text(json.dumps(w), encoding="utf-8")
    p = sprites.Pack(pack)
    assert len(p.sequences["Walk"].frames) == 3  # before the build: as listed
    p.get(f"{sprites.WALK_LOCK}0")
    walk = p.sequences["Walk"]
    assert len(walk.frames) == 2 and walk.length == pytest.approx(0.375)  # the copy is gone, the cycle keeps its time


def test_pack_without_walk_json_keeps_the_built_in_walk(pack):
    assert sprites.Pack(pack).sequences["Walk"] == sprites.SEQUENCES["Walk"]


def test_head_anchor_found_on_a_figure_not_on_a_prop(pack):
    img = QImage(100, 150, QImage.Format.Format_ARGB32)  # a head (rows 10-40, x 30-70) on a narrow body
    img.fill(Qt.GlobalColor.transparent)
    for y in range(10, 141):
        for x in (range(30, 71) if y <= 40 else range(45, 56)):
            img.setPixelColor(x, y, QColor("navy"))
    img.save(str(pack / "poses" / "figure.png"))
    p = sprites.Pack(pack)
    assert p.get("poses/figure").head == pytest.approx((30, 70, 10), abs=1)
    _png(pack, "extras/slime", 140)
    assert p.get("extras/slime").head is None


def test_sitting_raises_her_onto_the_seat(pack):
    _png(pack, "poses/sit", 140)
    _png(pack, "extras/slime", 140)
    m = sprites.SpriteModel(str(pack), None)
    img = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
    m.Resize(300, 300)

    def lowest(motion):
        m.StartMotion(motion)
        img.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter
        painter = QPainter(img)
        painter.setTransform(m.transform())
        m.paint(painter, time.monotonic())
        painter.end()
        return [y for y in range(300) if any(img.pixelColor(x, y).alpha() > 128 for x in range(0, 300, 2))][-1]

    m.wear_mask = m.wear_sword = False
    assert abs(lowest("Sit") - lowest("Idle")) <= 2  # the seat stands on the baseline


def test_tune_sets_worn_props_and_sequence_props(pack):
    from chibi_overlay import character
    ch = character.Character()
    tw = ch.tweaks("casual_coat")
    tw.mask, tw.sword = True, True
    ch.sequences["Think"] = {"frames": [["poses/think", 1.0]], "loop": True, "prop": "", "seat": sprites.SLIME}
    m = sprites.SpriteModel(str(pack), None)
    m.tune(ch, "casual_coat")
    assert m.wear_mask == sprites.MASK_ENABLED and m.wear_sword  # the mask stays off even if saved on
    assert m.sequences["Think"].prop is None and m.sequences["Think"].seat == sprites.SLIME
    assert m.sequences["Notice"].prop == sprites.SWORD  # untouched: the built-in choice
    m.tune(ch, "another_outfit")
    assert m.wear_mask == sprites.MASK_ENABLED and m.wear_sword  # outfits without settings: the sword (no mask for now)


def test_dance_cycles_build_both_styles_in_order(pack):
    for kind, names in (("type-1-vibe", ("01", "02", "03", "06", "07")), ("type-2-excited", [f"{i:02d}" for i in range(1, 9)])):
        for n in names:
            _png(pack, f"dance-cycles-v01/{kind}/frames/dance_{n}", 140)
    p = sprites.Pack(pack)
    vibe, excited = p.sequences["DanceVibe"], p.sequences["DanceExcited"]
    assert [k.rsplit("_", 1)[1] for k, _ in vibe.frames] == ["03", "02", "01", "07", "01", "02"]  # no 06
    assert vibe.frames[0][0] == "dance-cycles-v01/type-1-vibe/frames/dance_03"
    assert [k.rsplit("_", 1)[1] for k, _ in excited.frames] == ["01", "02", "03", "04", "06", "07"]
    assert excited.length == pytest.approx(1.0) and vibe.length == pytest.approx(7 * 0.20 * 1.75)
    assert vibe.loop and excited.loop and vibe.effect == excited.effect == "music_note"
    assert p.get(vibe.frames[0][0]) is not None


def test_without_dance_cycles_both_styles_use_the_old_dance(pack):
    p = sprites.Pack(pack)
    assert p.sequences["DanceVibe"] == p.sequences["DanceExcited"] == sprites.SEQUENCES["Dance"]


def test_drawn_dances_get_no_added_sway(pack):
    """The stage's dance bob (ParamBodyAngleX) tilts other poses; the drawn dances move on their own."""
    from PySide6.QtGui import QPainter
    m = sprites.SpriteModel(str(pack), None)
    m.wear_sword = False
    img = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
    m.Resize(300, 300)

    def draw(motion, lean):
        m.StartMotion(motion)
        m._t0, m._motion_t0 = 0.0, 100.0  # one moment for both draws (breathing, effects)
        m.SetSaveParamById("ParamBodyAngleX", lean)
        m.Update()
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setTransform(m.transform())
        m.paint(painter, 100.01)
        painter.end()
        return img.copy()

    assert draw("DanceExcited", 10.0) == draw("DanceExcited", 0.0)
    assert draw("Idle", 10.0) != draw("Idle", 0.0)
