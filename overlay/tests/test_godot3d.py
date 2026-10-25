"""Her 3D body: frames for the Godot renderer, hull hit tests, the renderer link, the body switch."""
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from chibi_overlay import godot3d, outfits, stage as stage_mod
from chibi_overlay.body import motion
from chibi_overlay.body.brain import Mood, Moment
from chibi_overlay.body.motion import Clip
from chibi_overlay.puppet import Puppet
from chibi_shared.protocol import OutfitState

from test_stage_outfit import FakeGround, FakeLink, FakeMedia, _run_puff

PKG = Path(__file__).resolve().parents[1]
CLIPS_GD = PKG.parent / "overlay3d" / "clips.gd"


class FakeBridge:
    def __init__(self, ready=True):
        self.failed = ""
        self.ready = ready
        self.height_m, self.half_width_m = 1.47, 0.294
        self.hull = []
        self.sent = []
        self.released = 0
        self.shown = []

    def send(self, msg):
        self.sent.append(msg)

    def place(self, above, rect):
        pass

    def show(self, on):
        self.shown.append(on)

    def release(self):
        self.released += 1


@pytest.fixture
def fake_bridge(monkeypatch):
    b = FakeBridge()
    monkeypatch.setattr(godot3d.Bridge, "get", classmethod(lambda cls, project: b))
    return b


# --- hull --------------------------------------------------------------------------------------
@pytest.mark.parametrize("pts", [[(0, 0), (10, 0), (10, 20), (0, 20)], [(0, 20), (10, 20), (10, 0), (0, 0)]])
def test_point_in_hull_either_winding(pts):
    assert godot3d.in_hull(pts, 5, 10)
    assert not godot3d.in_hull(pts, 11, 10)
    assert not godot3d.in_hull(pts, 5, -1)


def test_empty_hull_never_hits():
    assert not godot3d.in_hull([], 0, 0)
    assert not godot3d.in_hull([(0, 0), (1, 1)], 0.5, 0.5)


# --- the puppet model -----------------------------------------------------------------------
def _puppet(fb=(2560, 1392), dpr=1.25):
    rig = motion.load(PKG / "rigs" / "raphael_3d.toml")
    return Puppet("godot:X:/nowhere", rig, dpr, fb)


def test_geometry_waits_for_the_renderer(fake_bridge):
    fake_bridge.ready = False
    assert _puppet().model.geom() is None
    fake_bridge.ready = True
    g = _puppet().model.geom()
    assert g.height == 1.0 and g.half_width == pytest.approx(0.2)


def test_frame_carries_feet_height_clip_params_gaze(fake_bridge):
    fb = (2560, 1392)
    pup = _puppet(fb, dpr=1.25)
    pup.configure(pup.model.geom(), fb)
    assert pup.height == pytest.approx(520 * 1.25)  # height_dip at 125 %
    assert pup.half_width == pytest.approx(pup.height * 0.2)
    pup.place(2200, 1392)
    pup.face(True)
    pup.play(Clip("Walk", None, "happy"))
    pup.set_param("ParamMouthOpenY", 0.42)
    pup.model.Drag(100, 200)
    pup.model.Update()
    (f,) = fake_bridge.sent
    assert f["t"] == "frame"
    assert f["feet"] == [pytest.approx(2200, abs=0.1), pytest.approx(1392, abs=0.1)]
    assert f["h"] == pytest.approx(650, abs=0.1)
    assert (f["motion"], f["expression"], f["walking"], f["facing_left"]) == ("Walk", "happy", True, True)
    assert f["params"] == {"ParamMouthOpenY": 0.42}
    assert f["gaze"] == [100, 200]


def test_hit_uses_the_renderers_hull(fake_bridge):
    m = _puppet().model
    fake_bridge.hull = [(100, 100), (200, 100), (200, 400), (100, 400)]
    assert m.hit(150, 300) and not m.hit(250, 300)


def test_close_releases_the_renderer_once(fake_bridge):
    m = _puppet().model
    m.close()
    m.close()
    assert fake_bridge.released == 1


