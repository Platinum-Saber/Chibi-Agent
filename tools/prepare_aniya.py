"""Make an app-ready working copy of the free ANIYA Live2D model (DG_studio).

Licence (ANIYA/Instructions.txt): personal use; no for-profit streaming, no
redistribution. So the copy lives outside git, beside the repo, and this script
holds only names and wiring, no model data.

    python tools/prepare_aniya.py [SRC_DIR] [OUT_DIR]

defaults: SRC = D:/Projects/Chibi-Agent-Project/ANIYA/ANIYA,
          OUT = D:/Projects/Chibi-Agent-Project/ChibiAgent/rigs/chibi/aniya
Writes:
- textures downscaled 8192 -> 2048 (six 8192 atlases are ~1.6 GB of VRAM; the
  overlay budget is ~300 MiB; she's drawn ~320 px tall, so 2048 is plenty)
- aniya.cdi3.json with English display names (IDs unchanged: motions,
  physics and expressions keep working); TRANSLATION.md lists them all
- exp/<name>.exp3.json: the app's 9 expression names mapped onto her
  reaction faces, plus every original face under an English name
- motions/: Idle (new, gentle breath/sway), Walk (her walk loop), and the
  original scenes under English names
- aniya.model3.json with LipSync = ParamMouthOpenY (the original group was empty)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\Projects\Chibi-Agent-Project\ANIYA\ANIYA")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\Projects\Chibi-Agent-Project\ChibiAgent\rigs\chibi\aniya")
TEX = 2048

# --- translations (Chinese display names in ANIYA.cdi3.json -> English) ------------------
PARAM_EN = {
    "expression1": "Face: crying (哭哭)", "expression2": "Face: shocked (震惊)",
    "expression3": "Face: classic smug 'heh' (经典表情)", "expression4": "Face: confused '?' (？)",
    "expression5": "Face: star eyes (星星)", "expression6": "Face: angry (生气)",
    "expression7": "Face: speechless (无语)", "expression8": "Face: startled (吃惊)",
    "expression9": "Face: sleeping zzz (zzz)", "expression10": "Face: wailing (大哭)",
    "expression11": "Outfit change (换衣服)", "Param14": "Hand gesture (手势)",
    "Param61": "Peanut appears (花生出现)", "Param80": "Toothy grin (呲牙表情)",
    "Param81": "Tiny pupils (小眼珠)",
    "Param84": "Right leg (右腿)", "Param87": "Right leg 2 (右腿2)", "Param85": "Left leg (左腿)",
    "Param88": "Left leg 2 (左腿2)", "Param86": "Walk ss", "Param89": "Walk y", "Param90": "Walk y2",
    "Param": "Jelly eye 1 (果冻眼1)", "Param2": "Jelly eye 2", "Param3": "Jelly eye 3",
    "Param4": "Eye highlight 1 (高光1)", "Param5": "Eye highlight 2", "Param15": "Jelly eye 4",
    "Param16": "Jelly eye 5", "Param17": "Jelly eye 6", "Param18": "Eye highlight 3", "Param19": "Eye highlight 4",
    "Param45": "Ahoge physics 1 (呆毛物理1)", "Param46": "Ahoge physics 2", "Param47": "Ahoge physics 3",
    "Param6": "Front hair physics 1 (前发物理1)", "Param7": "Front hair physics 2",
    "Param8": "Front hair physics 3", "Param9": "Front hair physics 4",
    "Param39": "Front hair physics 1 Y", "Param40": "Front hair physics 2 Y",
    "Param41": "Front hair physics 3 Y", "Param42": "Front hair physics 4 Y",
    "Param10": "Back hair physics 1 (后发物理1)", "Param11": "Back hair physics 2",
    "Param12": "Back hair physics 3", "Param13": "Back hair physics 4",
    "Param35": "Back hair physics 1 Y", "Param36": "Back hair physics 2 Y",
    "Param37": "Back hair physics 3 Y", "Param38": "Back hair physics 4 Y",
    "Param20": "Clothes physics 1 (衣服物理1)", "Param21": "Clothes physics 2", "Param22": "Clothes physics 3",
    "Param23": "Clothes physics 4", "Param24": "Clothes physics 5", "Param25": "Clothes physics 6",
    "Param43": "Skirt physics Y1 (裙子物理Y1)", "Param44": "Skirt physics Y2",
    "Param26": "Arm 1 (手臂1)", "Param27": "Arm 2", "Param28": "Arm 3", "Param29": "Arm 4",
    "Param30": "Arm 5", "Param31": "Arm 6",
    "Param32": "Bow physics 1 (蝴蝶结物理1)", "Param33": "Bow physics 2", "Param34": "Bow physics 3",
    "Param48": "Star orbit (星星轨道)", "Param49": "Star spin (星星旋转)", "Param50": "Star grow (星星放大)",
    "Param51": "Star vanish (星星消失)", "Param82": "Star appear 2 (星星出现2)",
    "Param52": "Star move 1 (星星移动1)", "Param54": "Star move 2", "Param53": "Orbit appears (轨道出现)",
    "Param55": "Star physics 1 (星星物理1)", "Param56": "Star physics 2", "Param57": "Star physics 3",
    "Param58": "Star physics 4", "Param59": "Star X", "Param60": "Star Y",
    "Param62": "Chewing (咀嚼)", "Param63": "Small peanut appears (小花生出现)",
    "Param64": "Small peanut moves (小花生移动)", "Param65": "Big peanut appears (大花生出现)",
    "Param66": "Big peanuts gather (大花生集中)", "Param70": "Big peanut vanishes (大花生消失)",
    "Param68": "White grows (白放大)", "Param67": "Anya turns white (阿尼亚变白)",
    "Param69": "White vanishes (白消失)", "Param71": "Smoke (烟雾)", "Param73": "Arm waving (手臂挥动)",
    "Param75": "Peanut arms appear (花生手臂出现)", "Param72": "Smoke at feet (脚底烟雾)",
    "Param74": "Peanut bob (花生上下)",
    "Param76": "Crying physics 1 (哭哭物理1)", "Param78": "Crying physics 2",
    "Param77": "Tears fall (眼泪落下)", "Param79": "zzz bubble (zzz)", "Param83": "Mouth X (mouthX)",
    "ParamAngleX": "Angle X", "ParamAngleY": "Angle Y", "ParamAngleZ": "Angle Z",
    "ParamEyeLOpen": "Left eye open", "ParamEyeLSmile": "Left eye smile", "ParamEyeROpen": "Right eye open",
    "ParamEyeRSmile": "Right eye smile", "ParamEyeBallX": "Eyeball X", "ParamEyeBallY": "Eyeball Y",
    "ParamBrowLY": "Left brow up/down", "ParamBrowRY": "Right brow up/down",
    "ParamBrowLAngle": "Left brow angle", "ParamBrowRAngle": "Right brow angle",
    "ParamBrowLForm": "Left brow form", "ParamBrowRForm": "Right brow form",
    "ParamMouthForm": "Mouth form", "ParamMouthOpenY": "Mouth open", "ParamCheek": "Cheek blush",
    "ParamBodyAngleX": "Body angle X", "ParamBodyAngleY": "Body angle Y", "ParamBodyAngleZ": "Body angle Z",
    "ParamBreath": "Breath", "ParamHairFront": "Hair sway front", "ParamHairSide": "Hair sway side",
    "ParamHairBack": "Hair sway back",
}
GROUP_EN = {"表情": "Expressions", "Folder 1": "Legs (walk)", "果冻眼": "Jelly eyes", "头发物理": "Hair physics",
            "衣服物理": "Clothes physics", "衣服物理Y": "Clothes physics Y", "手臂物理": "Arm physics",
            "蝴蝶结物理": "Bow physics", "星星动画": "Star animation", "星星物理": "Star physics",
            "花生动画": "Peanut animation", "表情物理和动画": "Expression physics & animation"}
PART_EN = {"变身星星（补": "Transform stars (fill)", "阿尼亚烟雾和星星.psd": "Anya smoke and stars",
           "小花生 副本": "Small peanut (copy)", "小花生": "Small peanut", "花生": "Peanut", "星星": "Stars",
           "手势": "Hand gesture", "头": "Head", "衣服": "Clothes", "后发（补": "Back hair (fill)",
           "图层组3": "Layer group 3", "烟雾": "Smoke", "左眼": "Left eye", "口腔": "Mouth interior",
           "光芒": "Rays", "白星星": "White stars", "左胳膊": "Left arm", "右胳膊": "Right arm",
           "星星眼": "Star eyes", "前发": "Front hair", "阴影": "Shadow", "耳朵（补": "Ears (fill)",
           "第二季服装": "Season 2 outfit", "校服": "School uniform", "腿": "Legs", "肤色": "Skin",
           "眉毛": "Brows", "眼睛": "Eyes", "睡觉": "Sleeping", "鼻子": "Nose", "哭哭配哭哭嘴": "Crying + crying mouth",
           "嘴巴": "Mouth", "脸": "Face", "标准": "Standard", "无语左眼": "Speechless left eye",
           "也是表情": "Also expressions", "经典表情": "Classic smug face", "荷包蛋哭哭左": "Fried-egg crying eye L",
           "无语": "Speechless", "疑惑": "Confused", "大哭": "Wailing", "哭哭": "Crying", "震惊": "Shocked",
           "配合星星": "With stars", "表情口腔": "Expression mouth", "上睫毛": "Upper lashes",
           "下睫毛": "Lower lashes", "眼珠": "Pupil", "泪": "Tears"}
EXP_EN = {"0": "gesture", "1": "crying", "2": "shocked", "3": "smug", "4": "confused", "5": "star_eyes",
          "6": "angry", "7": "speechless", "8": "startled", "9": "outfit_change", "Q": "zzz", "W": "wailing",
          "t": "peanut", "u": "tiny_pupils", "y": "grin"}
MOTION_EN = {"Scene1": "OutfitChange", "Scene2": "Peanut", "Scene3": "TearsZzz", "zoulu": "Walk"}
# the app's expression names (overlay/rigs/*.toml) -> her reaction face (None = plain face)
APP_EXPRESSIONS = {"neutral": None, "happy": "5", "surprised": "2", "pout": "6", "upset": "1",
                   "sleepy": "Q", "thinking": "4", "focused": "3", "warning": "8"}


def idle_motion() -> dict:
    """A gentle 5 s loop: breath, slight body and head sway (30 fps linear segments)."""
    import math
    dur, fps = 5.0, 30
    curves = {"ParamBreath": lambda t: .5 - .5 * math.cos(2 * math.pi * t / dur),
              "ParamBodyAngleZ": lambda t: 1.5 * math.sin(2 * math.pi * t / dur),
              "ParamAngleZ": lambda t: 2.0 * math.sin(2 * math.pi * (t / dur + .3))}
    out = []
    for pid, f in curves.items():
        seg = [0.0, round(f(0), 4)]
        for i in range(1, int(dur * fps) + 1):
            seg += [0, round(i / fps, 4), round(f(i / fps), 4)]
        seg[-1] = seg[1]
        out.append({"Target": "Parameter", "Id": pid, "Segments": seg})
    n = int(dur * fps)
    return {"Version": 3, "Meta": {"Duration": dur, "Fps": fps, "Loop": True, "AreBeziersRestricted": True,
                                    "FadeInTime": .5, "FadeOutTime": .5, "CurveCount": len(out),
                                    "TotalSegmentCount": n * len(out), "TotalPointCount": (n + 1) * len(out),
                                    "UserDataCount": 0, "TotalUserDataSize": 0}, "Curves": out}


def dump(path: Path, data) -> None:
    # indented: the SDK's JSON parser rejects long one-line motion files
    path.write_text(json.dumps(data, ensure_ascii=False, indent="\t"), encoding="utf-8")


def main() -> None:
    src_model = json.loads((SRC / "ANIYA.model3.json").read_text(encoding="utf-8-sig"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "textures").mkdir(exist_ok=True)
    (OUT / "exp").mkdir(exist_ok=True)
    (OUT / "motions").mkdir(exist_ok=True)
    shutil.copy2(SRC / "ANIYA.moc3", OUT / "aniya.moc3")
    shutil.copy2(SRC / "ANIYA.physics3.json", OUT / "aniya.physics3.json")
    textures = []
    for i, rel in enumerate(src_model["FileReferences"]["Textures"]):
        dst = OUT / "textures" / f"texture_{i:02d}.png"
        if not dst.exists():
            Image.open(SRC / rel).resize((TEX, TEX), Image.Resampling.LANCZOS).save(dst, optimize=True)
        textures.append(f"textures/{dst.name}")

    cdi = json.loads((SRC / "ANIYA.cdi3.json").read_text(encoding="utf-8-sig"))
    rows = ["| ID | Original | English |", "|---|---|---|"]
    for p in cdi["Parameters"]:
        en = PARAM_EN.get(p["Id"], p["Name"])
        rows.append(f"| `{p['Id']}` | {p['Name']} | {en} |")
        p["Name"] = en
    for g in cdi.get("ParameterGroups", []):
        g["Name"] = GROUP_EN.get(g["Name"], g["Name"])
    for p in cdi["Parts"]:
        p["Name"] = PART_EN.get(p["Name"], p["Name"])
    dump(OUT / "aniya.cdi3.json", cdi)

    exps = []
    for key, name in EXP_EN.items():
        data = json.loads((SRC / f"{key}.exp3.json").read_text(encoding="utf-8-sig"))
        dump(OUT / "exp" / f"{name}.exp3.json", data)
        exps.append({"Name": name, "File": f"exp/{name}.exp3.json"})
    for app_name, key in APP_EXPRESSIONS.items():
        data = (json.loads((SRC / f"{key}.exp3.json").read_text(encoding="utf-8-sig")) if key else
                {"Type": "Live2D Expression", "FadeInTime": .5, "FadeOutTime": .5, "Parameters": []})
        data["Parameters"] = [p for p in data["Parameters"] if p["Id"] != "ParamMouthOpenY"]  # lip sync owns it
        dump(OUT / "exp" / f"{app_name}.exp3.json", data)
        exps.append({"Name": app_name, "File": f"exp/{app_name}.exp3.json"})

    motions = {"Idle": [{"File": "motions/Idle.motion3.json"}]}
    dump(OUT / "motions" / "Idle.motion3.json", idle_motion())
    for key, name in MOTION_EN.items():
        dump(OUT / "motions" / f"{name}.motion3.json",
             json.loads((SRC / f"{key}.motion3.json").read_text(encoding="utf-8-sig")))
        motions[name] = [{"File": f"motions/{name}.motion3.json"}]

    model = {"Version": 3,
             "FileReferences": {"Moc": "aniya.moc3", "Textures": textures, "Physics": "aniya.physics3.json",
                                "DisplayInfo": "aniya.cdi3.json", "Expressions": exps, "Motions": motions},
             "Groups": [{"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
                        {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]}]}
    dump(OUT / "aniya.model3.json", model)
    exp_rows = ["| File | Original (VTube Studio hotkey) | English name |", "|---|---|---|"]
    exp_rows += [f"| {k}.exp3.json | {k} | {v} |" for k, v in EXP_EN.items()]
    (OUT / "TRANSLATION.md").write_text(
        "# ANIYA model: translated names\n\nArt & rig: DG_studio. Personal use only; no for-profit streaming, "
        "no redistribution (see the original Instructions.txt).\n\n## Parameters\n\n" + "\n".join(rows) +
        "\n\n## Expressions\n\n" + "\n".join(exp_rows) +
        "\n\nApp expressions: " + ", ".join(f"{a} = {EXP_EN[k] if k else 'plain'}" for a, k in APP_EXPRESSIONS.items()) +
        "\n\n## Motions\n\n" + "\n".join(f"- {k}.motion3.json → {v}" for k, v in MOTION_EN.items()) +
        "\n- Idle.motion3.json: new, gentle breath/sway\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "textures": len(textures), "expressions": len(exps), "motions": list(motions)}))


if __name__ == "__main__":
    main()
