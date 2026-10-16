import numpy as np
import soundfile as sf

from chibi_voice.clips import LINES, ClipCache, clip_hash, slug, voice_id


def test_slug():
    assert slug("Answer.") == "answer"
    assert slug("Understood, Master.") == "understood-master"
    assert slug("End of report.") == "end-of-report"
    assert len({slug(t) for t in LINES}) == len(LINES)


def test_hash_depends_on_voice_and_text():
    assert clip_hash("v1", "Answer.") == clip_hash("v1", "Answer.")
    assert clip_hash("v1", "Answer.") != clip_hash("v2", "Answer.")
    assert clip_hash("v1", "Answer.") != clip_hash("v1", "Notice.")


def test_voice_id_covers_reference_and_settings(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"abc")
    base = voice_id(ref, "hello", 0.9, 8)
    assert voice_id(ref, "hello", 0.9, 8) == base
    assert voice_id(ref, "hello", 1.0, 8) != base
    assert voice_id(ref, "hello", 0.9, 16) != base
    assert voice_id(ref, "other", 0.9, 8) != base
    ref.write_bytes(b"abd")
    assert voice_id(ref, "hello", 0.9, 8) != base


def fake_synth(calls):
    def synth(text):
        calls.append(text)
        return np.zeros(240, dtype=np.float32), 24000
    return synth


def test_ensure_renders_missing_then_lookup(tmp_path):
    cache = ClipCache(tmp_path, "voiceA")
    assert cache.lookup("Answer.") is None
    calls = []
    assert cache.ensure(fake_synth(calls)) == LINES
    assert calls == LINES
    p = cache.lookup("Answer.")
    assert p is not None and p.name.startswith("answer-")
    data, sr = sf.read(p)
    assert sr == 24000 and len(data) == 240
    # Matched by slug, so case and punctuation don't matter; unknown lines miss.
    assert cache.lookup("answer") == p
    assert cache.lookup("Understood, Master.") != cache.lookup("Understood.")
    assert cache.lookup("Hello there.") is None
    # Second start: nothing to render.
    calls.clear()
    assert cache.ensure(fake_synth(calls)) == [] and calls == []


def test_voice_change_rerenders_and_drops_stale(tmp_path):
    ClipCache(tmp_path, "voiceA").ensure(fake_synth([]))
    old = {p.name for p in tmp_path.glob("*.wav")}
    cache = ClipCache(tmp_path, "voiceB")
    assert cache.lookup("Answer.") is None
    calls = []
    cache.ensure(fake_synth(calls))
    assert calls == LINES
    new = {p.name for p in tmp_path.glob("*.wav")}
    assert len(new) == len(LINES) and not (old & new)
    # "Understood." must not delete "Understood, Master." (shared slug prefix).
    assert cache.lookup("Understood, Master.") is not None
