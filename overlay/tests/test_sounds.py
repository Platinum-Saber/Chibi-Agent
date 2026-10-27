from chibi_overlay.body.brain import Moment, Mood
from chibi_overlay.sounds import Sfx, reaction_for


def test_body_events_become_reactions():
    M = Moment.LOOK_AROUND
    assert reaction_for(Mood.IDLE, Mood.SURPRISED, M, False) == "poke"
    assert reaction_for(Mood.SLEEPING, Mood.SURPRISED, M, False) == "wake"
    assert reaction_for(Mood.IDLE, Mood.HELD, M, False) == "held"
    assert reaction_for(Mood.HELD, Mood.FALLING, M, False) == "drop"
    assert reaction_for(Mood.IDLE, Mood.FALLING, M, False) is None  # the floor moved away
    assert reaction_for(Mood.FALLING, Mood.DIZZY, M, False) == "dizzy"
    assert reaction_for(Mood.IDLE, Mood.SLEEPING, M, True) == "sleep"
    assert reaction_for(Mood.IDLE, Mood.MOMENT, Moment.STRETCH, False) == "stretch"
    assert reaction_for(Mood.IDLE, Mood.MOMENT, Moment.CURIOUS, False) is None


def test_agent_moods_stay_quiet_unless_picked():
    M = Moment.LOOK_AROUND
    assert reaction_for(Mood.IDLE, Mood.TALKING, M, False) is None
    assert reaction_for(Mood.IDLE, Mood.THINKING, M, False) is None
    assert reaction_for(Mood.IDLE, Mood.THINKING, M, True) == "think"
    assert reaction_for(Mood.IDLE, Mood.HAPPY, M, False) is None
    assert reaction_for(Mood.IDLE, Mood.HAPPY, M, True) == "cheer"
    assert reaction_for(Mood.IDLE, Mood.CURSOR_NEAR, M, False) is None


def test_no_sounds_folder_is_silent():
    Sfx(None).play("click")  # nothing loaded, nothing raised
