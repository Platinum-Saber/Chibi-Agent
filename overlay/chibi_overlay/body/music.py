"""What kind of music is playing: "vibe" (the default, a slow sway) or "excited" (EDM and the like).

Windows' media sessions give the title, artist and album (Spotify, YouTube in a
browser, VLC, Media Player); the genre list is usually empty (Spotify leaves it
so). The style comes from whole-word keywords and known EDM artists/channels in
those fields, plus any genre given. Pure Python, unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VIBE, EXCITED = "vibe", "excited"

KEYWORDS = (
    "edm", "electro", "electronic", "house", "techno", "trance", "dubstep", "drum and bass", "drum & bass",
    "drum n bass", "dnb", "d&b", "hardstyle", "hardcore", "phonk", "nightcore", "sped up", "speed up",
    "remix", "bass boost", "bass boosted", "club mix", "extended mix", "rave", "festival mix", "trap",
    "future bass", "big room", "dance mix", "eurobeat", "hyperpop", "breakbeat", "jersey club",
)
ARTISTS = (
    "avicii", "martin garrix", "skrillex", "alan walker", "marshmello", "zedd", "calvin harris", "tiesto",
    "tiësto", "david guetta", "kygo", "illenium", "porter robinson", "madeon", "deadmau5", "hardwell",
    "steve aoki", "diplo", "major lazer", "the chainsmokers", "swedish house mafia", "armin van buuren",
    "alesso", "galantis", "daft punk", "fly by nightcore", "ncs", "nocopyrightsounds", "monstercat",
    "trap nation", "proximity", "spinnin", "ultra music", "kshmr", "dimitri vegas", "afrojack",
    "nicky romero", "excision", "subtronics", "fred again", "kaskade", "lost frequencies", "robin schulz",
    "don diablo", "oliver heldens", "san holo", "louis the child", "virtual riot", "knife party",
    "pendulum", "netsky", "sub focus", "wilkinson", "rezz", "slander", "said the sky", "seven lions",
    "gryffin", "r3hab", "w&w", "headhunterz", "da tweekaz", "bass nation", "mrsuicidesheep",
    "chill nation", "xkito music", "suicide sheep",
)


@dataclass(frozen=True)
class Track:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    genres: tuple[str, ...] = field(default_factory=tuple)
    app: str = ""  # the playing app's id (Spotify, a browser, VLC...)

    @property
    def label(self) -> str:
        return " — ".join(x for x in (self.title, self.artist) if x) or "(untitled)"


def _words(extra: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(extra, str):
        extra = extra.split(",")
    return [w.strip().lower() for w in extra if w and w.strip()]


def _pattern(words) -> re.Pattern:
    """Whole words/phrases, case-insensitive ("house" matches "Deep House", not "Housewives")."""
    alts = sorted({re.escape(w) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?![\w])", re.IGNORECASE)


_BUILT_IN = _pattern(KEYWORDS + ARTISTS)


def matches(track: Track, extra: str | list[str] = "") -> str | None:
    """The word that makes it excited, or None."""
    text = " | ".join((track.title, track.artist, track.album, track.album_artist, *track.genres))
    m = _BUILT_IN.search(text)
    if m:
        return m.group(0)
    words = _words(extra)
    if words:
        m = _pattern(words).search(text)
        if m:
            return m.group(0)
    return None


def style(track: Track | None, extra: str | list[str] = "") -> str:
    """"excited" for EDM-like tracks, else "vibe" (also when nothing is known about the track)."""
    if track is None:
        return VIBE
    return EXCITED if matches(track, extra) else VIBE
