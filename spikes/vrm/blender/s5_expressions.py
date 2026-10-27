"""Step 5: her 9 expressions (docs/character.md → Required coverage) as VRM expressions.

Presets are rebound where one fits (neutral, happy, surprised, sad = upset); the rest are
custom expressions mixed from the base's VRoid face keys (Fcl_BRW_*, Fcl_EYE_*, Fcl_MTH_*).
Material binds add the halo and eye glow: `eyeGlow` (serious form) and the amber halo in
`warning`. The overlay maps her mood names to these:

    neutral   -> neutral      happy    -> happy     surprised -> surprised
    pout      -> pout         upset    -> sad       sleepy    -> sleepy
    thinking  -> thinking     focused  -> focused   warning   -> warning
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bpy  # noqa: E402

import rlib  # noqa: E402
import s2_halo_orb  # noqa: E402

K = "Face_Blendshape.Fcl_"
MIX = {
    # calm and half-lidded, mouth small: her quietly composed default
    "neutral": {"EYE_Close": 0.22, "MTH_Small": 0.3},
    "happy": {"BRW_Fun": 0.7, "EYE_Fun": 0.55, "MTH_Fun": 0.75},
    "surprised": {"BRW_Surprised": 1.0, "EYE_Surprised": 0.8, "MTH_Surprised": 0.55},
    "sad": {"BRW_Sorrow": 1.0, "EYE_Sorrow": 0.7, "MTH_Sorrow": 0.6},
    "pout": {"MTH_U": 0.85, "MTH_Angry": 0.3, "MTH_Small": 0.5, "BRW_Angry": 0.55, "EYE_Close": 0.2},
    "sleepy": {"EYE_Close": 0.72, "BRW_Sorrow": 0.3, "MTH_A": 0.12},
    "thinking": {"EYE_Close_R": 0.35, "EYE_Close": 0.15, "BRW_Angry": 0.3, "BRW_Sorrow": 0.25, "MTH_Small": 0.5, "MTH_Down": 0.5},
    "focused": {"EYE_Angry": 0.6, "BRW_Angry": 0.55, "MTH_Close": 0.6, "MTH_Small": 0.3},
    "warning": {"BRW_Angry": 0.85, "EYE_Angry": 0.5, "MTH_Angry": 0.4},
}
CHIBI = {
    # chibi gag face: blank eyes and a triangle-ish mouth
    "surprised": {"BRW_Surprised": 1.0, "EYE_Surprised": 1.0, "EYE_IrisHide": 1.0, "MTH_O": 0.5, "MTH_Small": 0.4},
}
PRESET = {"neutral", "happy", "surprised", "sad"}
BLOCK_BLINK = {"sleepy", "surprised", "happy"}


def expression(arm, name):
    ex = rlib.ext(arm).vrm1.expressions
    if name in PRESET:
        return ex.preset.name_to_expression_dict()[name]
    return s2_halo_orb.custom_expression(arm, name)


def run(chibi=False):
    arm = rlib.armature()
    face = bpy.data.objects["Face"]
    keys = face.data.shape_keys.key_blocks
    mixes = {**MIX, **(CHIBI if chibi else {})}
    for name, mix in mixes.items():
        e = expression(arm, name)
        e.morph_target_binds.clear()
        for k, w in mix.items():
            assert K + k in keys, k
            b = e.morph_target_binds.add()
            b.node.mesh_object_name = face.name
            b.index = K + k
            b.weight = w
        if name in BLOCK_BLINK:
            e.override_blink = "block"
        if name in ("pout", "sad"):
            e.override_mouth = "blend"
    mats = bpy.data.materials
    iris = mats["EyeIris_00_EYE"]
    s2_halo_orb.color_bind(expression(arm, "eyeGlow"), iris, "emissionColor", (1.0, 0.25, 0.3, 1.0))
    if "Halo_Gold" in mats:
        w = expression(arm, "warning")
        s2_halo_orb.color_bind(w, mats["Halo_Gold"], "color", (*rlib.lin("#FF9A2E"), 1.0))
        s2_halo_orb.color_bind(w, mats["Halo_Gold"], "emissionColor", (1.0, 0.45, 0.05, 1.0))
    print(f"RAPHAEL expressions done ({len(mixes)} mixes, chibi={chibi})")
