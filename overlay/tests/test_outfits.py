from pathlib import Path

import pytest

from chibi_overlay import outfits

PKG = Path(__file__).resolve().parents[1]


def _cfg(**extra):
    return {
        "outfit": "robe",
        "chibi_map": "rigs/haru.toml",
        "serious_map": "rigs/mao.toml",
        "outfits": {
            "robe": {"chibi_rig": "robe/c.model3.json", "serious_rig": "robe/s.model3.json"},
            "coat": {"chibi_rig": "coat/c.model3.json", "serious_rig": "coat/s.model3.json",
                     "serious_map": "rigs/haru.toml"},
        },
        **extra,
    }


def test_outfits_table():
    w = outfits.parse(_cfg())
    assert w.current == "robe"
    assert w.names == ["robe", "coat"]
    assert w.outfits["coat"].rigs == {"chibi": "coat/c.model3.json", "serious": "coat/s.model3.json"}


def test_maps_default_to_the_shared_ones():
    w = outfits.parse(_cfg())
    assert w.outfits["robe"].maps == {"chibi": "rigs/haru.toml", "serious": "rigs/mao.toml"}
    assert w.outfits["coat"].maps == {"chibi": "rigs/haru.toml", "serious": "rigs/haru.toml"}


def test_legacy_keys_make_one_default_outfit():
    w = outfits.parse({"chibi_rig": "a.model3.json", "chibi_map": "rigs/haru.toml",
                       "serious_rig": "b.model3.json", "serious_map": "rigs/mao.toml"})
    assert w.current == outfits.LEGACY
    assert w.outfits[outfits.LEGACY].rigs == {"chibi": "a.model3.json", "serious": "b.model3.json"}


def test_top_level_rig_fills_a_gap_only():
    cfg = _cfg(chibi_rig="old.model3.json")
    del cfg["outfits"]["coat"]["chibi_rig"]
    w = outfits.parse(cfg)
    assert w.outfits["coat"].rigs["chibi"] == "old.model3.json"
    assert w.outfits["robe"].rigs["chibi"] == "robe/c.model3.json"


def test_unknown_current_outfit_falls_back_to_the_first():
    assert outfits.parse(_cfg(outfit="cape")).current == "robe"


def test_no_current_outfit_means_the_first():
    cfg = _cfg()
    del cfg["outfit"]
    assert outfits.parse(cfg).current == "robe"


def test_missing_rig_is_an_error():
    cfg = _cfg()
    del cfg["outfits"]["coat"]["serious_rig"]
    with pytest.raises(ValueError, match="coat.*serious_rig"):
        outfits.parse(cfg)


def test_missing_map_is_an_error():
    cfg = _cfg()
    del cfg["chibi_map"]
    with pytest.raises(ValueError, match="chibi_map"):
        outfits.parse(cfg)


def test_load_maps_and_missing_models(tmp_path):
    (tmp_path / "c.model3.json").write_text("{}")
    o = outfits.Outfit("robe", {"chibi": str(tmp_path / "c.model3.json"), "serious": str(tmp_path / "s.model3.json")},
                       {"chibi": "rigs/haru.toml", "serious": "rigs/mao.toml"})
    maps = o.load_maps(PKG)
    assert maps["serious"].height_dip == 420
    assert o.missing_models() == [str(tmp_path / "s.model3.json")]


def test_repo_config_parses():
    import tomllib
    cfg = tomllib.loads((PKG.parent / "config.toml").read_text(encoding="utf-8"))["overlay"]
    w = outfits.parse(cfg)
    assert w.current in w.names and set(w.names) == {"chibi", "rimuru", "raphael"}
    for o in w.outfits.values():
        o.load_maps(PKG)


def test_an_outfit_without_its_serious_vrm_stays_chibi_only(tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    proj = tmp_path / "overlay3d"
    (proj / "models").mkdir(parents=True)
    (proj / "project.godot").write_text("")
    w = outfits.parse({"outfit": "raphael", "outfits": {
        "chibi": {"chibi_rig": f"sprites:{pack}", "chibi_map": "rigs/raphael_sprites.toml",
                  "serious_rig": f"godot:{proj}#raphael.vrm", "serious_map": "rigs/raphael_3d.toml"},
        "raphael": {"chibi_rig": f"godot:{proj}#raphael.vrm", "chibi_map": "rigs/raphael_3d.toml",
                    "serious_rig": f"godot:{proj}#raphael.vrm", "serious_map": "rigs/raphael_3d.toml"}}})
    u = outfits.usable(w)
    assert u.names == ["chibi"] and u.current == "chibi"  # no VRM: the 3D outfit is left out
    o = u.outfits["chibi"]
    assert o.chibi_only and o.rigs["serious"] == o.rigs["chibi"] and not o.missing_models()
    (proj / "models" / "raphael.vrm").write_bytes(b"")
    u = outfits.usable(w)
    assert u.names == ["chibi", "raphael"] and u.current == "raphael"
    assert not u.outfits["chibi"].chibi_only
