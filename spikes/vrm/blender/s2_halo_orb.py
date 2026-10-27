"""Step 2: the golden sunburst halo and the cyan orb, each on its own new bone.

- `Halo` bone (child of the head): gold ring, thin inner ring, 24 spikes in three lengths,
  8 red gems. It sits behind the head, facing the camera.
- `Orb` bone (child of the upper chest): emissive cyan core and a translucent glow shell,
  floating in front of her chest.
- Custom expressions: `ringGlow` (halo emission up), `haloAmber` (warning colour),
  `orbFlare` (orb brighter).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import rlib  # noqa: E402

P = rlib.PALETTE
HEAD, CHEST = "J_Bip_C_Head", "J_Bip_C_UpperChest"


def _torus(bm, major, minor, seg=64, ring=10, y=0.0):
    """Torus lying in the XZ plane (facing -Y, the model's front in Blender)."""
    out = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        for j in range(ring):
            b = 2 * math.pi * j / ring
            r = major + minor * math.cos(b)
            out.append(bm.verts.new((r * math.cos(a), y + minor * math.sin(b), r * math.sin(a))))
    for i in range(seg):
        for j in range(ring):
            q = [out[(i * ring + j)], out[(((i + 1) % seg) * ring + j)],
                 out[(((i + 1) % seg) * ring + (j + 1) % ring)], out[(i * ring + (j + 1) % ring)]]
            bm.faces.new(q)


def _spike(bm, angle, r0, length, width, thick=0.006):
    """A flat diamond blade pointing outwards from radius r0."""
    d = Vector((math.cos(angle), 0, math.sin(angle)))
    s = Vector((-math.sin(angle), 0, math.cos(angle)))
    t = Vector((0, thick, 0))
    base, mid, tip = d * r0, d * (r0 + length * 0.22), d * (r0 + length)
    v = [bm.verts.new(p) for p in (base, mid + s * width, tip, mid - s * width, mid + t, mid - t)]
    b, l, tp, r, f, k = v
    for tri in ((b, l, f), (l, tp, f), (tp, r, f), (r, b, f), (l, b, k), (tp, l, k), (r, tp, k), (b, r, k)):
        bm.faces.new(tri)


def build_halo(arm, scale=1.0, dim=False):
    head = rlib.bone_head(arm, HEAD)
    top = rlib.bone_head(arm, "J_Bip_C_Head_end") if "J_Bip_C_Head_end" in arm.data.bones else head + Vector((0, 0, 0.2))
    centre = head.lerp(top, 0.55) + Vector((0, 0.2 * scale, 0))
    R = 0.19 * scale

    bm = bmesh.new()
    _torus(bm, R, 0.012 * scale)
    _torus(bm, R * 0.8, 0.005 * scale, ring=6)
    for i in range(24):
        a = 2 * math.pi * i / 24 + math.pi / 2
        length = (0.20 if i % 6 == 0 else 0.11 if i % 2 == 0 else 0.06) * scale
        _spike(bm, a, R + 0.01 * scale, length, (0.022 if i % 6 == 0 else 0.014) * scale)
    gold_faces = len(bm.faces)
    for i in range(8):
        a = 2 * math.pi * i / 8 + math.pi / 2
        c = Vector((R * math.cos(a), -0.012 * scale, R * math.sin(a)))
        g = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.016 * scale)
        bmesh.ops.translate(bm, verts=g["verts"], vec=c)
    me = bpy.data.meshes.new("Halo")
    bm.to_mesh(me)
    bm.free()
    halo = rlib.link(bpy.data.objects.new("Halo", me))
    gold = rlib.toon_material("Halo_Gold", P["gold"], "#9C7A2E", P["gold"], 0.15 if dim else 0.35)
    gem = rlib.toon_material("Halo_Gem", P["gem"], "#7A1A14", P["gem"], 0.3)
    me.materials.append(gold)
    me.materials.append(gem)
    for f in me.polygons:
        f.material_index = 0 if f.index < gold_faces else 1
        f.use_smooth = True
    me.transform(Matrix.Translation(centre))

    bone = rlib.add_bone(arm, "Halo", HEAD, centre, centre + Vector((0, 0, 0.1 * scale)))
    rlib.skin_to_bone(halo, arm, bone)
    return halo, gold, gem


def build_orb(arm, scale=1.0, offset=None):
    chest = rlib.bone_head(arm, CHEST)
    centre = chest + (offset or Vector((0, -0.26, 0.02))) * scale
    me_core = bpy.data.meshes.new("Orb")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.03 * scale)
    bm.to_mesh(me_core)
    bm.free()
    orb = rlib.link(bpy.data.objects.new("Orb", me_core))
    core = rlib.toon_material("Orb_Core", "#E8FBFF", P["cyan"], P["cyan"], 1.0)
    rlib.assign(orb, core)
    for f in me_core.polygons:
        f.use_smooth = True
    me_core.transform(Matrix.Translation(centre))

    me_shell = bpy.data.meshes.new("OrbGlow")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.046 * scale)
    bm.to_mesh(me_shell)
    bm.free()
    shell = rlib.link(bpy.data.objects.new("OrbGlow", me_shell))
    glow = rlib.toon_material("Orb_Glow", P["cyan"], "#8A6CFF", P["cyan"], 0.8, alpha=0.28)
    rlib.assign(shell, glow)
    for f in me_shell.polygons:
        f.use_smooth = True
    me_shell.transform(Matrix.Translation(centre))

    bone = rlib.add_bone(arm, "Orb", CHEST, centre, centre + Vector((0, 0, 0.08 * scale)))
    rlib.skin_to_bone(orb, arm, bone)
    rlib.skin_to_bone(shell, arm, bone)
    return core, glow


def custom_expression(arm, name):
    ex = rlib.ext(arm).vrm1.expressions
    e = next((c for c in ex.custom if c.custom_name == name), None) or ex.custom.add()
    e.custom_name = name
    return e


def color_bind(expr, mat, kind, rgba):
    b = expr.material_color_binds.add()
    b.material = mat
    b.type = kind
    b.target_value = rgba


def run(scale=1.0, dim=False, orb_offset=None):
    arm = rlib.armature()
    _, gold, gem = build_halo(arm, scale, dim)
    core, glow = build_orb(arm, scale, orb_offset)
    color_bind(custom_expression(arm, "ringGlow"), gold, "emissionColor", (1.0, 0.82, 0.42, 1.0))
    amber = custom_expression(arm, "haloAmber")
    color_bind(amber, gold, "color", (*rlib.lin("#FF9A2E"), 1.0))
    color_bind(amber, gold, "emissionColor", (1.0, 0.45, 0.05, 1.0))
    color_bind(custom_expression(arm, "orbFlare"), glow, "color", (*rlib.lin(P["cyan"]), 0.6))
    print("RAPHAEL halo + orb done")


if __name__ == "__main__":
    a = rlib.args()
    rlib.load_vrm(a[0] if a else rlib.EXPORT + "raphael_s1_recolour.vrm")
    run()
    rlib.export(a[1] if len(a) > 1 else "raphael_s2_halo")
