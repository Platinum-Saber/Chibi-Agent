import numpy as np

from chibi_voice.tts import TAIL_KEEP_S, calm, speakable, trim_tail


def test_trim_tail_drops_the_silence_a_short_line_was_given():
    sr = 24000
    speech = np.sin(np.linspace(0, 2000, sr)).astype(np.float32) * 0.5  # 1 s
    out = trim_tail(np.concatenate([speech, np.zeros(sr // 2, np.float32)]), sr)
    assert abs(len(out) - (sr + TAIL_KEEP_S * sr)) <= sr * 0.011
    assert len(trim_tail(speech, sr)) == sr  # nothing to trim


def test_numbers_are_spoken_not_stopped_at():
    assert speakable("It is 3.5 percent.") == "It is 3 point 5 percent."
    assert speakable("Pi is 3.14.") == "Pi is 3 point 1 4."
    assert speakable("Use qwen3.5 now") == "Use qwen3 point 5 now"
    assert speakable("Version 2.1.3 is out.") == "Version 2 point 1 point 3 is out."
    assert speakable("Costs $4.99, or $1.00.") == "Costs 4 dollars 99 cents, or 1 dollar."
    assert speakable("At 10:30, 9:05 and 7:00.") == "At 10 30, 9 oh 5 and 7 o'clock."
    assert speakable("In 2026. Then 1,200 files at 50%.") == "In 2026. Then 1,200 files at 50%."


def test_exclamations_become_calm():
    assert calm("Warning! Sir, your battery is critically low!") == \
        "Warning. Sir, your battery is critically low."
    assert calm("Really?!") == "Really?"
    assert calm("Wait... what…  now!!") == "Wait. what. now."
    assert calm("Answer. Tokyo.") == "Answer. Tokyo."