# --- the renderer link (a fake renderer process instead of Godot) ---------------------------------
FAKE_RENDERER = r'''
import json, socket, sys
args = dict(a.lstrip("-").split("=", 1) for a in sys.argv if a.startswith("--") and "=" in a)
out = open(sys.argv[1], "w")
s = socket.create_connection(("127.0.0.1", int(args["renderer"])))
s.sendall((json.dumps({"t": "hello", "token": args["token"], "hwnd": 4242,
                       "height_m": 1.5, "half_width_m": 0.3}) + "\n").encode())
s.sendall(b'{"t":"hull","pts":[0,0,10,0,10,10,0,10]}\n')
buf = b""
while True:
    data = s.recv(65536)
    if not data:
        break
    buf += data
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        out.write(line.decode() + "\n"); out.flush()
        if json.loads(line).get("t") == "quit":
            sys.exit(0)
'''


@pytest.fixture
def qapp(monkeypatch, tmp_path):
    monkeypatch.setattr(godot3d.paths, "LOGS", tmp_path / "logs")  # the renderer's log, not Kryo's
    return QCoreApplication.instance() or QCoreApplication([])


def _wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_bridge_handshake_frames_and_quit(qapp, monkeypatch, tmp_path):
    fake, log = tmp_path / "fake.py", tmp_path / "got.txt"
    fake.write_text(FAKE_RENDERER)
    real_popen = subprocess.Popen
    started = []

    def popen(cmd, **kw):  # run the fake renderer with Godot's arguments
        started.append(cmd)
        return real_popen([sys.executable, "-I", str(fake), str(log), *cmd[1:]], **kw)
    monkeypatch.setattr(godot3d.subprocess, "Popen", popen)
    monkeypatch.setattr(godot3d.Bridge, "_own_window", lambda self: None)  # 4242 isn't a window

    b = godot3d.Bridge(str(tmp_path), exe="godot.exe")
    b.users = 1
    assert started[0][:3] == ["godot.exe", "--path", str(tmp_path)]
    assert "--model=res://models/raphael_teen.vrm" in started[0]
    assert _wait(lambda: b.ready and b.hull), b.failed
    assert (b.hwnd, b.height_m, b.half_width_m) == (4242, 1.5, 0.3)
    assert godot3d.in_hull(b.hull, 5, 5)
    b.send({"t": "frame", "motion": "Idle"})
    assert _wait(lambda: log.exists() and "Idle" in log.read_text())
    b.release()
    assert _wait(lambda: b.proc.poll() is not None)
    assert '"quit"' in log.read_text()


def test_bridge_refuses_a_wrong_token(qapp, monkeypatch, tmp_path):
    fake, log = tmp_path / "fake.py", tmp_path / "got.txt"
    fake.write_text(FAKE_RENDERER.replace('args["token"]', '"guess"'))
    real_popen = subprocess.Popen
    monkeypatch.setattr(godot3d.subprocess, "Popen",
                        lambda cmd, **kw: real_popen([sys.executable, "-I", str(fake), str(log), *cmd[1:]], **kw))
    b = godot3d.Bridge(str(tmp_path), exe="godot.exe")
    assert _wait(lambda: bool(b.failed))
    assert not b.ready and "hello" in b.failed
    b.close()


def test_missing_executable_fails_cleanly(qapp, tmp_path):
    b = godot3d.Bridge(str(tmp_path), exe=str(tmp_path / "no-godot.exe"))
    assert "can't start" in b.failed and not b.ready
    b.close()


