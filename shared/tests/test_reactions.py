import re

from chibi_shared.protocol import Command, React, Speak, decode, encode
from chibi_shared.reactions import IDLE_EVENTS, REACTIONS, all_lines


def test_react_and_cached_speak_round_trip():
    m = decode(encode(React(event="poke", picked=True)))
    assert isinstance(m, React) and (m.event, m.picked) == ("poke", True)
    s = decode(encode(Speak(utt_id="react-1", text="Hm?", clip="Hm?", only_cached=True)))
    assert s.only_cached and s.clip == "Hm?"
    assert decode(encode(Command(name="restart"))).name == "restart"  # the tray's Restart agent


def test_reaction_lines_have_distinct_clip_slugs():
    """Clips are looked up by slug: two lines with one slug would play the wrong one."""
    slugs = [re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") for t in all_lines()]
    assert len(slugs) == len(set(slugs))
    assert IDLE_EVENTS <= set(REACTIONS)
