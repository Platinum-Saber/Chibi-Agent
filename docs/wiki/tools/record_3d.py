"""Record Raphael's 3D clips as PNG frame folders with Godot's Movie Maker (docs/wiki/making-the-gifs.md).

Works on a copy of overlay3d with its VRMs imported, in WORK/o3d, so the repo's .godot cache
and the deployed app stay untouched. Frames go to WORK/g3d/<name>/.

usage: python record_3d.py [name ...]   (no names: all)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORK = Path(os.environ.get("RAPHAEL_GIF_WORK", Path(tempfile.gettempdir()) / "raphael-gifs"))
PROJECT = WORK / "o3d"
OUT = WORK / "g3d"
GODOT = r"D:\Projects\Chibi-Agent-Project\Deployments\Raphael\godot\Godot_v4.7.2-stable_win64.exe"
FPS = 15

# name: (clip, expression, seconds, extra args)
SHOTS = {
    "idle": ("Idle", "neutral", 3.0, []),
    "wave": ("Wave", "happy", 2.4, []),
    "cheer": ("Happy", "happy", 2.6, []),
    "think": ("Think", "neutral", 3.0, []),
    "look_around": ("LookAround", "neutral", 3.4, []),
    "stretch": ("Stretch", "relaxed", 3.4, []),
    "dance": ("DanceExcited", "smile", 4.0, []),
    "dance_vibe": ("DanceVibe", "smile", 3.4, []),
    "sit": ("Sit", "relaxed", 3.0, []),
    "sleep": ("Sleep", "relaxed", 3.0, []),
    "talk": ("Talk", "neutral", 3.4, ["--listen=20"]),
    "answer_point": ("AnswerPoint", "neutral", 2.8, ["--listen=20"]),
    "analyse": ("Analyse", "neutral", 2.6, []),
    "notice": ("Notice", "surprised", 2.6, []),
    "surprised": ("Surprised", "surprised", 2.2, []),
    "pout": ("Pout", "angry", 3.0, []),
    "upset": ("Upset", "sad", 3.0, []),
    "held": ("Held", "surprised", 2.6, []),
    "carried": ("Carried", "surprised", 2.6, []),
    "fall": ("Fall", "surprised", 1.6, []),
    "land": ("Land", "happy", 2.0, []),
    "hardland": ("HardLand", "sad", 2.2, []),
    "fallflat": ("FallFlat", "surprised", 1.6, []),
    "flatimpact": ("FlatImpact", "sad", 1.6, []),
    "getup": ("GetUp", "neutral", 1.4, []),
    "walk": ("Walk", "neutral", 2.0, []),
}
LOW = {"sleep": 360, "carried": 400, "fallflat": 400, "flatimpact": 400, "getup": 400}  # lying down: fit the 520 px preview
TURNS =list(range(0, 360, 30))  # the middle-drag turn: one still per angle


def run(out: Path, user_args: list[str], frames: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [GODOT, "--path", str(PROJECT), "--write-movie", str(out / "f.png"), "--fixed-fps", str(FPS),
           "--quit-after", str(frames), "--", "--model=res://models/raphael.vrm", "--offscreen",
           f"--height={LOW.get(out.name, 640)}", "--render-scale=2.0", "--msaa=2", *user_args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    errs = [l for l in (r.stdout + r.stderr).splitlines() if "ERROR" in l and "tangents" not in l]
    print(out.name, len(list(out.glob("f*.png"))), "frames", *errs[:3], flush=True)


def main(names: list[str]) -> None:
    for name, (clip, expr, secs, extra) in SHOTS.items():
        if names and name not in names:
            continue
        run(OUT / name, [f"--clip={clip}", f"--expr={expr}", *extra], int(secs * FPS) + 6)  # +6: warm-up
    if not names or "turn" in names:
        for deg in TURNS:
            run(OUT / f"turn_{deg:03d}", ["--clip=Idle", f"--turn={deg}"], 8)


if __name__ == "__main__":
    main(sys.argv[1:])
