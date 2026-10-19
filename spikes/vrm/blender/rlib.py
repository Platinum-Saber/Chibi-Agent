"""Shared helpers for the Raphael build scripts (run inside Blender).

Colours are sRGB hex from docs/character.md → Palette. Image pixels of byte textures are
stored sRGB, so texture maths happens in sRGB; MToon factors are linear.
"""
import math
import sys

import addon_utils
import bpy
import numpy as np

DATA = "D:\\Projects\\Chibi-Agent-Project\\ChibiAgent\\3d\\"  # outside the repo, never in git
SAMPLES = DATA + "samples\\"
EXPORT = DATA + "export\\"
BLEND = DATA + "blend\\"
BASE = SAMPLES + "VRM1_Constraint_Twist_Sample.vrm"

PALETTE = {
    "hair_light": "#A8DDF5", "hair_mid": "#6CC0EC", "hair_shadow": "#3E8FD6",
    "ruby": "#D4243A", "ruby_rim": "#8E1426",
    "skin": "#FBE6DA", "white": "#FAFBFF", "cloth_shadow": "#C8D0E4",
    "gold": "#D8B45A", "gem": "#C8372D", "cyan": "#7FE3FF", "ink": "#2B2F3A",
}


def args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def srgb(hexcode):
    h = hexcode.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def lin(hexcode):
    c = srgb(hexcode)
    return tuple(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)  # unloads add-ons, so enable after it
    addon_utils.enable("bl_ext.system.vrm", default_set=True)


def load_vrm(path=BASE):
    fresh()
    bpy.ops.import_scene.vrm(filepath=path)
    return armature()


def armature():
    return next(o for o in bpy.data.objects if o.type == "ARMATURE")


def ext(arm=None):
    return (arm or armature()).data.vrm_addon_extension


def mtoon(mat):
    return mat.vrm_addon_extension.mtoon1


def export(name, arm=None):
    arm = arm or armature()
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND + name + ".blend")
    out = EXPORT + name + ".vrm"
    bpy.ops.export_scene.vrm(filepath=out, armature_object_name=arm.name)
    print(f"RAPHAEL exported {out}")
    return out


# --- textures -------------------------------------------------------------------------

def pixels(img):
    a = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(-1, 4)


def set_pixels(img, px):
    img.pixels.foreach_set(px.astype(np.float32).ravel())
    img.update()
    img.pack()


def gradient_map(img, stops, lo_hi=(2, 98), mask=None):
    """Replace colour by a ramp over normalised luminance; keeps alpha.

    stops: [(t, hex), ...] with t in 0..1, dark to light.
    """
    px = pixels(img)
    lum = px[:, :3] @ np.array([0.299, 0.587, 0.114])
    sel = px[:, 3] > 0.01 if mask is None else mask
    lo, hi = np.percentile(lum[sel], lo_hi)
    t = np.clip((lum - lo) / max(hi - lo, 1e-4), 0, 1)
    ts = np.array([s[0] for s in stops])
    cols = np.array([srgb(s[1]) for s in stops])
    for ch in range(3):
        px[sel, ch] = np.interp(t[sel], ts, cols[:, ch])
    set_pixels(img, px)


# --- bones and meshes -----------------------------------------------------------------

def add_bone(arm, name, parent, head, tail):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones.new(name)
    eb.head, eb.tail = head, tail
    eb.parent = arm.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return name


def bone_head(arm, name):
    return arm.matrix_world @ arm.data.bones[name].head_local


def skin_to_bone(obj, arm, bone):
    """Rigidly bind obj to one bone (vertex group + armature modifier, as VRM expects)."""
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    vg = obj.vertex_groups.new(name=bone)
    vg.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def toon_material(name, base_hex, shade_hex=None, emissive_hex=None, emissive=0.0, alpha=None):
    """A plain MToon material set up through the VRM add-on's property groups."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mt = mtoon(mat)
    mt.enabled = True
    mt.pbr_metallic_roughness.base_color_factor = (*lin(base_hex), alpha if alpha is not None else 1.0)
    ext_ = mt.extensions.vrmc_materials_mtoon
    ext_.shade_color_factor = lin(shade_hex or base_hex)
    if emissive_hex:
        mt.emissive_factor = tuple(min(1.0, c * max(emissive, 0)) for c in lin(emissive_hex))
    if alpha is not None:
        mt.alpha_mode = "BLEND"
    return mat


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def mesh_from(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    return link(bpy.data.objects.new(name, me))


def ring_verts(r, z, n, y=0.0, phase=0.0):
    return [(r * math.cos(2 * math.pi * i / n + phase), y, z + r * math.sin(2 * math.pi * i / n + phase)) for i in range(n)]
