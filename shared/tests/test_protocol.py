from typing import get_args

import pytest
from pydantic import ValidationError

from chibi_shared import protocol as p

SAMPLES = [
    p.Hello(role="voice", token="x"), p.Welcome(), p.Quit(),
    p.MoodReq(mood="thinking", priority=1, ttl_ms=500), p.FormReq(form="serious", sticky=True),
    p.Bubble(text="Answer.", stream=True, done=False), p.Hud(title="Report", items=["a"], progress=0.5),
    p.Confirm(call_id="c1", tool="run_shell", summary="Run a command", detail="Get-Process"),
    p.Cloud(items=["Reminder"]), p.Visibility(hidden=True, reason="fullscreen"),
    p.MoodAck(req_id="r", accepted=False), p.ConfirmResult(call_id="c1", ok=True),
    p.Touch(t="poke", x=1, y=2), p.Touch(t="drop", x=1, y=2, speed=900),
    p.TextInput(text="hi"), p.FileDrop(paths=["C:/a.txt"]), p.Fullscreen(active=True, exe="game.exe"),
    p.Command(name="memory_delete", arg="3"), p.State(muted=True, gaming=False, autostart=True, google_accounts=["a@x.com", "b@y.lk"], notif_access="allowed"),
    p.Command(name="notif_access"),
    p.Command(name="google_signout", arg="a@x.com"),
    p.MemoryItems(items=[(1, "Kryo likes tea.")]),
    p.VoiceTune(engine="kokoro", voice="bf_emma", speed=1.0), p.Command(name="voice_test", arg="Yes, Sir."),
    p.OutfitReq(outfit="coat"), p.OutfitState(outfit="robe", outfits=["robe", "coat"]),
    p.OutfitState(outfit="robe", outfits=["robe"], ok=False, error="no outfit 'cape'"),
    p.Ptt(down=True), p.Transcript(text="hello", ms=180), p.Speak(utt_id="u", text="Hi.", clip="answer"),
    p.SpeakState(utt_id="u", state="end"), p.Stop(), p.Load(t="unload", what="tts"), p.Lip(rms=0.3),
]


def test_every_message_type_has_a_sample():
    union = get_args(get_args(p.Message)[0])  # Annotated[Union[...], Field]
    assert set(union) == {type(m) for m in SAMPLES}


@pytest.mark.parametrize("msg", SAMPLES, ids=lambda m: m.t)
def test_round_trip(msg):
    assert p.decode(p.encode(msg)) == msg


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        p.decode('{"t": "launch_missiles", "id": "x", "ts": 0}')


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        p.decode('{"t": "stop", "id": "x", "ts": 0, "evil": 1}')
