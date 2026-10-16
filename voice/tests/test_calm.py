from chibi_voice.tts import calm


def test_exclamations_become_calm():
    assert calm("Warning! Sir, your battery is critically low!") == \
        "Warning. Sir, your battery is critically low."
    assert calm("Really?!") == "Really?"
    assert calm("Wait... what…  now!!") == "Wait. what. now."
    assert calm("Answer. Tokyo.") == "Answer. Tokyo."