# --- one body at a time ----------------------------------------------------------------------
@pytest.fixture
def st(monkeypatch, tmp_path):
    monkeypatch.setattr(stage_mod, "Ground", FakeGround)
    monkeypatch.setattr(stage_mod, "MediaWatcher", FakeMedia)
    pack = tmp_path / "pack"
    pack.mkdir()
    proj = tmp_path / "overlay3d"
    (proj / "models").mkdir(parents=True)
    (proj / "project.godot").write_text("")
    (proj / "models" / "raphael_teen.vrm").write_bytes(b"")
    (proj / "models" / "ruby.vrm").write_bytes(b"")
    w = outfits.parse({
        "outfit": "casual_coat",
        "outfits": {
            "casual_coat": {"chibi_rig": f"sprites:{pack}", "chibi_map": "rigs/raphael_sprites.toml",
                            "serious_rig": f"sprites:{pack}", "serious_map": "rigs/raphael_sprites.toml"},
            "teen_3d": {"chibi_rig": f"godot:{proj}", "chibi_map": "rigs/raphael_3d.toml",
                        "serious_rig": f"godot:{proj}", "serious_map": "rigs/raphael_3d.toml"},
            "ruby_3d": {"chibi_rig": f"godot:{proj}#ruby.vrm", "chibi_map": "rigs/raphael_3d.toml",
                        "serious_rig": f"godot:{proj}#ruby.vrm", "serious_map": "rigs/raphael_3d.toml"},
            "lost_3d": {"chibi_rig": f"godot:{tmp_path / 'gone'}", "chibi_map": "rigs/raphael_3d.toml",
                        "serious_rig": f"godot:{tmp_path / 'gone'}", "serious_map": "rigs/raphael_3d.toml"},
        },
    })
    s = stage_mod.Stage(w, PKG, 1.0, FakeLink(), own_windows=set())
    s.bodies = {"2d": "casual_coat", "3d": "teen_3d"}
    s.chibi_only = True
    s.size = {"chibi": (320.0, 60.0), "serious": (320.0, 60.0)}
    return s


def test_outfits_know_their_body(st):
    assert st.body == "2d"
    assert st.wardrobe.outfits["teen_3d"].body == "3d"
    assert st.wardrobe.outfits["lost_3d"].missing_models()  # no project, no model


def test_switch_to_3d_and_back_keeps_one_form(st):
    assert st.switch_body() == "teen_3d"
    assert st.character.outfit == "teen_3d"
    _run_puff(st)
    assert st.outfit == "teen_3d" and st.body == "3d" and st.form == "chibi"
    assert st.rig_paths["chibi"] == st.rig_paths["serious"]
    assert st.link.states()[-1].ok and st.link.states()[-1].outfit == "teen_3d"
    st.brain.request_mood(Mood.WORKING, 0)  # work doesn't transform her: chibi_only
    st.tick((0, 0))
    assert st.transform_t0 is None and st.form == "chibi"
    assert st.switch_body() == "casual_coat"
    _run_puff(st)
    assert st.body == "2d"


def test_switch_falls_back_to_the_first_outfit_of_the_other_body(st):
    st.bodies = {}
    assert st.other_body_outfit() == "teen_3d"


def test_a_3d_body_that_cant_start_goes_back_to_2d(st):
    st.switch_body()
    _run_puff(st)
    gen = st.outfit_gen
    st.body_failed("no hello from Godot in time")
    assert st.body == "2d" and st.outfit_gen == gen + 1
    last = st.link.states()[-1]
    assert not last.ok and "3D body unavailable" in last.error


# --- the mood map against the clip library ---------------------------------------------------
def test_3d_map_covers_every_mood_and_moment_with_real_clips():
    rig = motion.load(PKG / "rigs" / "raphael_3d.toml")
    clips = set(re.findall(r'"(\w+)": (?:true|false)', CLIPS_GD.read_text(encoding="utf-8")))
    assert {"Idle", "Walk", "Talk", "Think"} <= clips
    for m in Mood:
        assert m.value in rig.moods, m
        assert rig.moods[m.value].motion in clips, m
    for mo in Moment:
        assert rig.moments[mo.value].motion in clips, mo
    assert rig.moods["dancing_excited"].motion in clips
    vrm = {"neutral", "happy", "angry", "sad", "relaxed", "surprised"}
    assert {c.expression for c in [*rig.moods.values(), *rig.moments.values()]} <= vrm


def test_params_last_one_frame(fake_bridge):
    """Eyes shut while asleep must not stick once she wakes (Stage.params stops sending them)."""
    m = _puppet().model
    m.SetSaveParamById("ParamEyeLOpen", 0.0)
    m.Update()
    m.Update()
    assert fake_bridge.sent[0]["params"] == {"ParamEyeLOpen": 0.0}
    assert fake_bridge.sent[1]["params"] == {}


