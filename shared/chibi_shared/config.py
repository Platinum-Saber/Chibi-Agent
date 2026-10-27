"""config.toml in the repo holds the defaults; %APPDATA%\\ChibiAgent\\config.toml overrides them.

Path settings may use environment variables (%LOCALAPPDATA%), ~ and paths relative to the app
folder (the repo, or the install folder): `load` turns them into absolute paths, so the shipped
config works wherever the app is installed."""
import os
import tomllib
from pathlib import Path
from typing import Any

from . import paths

# section -> keys that hold a file or folder path
PATH_KEYS = {
    "ollama": ("exe", "models_dir"),
    "voice": ("hf_home", "reference", "reference_text", "kokoro_dir"),
    "overlay": ("fonts_dir", "sounds_dir", "godot_exe"),
}
RIG_PREFIXES = ("sprites:", "godot:", "vector:")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def path(value: str, root: Path = paths.REPO) -> str:
    """Expand %VARS% and ~; a relative path is relative to the app folder. "" stays ""."""
    if not value:
        return value
    p = Path(os.path.expanduser(os.path.expandvars(value)))
    return str(p if p.is_absolute() else root / p)


def rig_path(value: str, root: Path = paths.REPO) -> str:
    """A rig path keeps its kind prefix (sprites:, godot:) and a godot `#model.vrm` suffix."""
    prefix = next((p for p in RIG_PREFIXES if value.startswith(p)), "")
    rest, sep, model = value[len(prefix):].partition("#")
    return prefix + (path(rest, root) if rest else rest) + sep + model


def _expand(cfg: dict, root: Path) -> dict:
    for section, keys in PATH_KEYS.items():
        sec = cfg.get(section)
        if isinstance(sec, dict):
            for k in keys:
                if isinstance(sec.get(k), str):
                    sec[k] = path(sec[k], root)
    ov = cfg.get("overlay")
    if isinstance(ov, dict):
        for t in [ov, *(ov.get("outfits") or {}).values()]:
            for form in ("chibi", "serious"):
                if isinstance(t.get(f"{form}_rig"), str):
                    t[f"{form}_rig"] = rig_path(t[f"{form}_rig"], root)
    return cfg


def load(default: Path = paths.DEFAULT_CONFIG, user: Path = paths.USER_CONFIG) -> dict[str, Any]:
    cfg = tomllib.loads(default.read_text(encoding="utf-8")) if default.exists() else {}
    if user.exists():
        cfg = _merge(cfg, tomllib.loads(user.read_text(encoding="utf-8")))
    return _expand(cfg, default.parent)
