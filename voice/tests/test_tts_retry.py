"""A failed F5 load is retried when live speech needs it; an asked-for unload is not."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from chibi_shared.protocol import Load
from chibi_voice import main
from chibi_voice.speech import Item
from chibi_voice.tts import TtsUnloaded


class FakeTts:
    def __init__(self, fail_loads=0):
        self.fail_loads, self.loads, self.model = fail_loads, 0, None

    @property
    def loaded(self):
        return self.model is not None

    def load(self):
        self.loads += 1
        if self.loads <= self.fail_loads:
            raise RuntimeError("Attempted to access the data pointer on an invalid python storage.")
        self.model = object()

    def unload(self):
        self.model = None

    def synth(self, text):
        if self.model is None:
            raise TtsUnloaded("tts is unloaded")
        return np.zeros(4, np.float32), 24000


class FakeClips:
    def ensure(self, synth):
        return []

    def lookup(self, text):
        return None


def app(tts) -> main.VoiceApp:
    a = main.VoiceApp.__new__(main.VoiceApp)
    a.tts, a.clips, a._bg = tts, FakeClips(), set()
    a._tts_pool = ThreadPoolExecutor(1)
    a._tts_failed_at = None
    return a


async def test_failed_load_is_retried_for_live_speech(monkeypatch):
    monkeypatch.setattr(main, "TTS_RETRY_S", 0.0)
    a = app(FakeTts(fail_loads=1))
    await a.load_tts()
    assert not a.tts.loaded
    audio, sr = await a._render(Item("u1", "Status report.", None))
    assert a.tts.loads == 2 and a.tts.loaded and sr == 24000


async def test_retry_waits_out_the_cooldown():
    a = app(FakeTts(fail_loads=5))
    await a.load_tts()
    await a._retry_tts()  # straight after the failure: no second 15 s load
    assert a.tts.loads == 1


async def test_asked_for_unload_is_not_retried(monkeypatch):
    monkeypatch.setattr(main, "TTS_RETRY_S", 0.0)
    a = app(FakeTts(fail_loads=1))
    await a.load_tts()
    await a.handle(Load(t="unload", what="tts"))
    await a._retry_tts()
    assert a.tts.loads == 1
