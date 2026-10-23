from chibi_overlay.body import music
from chibi_overlay.body.music import EXCITED, VIBE, Track


def test_default_is_vibe():
    assert music.style(None) == VIBE
    assert music.style(Track()) == VIBE
    assert music.style(Track("Clair de Lune", "Claude Debussy")) == VIBE
    assert music.style(Track("lofi beats to study to", "Lofi Girl")) == VIBE


def test_edm_keywords_in_any_field():
    assert music.style(Track("Demons (Sped Up Version)", "Fly By Nightcore", "Goes Acoustic, Vol. 5")) == EXCITED
    assert music.style(Track("Faded (Remix)", "Someone")) == EXCITED
    assert music.style(Track("Song", "Band", "Best of Deep House 2026")) == EXCITED
    assert music.style(Track("Song", "Band", genres=("Dance/Electronic",))) == EXCITED
    assert music.style(Track("DRUM AND BASS MIX", "A YouTube channel")) == EXCITED


def test_known_artists_and_channels():
    assert music.style(Track("Levels", "Avicii")) == EXCITED
    assert music.style(Track("Song", "NCS")) == EXCITED          # YouTube's channel as the artist
    assert music.style(Track("Tiësto - The Business", "Ultra Music")) == EXCITED


def test_whole_words_only():
    assert music.style(Track("Real Housewives theme", "TV")) == VIBE   # not "house"
    assert music.style(Track("Electrolyte", "Chemistry Class")) == VIBE   # not "electro"
    assert music.style(Track("The Ravens", "Poet")) == VIBE   # not "rave"


def test_kryos_extra_words():
    t = Track("Gurenge", "LiSA")
    assert music.style(t) == VIBE
    assert music.style(t, "LiSA, anime openings") == EXCITED
    assert music.matches(t, ["lisa"]).lower() == "lisa"
    assert music.style(t, " , ") == VIBE
