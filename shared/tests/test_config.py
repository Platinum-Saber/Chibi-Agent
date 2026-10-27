from pathlib import Path

from chibi_shared import config


def test_paths_expand_vars_home_and_the_app_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    default = tmp_path / "config.toml"
    default.write_text("""
[voice]
kokoro_dir = '%LOCALAPPDATA%\\ChibiAgent\\kokoro'
reference = ''
[overlay]
sounds_dir = 'assets/sounds'
sfx_volume = 0.6
[overlay.outfits.chibi]
chibi_rig = 'sprites:assets/chibi/casual-coat'
serious_rig = 'godot:overlay3d#raphael.vrm'
""", encoding="utf-8")
    cfg = config.load(default, tmp_path / "none.toml")
    assert cfg["voice"]["kokoro_dir"] == r"C:\Users\x\AppData\Local\ChibiAgent\kokoro"
    assert cfg["voice"]["reference"] == ""
    assert cfg["overlay"]["sounds_dir"] == str(tmp_path / "assets/sounds")
    assert cfg["overlay"]["sfx_volume"] == 0.6
    o = cfg["overlay"]["outfits"]["chibi"]
    assert o["chibi_rig"] == "sprites:" + str(tmp_path / "assets/chibi/casual-coat")
    assert o["serious_rig"] == "godot:" + str(tmp_path / "overlay3d") + "#raphael.vrm"


def test_user_overrides_keep_absolute_paths(tmp_path):
    default, user = tmp_path / "config.toml", tmp_path / "user.toml"
    default.write_text("[overlay]\nfonts_dir = ''\n", encoding="utf-8")
    user.write_text("[overlay]\nfonts_dir = 'D:\\\\fonts'\n", encoding="utf-8")
    assert config.load(default, user)["overlay"]["fonts_dir"] == r"D:\fonts"


def test_rig_path_leaves_absolute_rigs_alone():
    assert config.rig_path(r"D:\rigs\Mao.model3.json", Path("C:/app")) == r"D:\rigs\Mao.model3.json"
