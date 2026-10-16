"""config.toml in the repo holds the defaults; %APPDATA%\\ChibiAgent\\config.toml overrides them."""
import tomllib
from pathlib import Path
from typing import Any

from . import paths


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(default: Path = paths.DEFAULT_CONFIG, user: Path = paths.USER_CONFIG) -> dict[str, Any]:
    cfg = tomllib.loads(default.read_text(encoding="utf-8")) if default.exists() else {}
    if user.exists():
        cfg = _merge(cfg, tomllib.loads(user.read_text(encoding="utf-8")))
    return cfg
