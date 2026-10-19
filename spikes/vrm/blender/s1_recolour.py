"""Step 1: recolour the base. Hair and brows to the palette blues, irises to ruby.

Works on the base's own textures with a luminance gradient map, so the painted strands,
shading and highlights survive. Run as a module from build.py, or alone:

    X:\\Blender\\blender.exe -b --factory-startup --python spikes/vrm/blender/s1_recolour.py -- [IN.vrm] [NAME]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bpy  # noqa: E402
import rlib  # noqa: E402

P = rlib.PALETTE
# weighted towards the light end: the reference reads as pale sky-blue, MToon shading darkens it
HAIR = [(0.0, P["hair_shadow"]), (0.30, P["hair_mid"]), (0.70, P["hair_light"]), (1.0, "#D8F1FC")]
BROW = [(0.0, "#1E3C78"), (1.0, P["hair_shadow"])]
LASH = [(0.0, P["ink"]), (1.0, "#4A5470")]  # eyeline stays dark, with a cool tint
# iris: near-black pupil -> rim -> ruby -> pale highlight
IRIS = [(0.0, "#2A0408"), (0.30, P["ruby_rim"]), (0.62, P["ruby"]), (0.88, "#FF6A6F"), (1.0, "#FFC4C4")]


def run():
    img = bpy.data.images
    for name in ("Hair_00", "HairBack_00"):
        rlib.gradient_map(img[name], HAIR)
    rlib.gradient_map(img["FaceBrow_00"], BROW)
    rlib.gradient_map(img["FaceEyeline_00"], LASH)
    # only the iris disc, not the black background around it
    px = rlib.pixels(img["EyeIris_00"])
    rlib.gradient_map(img["EyeIris_00"], IRIS, lo_hi=(1, 99.5), mask=px[:, :3].max(1) > 0.03)
    # hair shadows lean deeper blue instead of grey
    for m in ("Hair_00_HAIR", "HairBack_00_HAIR"):
        mt = rlib.mtoon(bpy.data.materials[m]).extensions.vrmc_materials_mtoon
        mt.shade_color_factor = rlib.lin("#B4CCF4")
        rim = rlib.lin(P["hair_light"])
        mt.parametric_rim_color_factor = tuple(c * 0.35 for c in rim)
    # skin shade: softer pink, closer to the palette's pale skin
    for m in ("Body_00_SKIN", "Face_00_SKIN"):
        rlib.mtoon(bpy.data.materials[m]).extensions.vrmc_materials_mtoon.shade_color_factor = rlib.lin("#F2C4C0")
    print("RAPHAEL recolour done")


if __name__ == "__main__":
    a = rlib.args()
    rlib.load_vrm(a[0] if a else rlib.BASE)
    run()
    rlib.export(a[1] if len(a) > 1 else "raphael_s1_recolour")