def _grab_at(st, frac):
    """Press at `frac` of her height above her feet, then drag."""
    x, y = st.feet
    h = st.size[st.form][0]
    st.press_at(x, y - frac * h)
    st.move_to(x + 20, y - frac * h - 20)


def test_held_from_the_torso_up_hangs(st):
    st.switch_body()
    _run_puff(st)
    _grab_at(st, 0.75)
    assert st.brain.mood == Mood.HELD and not st.grab_low
    assert st.clip("chibi").motion == "Held"


def test_held_below_the_waist_is_carried(st):
    st.switch_body()
    _run_puff(st)
    _grab_at(st, 0.3)
    assert st.brain.mood == Mood.HELD and st.grab_low
    assert st.clip("chibi").motion == "Carried"


def test_a_rig_without_held_low_just_hangs(st):
    _grab_at(st, 0.3)  # the 2D art has a single held clip
    assert st.grab_low and st.clip("chibi").motion == "Held"


def test_3d_walk_pace_matches_the_walk_clip(st):
    """She walks at the Mixamo walk's own pace (in her heights per second), not the chibi's 90 px/s."""
    rig = motion.load(PKG / "rigs" / "raphael_3d.toml")
    assert rig.walk_dip_s(90.0) == pytest.approx(0.5 * rig.height_dip)
    sprites = motion.load(PKG / "rigs" / "raphael_sprites.toml")
    assert sprites.walk_dip_s(90.0) == 90.0  # rigs without walk_speed keep the stage default
    st.switch_body()
    _run_puff(st)
    st.physics.place(st.home[0] - 400, st.home[1])
    st.brain.mood = Mood.WALKING
    x0 = st.physics.x
    st._t -= 0.05  # one 50 ms frame
    st.tick((0, 0))
    assert st.physics.x - x0 == pytest.approx(0.5 * 520 * 0.05, rel=0.05)


def test_walk_speed_tweak_is_px_per_second_whatever_her_size():
    from chibi_overlay import character
    rig = motion.load(PKG / "rigs" / "raphael_3d.toml")
    assert rig.walk_dip_s(90.0) == pytest.approx(260)  # the default: 0.5 heights/s at 520
    tw = character.OutfitTweaks(height_dip=400, walk_px_s=200)
    assert character.apply_to_map(rig, tw).walk_dip_s(90.0) == pytest.approx(200)
    ch = character.Character(outfits={"teen_3d": tw})
    back = character.parse(__import__("tomllib").loads(character.dumps(ch)))
    assert back.outfits["teen_3d"].walk_px_s == 200


def test_frames_carry_her_velocity(fake_bridge, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(godot3d.time, "monotonic", lambda: clock[0])
    fb = (2000, 1000)
    pup = _puppet(fb, dpr=1.0)
    pup.configure(pup.model.geom(), fb)
    pup.place(500, 1000)
    pup.model.Update()
    clock[0] += 1 / 60
    pup.place(504, 1000)  # 240 px/s
    pup.model.Update()
    assert fake_bridge.sent[0]["vel"] == [0.0, 0.0]
    assert fake_bridge.sent[1]["vel"][0] == pytest.approx(240, abs=1)


def test_a_rig_path_can_name_its_model(tmp_path):
    assert godot3d.split("D:/x/overlay3d") == ("D:/x/overlay3d", "raphael_teen.vrm")
    assert godot3d.split("D:/x/overlay3d#raphael_teen_ruby.vrm") == ("D:/x/overlay3d", "raphael_teen_ruby.vrm")
    (tmp_path / "project.godot").write_text("")
    assert godot3d.missing(f"{tmp_path}#ruby.vrm") == [str(tmp_path / "models" / "ruby.vrm")]


def test_switching_back_to_3d_wears_the_last_3d_variant(st):
    assert st.wardrobe.outfits["ruby_3d"].body == "3d"
    st.request_outfit("ruby_3d")
    _run_puff(st)
    assert st.outfit == "ruby_3d"
    assert st.switch_body() == "casual_coat"
    _run_puff(st)
    assert st.switch_body() == "ruby_3d"  # not [overlay.bodies]' teen_3d: the variant she last wore
