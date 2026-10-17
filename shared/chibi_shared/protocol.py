"""WebSocket messages between agent, overlay and voice (docs/architecture.md -> IPC).

Every frame is one JSON object: {"t": <type>, "id": <uuid>, "ts": <ms>, ...payload}.
Bump VERSION when a message changes shape; `hello` carries it and the agent
refuses a client on another version.
"""
from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

VERSION = 3  # 2: tray commands, state, memory items (M6); 3: Google sign-in (M5)

Role = Literal["overlay", "voice"]
Form = Literal["chibi", "serious"]
Mood = Literal[
    "idle", "listening", "thinking", "talking", "happy", "working", "confirm",
    "briefing", "alert", "surprised", "pout", "upset", "sleepy",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


class Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: int = Field(default_factory=_now_ms)


# --- handshake (client -> agent, agent -> client) ---------------------------------
class Hello(Msg):
    t: Literal["hello"] = "hello"
    role: Role
    token: str
    version: int = VERSION


class Welcome(Msg):
    t: Literal["welcome"] = "welcome"


class Quit(Msg):
    t: Literal["quit"] = "quit"


# --- agent -> overlay -----------------------------------------------------------
class MoodReq(Msg):
    t: Literal["mood"] = "mood"
    mood: Mood
    priority: int = 0
    ttl_ms: int = 0


class FormReq(Msg):
    t: Literal["form"] = "form"
    form: Form
    sticky: bool = False


class Bubble(Msg):
    t: Literal["bubble"] = "bubble"
    text: str
    stream: bool = False
    done: bool = True


class Hud(Msg):
    t: Literal["hud"] = "hud"
    title: str
    items: list[str] = []
    progress: float | None = None


class Confirm(Msg):
    t: Literal["confirm"] = "confirm"
    call_id: str
    tool: str
    summary: str
    detail: str = ""


class Cloud(Msg):
    t: Literal["cloud"] = "cloud"
    items: list[str] = []


class Visibility(Msg):
    t: Literal["visibility"] = "visibility"
    hidden: bool
    reason: str = ""


# --- overlay -> agent -----------------------------------------------------------
class MoodAck(Msg):
    t: Literal["mood_ack"] = "mood_ack"
    req_id: str
    accepted: bool


class ConfirmResult(Msg):
    t: Literal["confirm_result"] = "confirm_result"
    call_id: str
    ok: bool


class Touch(Msg):
    t: Literal["poke", "hold", "drop"]
    x: float
    y: float
    speed: float = 0.0


class TextInput(Msg):
    t: Literal["text_input"] = "text_input"
    text: str


class FileDrop(Msg):
    t: Literal["file_drop"] = "file_drop"
    paths: list[str]


class Fullscreen(Msg):
    t: Literal["fullscreen"] = "fullscreen"
    active: bool
    exe: str = ""


CommandName = Literal[
    "toggle_visible", "mute", "unmute", "gaming_on", "gaming_off", "memory_list", "memory_delete",
    "open_settings", "autostart_on", "autostart_off", "google_signin", "google_signout", "notif_access", "quit",
]


class Command(Msg):
    """A tray-menu action (overlay -> agent)."""
    t: Literal["command"] = "command"
    name: CommandName
    arg: str = ""


# --- agent -> overlay: tray support -------------------------------------------------
class State(Msg):
    """What the tray's check marks show; sent on connect and on every change."""
    t: Literal["state"] = "state"
    muted: bool = False
    gaming: bool = False
    autostart: bool = False
    google_accounts: list[str] = []  # signed-in Google accounts (M5)
    notif_access: str = "unknown"  # Windows notification access: allowed | denied | unspecified | unknown


class MemoryItems(Msg):
    t: Literal["memory_items"] = "memory_items"
    items: list[tuple[int, str]] = []


# --- agent <-> voice ------------------------------------------------------------
class Ptt(Msg):
    t: Literal["ptt"] = "ptt"
    down: bool


class Transcript(Msg):
    t: Literal["transcript"] = "transcript"
    text: str
    ms: int


class Speak(Msg):
    t: Literal["speak"] = "speak"
    utt_id: str
    text: str
    clip: str | None = None  # name of a pre-rendered clip to play instead of synthesising


class SpeakState(Msg):
    t: Literal["speak_state"] = "speak_state"
    utt_id: str
    state: Literal["start", "end", "cancel"]


class Stop(Msg):
    t: Literal["stop"] = "stop"


class Load(Msg):
    t: Literal["load", "unload"]
    what: Literal["stt", "tts", "all"] = "all"


# --- voice -> overlay (relayed by the agent) -------------------------------------
class Lip(Msg):
    t: Literal["lip"] = "lip"
    rms: float


Message = Annotated[
    Union[Hello, Welcome, Quit, MoodReq, FormReq, Bubble, Hud, Confirm, Cloud, Visibility,
          MoodAck, ConfirmResult, Touch, TextInput, FileDrop, Fullscreen, Command, State, MemoryItems,
          Ptt, Transcript, Speak, SpeakState, Stop, Load, Lip],
    Field(discriminator="t"),
]
_adapter: TypeAdapter[Message] = TypeAdapter(Message)


def encode(msg: Msg) -> str:
    return msg.model_dump_json()


def decode(raw: str | bytes) -> Message:
    return _adapter.validate_json(raw)
