"""Where Chibi-Agent keeps its files. Nothing here lives inside the repo."""
import os
from pathlib import Path

APP = "ChibiAgent"

# Roaming: things the user would miss (memory, chats, reminders, audit log, config).
DATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
# Local: caches and runtime state (run.json, clip cache, logs).
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP

RUN_FILE = LOCAL / "run.json"
LOGS = LOCAL / "logs"
CLIPS = LOCAL / "clips"
USER_CONFIG = DATA / "config.toml"

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "config.toml"


def ensure() -> None:
    for p in (DATA, LOCAL, LOGS, CLIPS):
        p.mkdir(parents=True, exist_ok=True)
