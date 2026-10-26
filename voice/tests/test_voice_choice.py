"""She starts on the last voice chosen in Customize, and clips are keyed by the voice that renders them."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from chibi_shared.protocol import VoiceTune
from chibi_voice import env, main
from chibi_voice.clips import ClipCache


class FakeTts:
    def __init__(self, vcfg=None):
        self.engine, self.kvoice, self.speed, self.ref, self.tuned = "f5", "bf_emma", 0.9, "ref.wav", []
        self.kokoro = self.model = None

    @property
    def loaded(self):
        return (self.kokoro if self.engine == "kokoro" else self.model) is not None

    def tune(self, engine, voice, speed, nfe):
        self.tuned.append((engine, voice, speed, nfe))
        self.engine, self.kvoice = engine, voice or self.kvoice

    def voice_key(self):
        return f"{self.engine}:{self.kvoice}"

    def load(self):
        if self.engine == "kokoro":
            self.kokoro = object()
        else:
            self.model = object()

    def synth(self, text):
        return np.full(4, 0.1 if self.engine == "kokoro" else 0.2, np.float32), 24000


def test_saved_voice_round_trip(tmp_path):
    p = tmp_path / "voice_tune.json"
    assert main.saved_voice(p) is None
    main.save_voice(VoiceTune(engine="kokoro", voice="bf_emma", speed=1.05, nfe=8), p)
    got = main.saved_voice(p)
    assert (got.engine, got.voice, got.speed, got.nfe) == ("kokoro", "bf_emma", 1.05, 8)


def test_unreadable_saved_voice_is_ignored(tmp_path):
    p = tmp_path / "voice_tune.json"
    p.write_text("{not json", encoding="utf-8")
    assert main.saved_voice(p) is None


def test_start_tunes_to_the_saved_voice_before_any_load(tmp_path, monkeypatch):
    p = tmp_path / "voice_tune.json"
    main.save_voice(VoiceTune(engine="kokoro", voice="af_sky", speed=1.05, nfe=8), p)
    for name in ("Stt", "Recorder", "Player", "SpeechQueue"):
        monkeypatch.setattr(main, name, lambda *a, **k: type("Stub", (), {"play": None})())
    monkeypatch.setattr(main, "Tts", FakeTts)
    monkeypatch.setattr(main.paths, "CLIPS", tmp_path / "clips")
    a = main.VoiceApp({}, send=None, last_voice=p)
    assert a.tts.tuned == [("kokoro", "af_sky", 1.05, 8)]
    assert not a.tts.loaded
    assert a.clips.voice == "kokoro:af_sky"


async def test_switch_queued_behind_a_load_renders_clips_once_under_the_new_key(tmp_path, monkeypatch):
    monkeypatch.setattr(main.paths, "CLIPS", tmp_path)
    a = main.VoiceApp.__new__(main.VoiceApp)
    a.tts, a._bg, a._tts_failed_at = FakeTts(), set(), None
    a._last_voice = tmp_path / "voice_tune.json"
    a._tts_pool = ThreadPoolExecutor(1)
    a.clips = ClipCache(tmp_path, a.tts.voice_key())
    a.tts.load()  # F5 loaded; the Customize choice arrives next
    await a.load_tts()
    await a.retune(VoiceTune(engine="kokoro", voice="bf_emma", speed=1.05, nfe=8))
    rendered = ClipCache(tmp_path, "kokoro:bf_emma")
    assert a.clips.voice == "kokoro:bf_emma" and not rendered.missing()
    assert main.saved_voice(a._last_voice).engine == "kokoro"


def _tts(tmp_path, **vcfg):
    from chibi_voice.tts import Tts
    (tmp_path / "ref.txt").write_text("Reference.", encoding="utf-8")
    return Tts({"reference": str(tmp_path / "ref.wav"), "reference_text": str(tmp_path / "ref.txt"),
                "speed": 0.9, **vcfg})


def test_f5_off_makes_kokoro_the_voice(tmp_path):
    t = _tts(tmp_path, f5=False)
    assert (t.engine, t.kvoice, t.speed) == ("kokoro", "bf_emma", 1.0)
    t.tune("f5", "", 0.9, 8)  # a saved F5 choice, or one from Customize
    assert (t.engine, t.kvoice, t.speed) == ("kokoro", "bf_emma", 1.0)
    t.tune("kokoro", "af_sky", 1.1, 8)
    assert (t.engine, t.kvoice, t.speed) == ("kokoro", "af_sky", 1.1)


def test_f5_on_is_unchanged(tmp_path):
    t = _tts(tmp_path)
    assert (t.engine, t.speed) == ("f5", 0.9)
    t.tune("f5", "", 0.9, 8)
    assert t.engine == "f5"


def test_hub_goes_offline_only_when_every_model_is_cached(tmp_path):
    repos = ["SWivid/F5-TTS", "charactr/vocos-mel-24khz"]
    assert not env.cached(str(tmp_path), repos)
    for r in repos:
        (tmp_path / "hub" / f"models--{r.replace('/', '--')}" / "snapshots" / "abc").mkdir(parents=True)
    assert env.cached(str(tmp_path), repos)
    assert not env.cached(str(tmp_path), repos + ["Systran/faster-whisper-small.en"])
