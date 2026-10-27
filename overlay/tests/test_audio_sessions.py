import sys

import pytest

from chibi_overlay import audio_sessions as a

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows audio sessions")


@pytest.mark.parametrize("title, exe, want", [
    ("Centuries - AMV.f397.mp4 - VLC media player", "vlc.exe", "Centuries - AMV"),
    ("Levels (Avicii).mkv - MPC-HC", "mpc-hc64.exe", "Levels (Avicii)"),
    ("song.flac - mpv", "mpv.exe", "song"),
    ("VLC media player", "vlc.exe", "VLC media player"),  # nothing loaded: no suffix to strip
    ("Deep House Mix.mp3 - VLC media player", "VLC.EXE", "Deep House Mix"),
])
def test_track_title_from_a_player_window(title, exe, want):
    assert a.track_title(title, exe) == want


def test_sounding_pids_reads_the_meters_without_failing():
    peaks = a.sounding_pids(threshold=-1.0)  # every session, silent or not
    assert all(isinstance(pid, int) and 0.0 <= v <= 1.0 for pid, v in peaks.items())
