import asyncio

import numpy as np
import pytest

from chibi_voice import main
from chibi_voice.clips import ALL_LINES, LINES, ClipCache
from chibi_voice.speech import Item, Skip


def test_reaction_lines_come_after_the_openers():
    assert ALL_LINES[:len(LINES)] == LINES and "Hm?" in ALL_LINES and len(set(ALL_LINES)) == len(ALL_LINES)


def _app(tmp_path):
    a = main.VoiceApp.__new__(main.VoiceApp)
    a.clips = ClipCache(tmp_path, "v", ALL_LINES)
    a.synthesised = []

    async def retry():
        raise AssertionError("a reaction must not touch the model")
    a._retry_tts = retry
    return a


def test_uncached_reaction_is_skipped_not_synthesised(tmp_path):
    a = _app(tmp_path)
    with pytest.raises(Skip):
        asyncio.run(a._render(Item("react-1", "Hm?", "Hm?", only_cached=True)))


def test_cached_reaction_plays(tmp_path):
    import soundfile as sf
    a = _app(tmp_path)
    sf.write(a.clips.path("Hm?"), np.zeros(240, np.float32), 24000)
    audio, sr = asyncio.run(a._render(Item("react-1", "Hm?", "Hm?", only_cached=True)))
    assert sr == 24000 and len(audio) == 240
