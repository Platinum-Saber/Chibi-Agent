import tomllib
from pathlib import Path

from chibi_overlay import outfits
from chibi_overlay.vector.model import VectorModel
from chibi_overlay.vector.pose import EXPRESSIONS, GALLERY, NEUTRAL, Eyes, Mouth, Pose

PKG = Path(__file__).resolve().parents[1]


def test_every_rig_map_expression_has_a_pose():
    m = tomllib.loads((PKG / "rigs" / "raphael_chibi.toml").read_text(encoding="utf-8"))
    names = {c["expression"] for table in ("moods", "moments") for c in m[table].values() if "expression" in c}
    assert names <= set(EXPRESSIONS)


def test_lerp_blends_numbers_and_switches_variants_halfway():
    a, b = Pose(arm_l=0), Pose(arm_l=100, eyes=Eyes.HAPPY, mouth=Mouth.SMILE)
    early, late = a.lerp(b, 0.25), a.lerp(b, 0.75)
    assert early.arm_l == 25 and early.eyes == Eyes.OPEN
    assert late.arm_l == 75 and late.eyes == Eyes.HAPPY and late.mouth == Mouth.SMILE


def test_approach_switches_variants_at_once():
    p = NEUTRAL.approach(EXPRESSIONS["upset"], 0.1)
    assert p.eyes == Eyes.SQUEEZE and p.tears
    assert 0 < p.arm_l - NEUTRAL.arm_l < EXPRESSIONS["upset"].arm_l - NEUTRAL.arm_l


def test_gallery_names_are_unique():
    names = [n for n, _ in GALLERY]
    assert len(names) == len(set(names))


def test_model_expressions_params_and_scale():
    m = VectorModel("coat", widget=None)
    m.SetExpression("happy")
    assert m.base == EXPRESSIONS["happy"]
    m.SetExpression("no such face")
    assert m.base == NEUTRAL
    m.SetScale(2.0)
    m.SetScaleX(-2.0)
    m.SetScale(3.0)  # a rescale keeps her facing left
    assert (m.scale_x, m.scale_y) == (-3.0, 3.0)
    m.SetSaveParamById("ParamEyeLOpen", 0.0)
    m.Update()
    assert m.params == {}  # the stage rewrites them each frame
    assert m.IsMotionFinished()


def test_missing_models_skips_vector_rigs(tmp_path):
    o = outfits.Outfit("vector", {"chibi": "vector:coat", "serious": str(tmp_path / "s.model3.json")},
                       {"chibi": "rigs/raphael_chibi.toml", "serious": "rigs/mao.toml"})
    assert o.missing_models() == [str(tmp_path / "s.model3.json")]
