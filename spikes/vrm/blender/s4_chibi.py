"""Step 4: chibi proportions (about 2.5 heads) from the full-size base.

1. Pose-scale the humanoid bones: head up, neck/torso/limbs shorter (each bone gets only
   its own scale; inherit_scale is off along the J_Bip chain, so the hair, eyes and halo
   still follow the head's scale).
2. Bake that pose into every skinned mesh, shape keys included (each key is evaluated
   alone and written back), then apply the pose as the new rest pose.
3. Rescale spring-bone colliders, joint hit radii and the lookAt offset to match.

Run before s3_robe so the robe and hood are fitted to the chibi body.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import rlib  # noqa: E402

# bone -> (x, y, z) pose scale in bone space (y runs along the bone)
SCALE = {
    "J_Bip_C_Head": (1.75, 1.75, 1.75),
    "J_Bip_C_Neck": (0.8, 0.35, 0.8),
    "J_Bip_C_UpperChest": (0.72, 0.55, 0.78),
    "J_Bip_C_Chest": (0.72, 0.55, 0.78),
    "J_Bip_C_Spine": (0.72, 0.55, 0.78),
    "J_Bip_C_Hips": (0.75, 0.6, 0.78),
    "J_Bip_L_Shoulder": (0.7, 0.6, 0.7), "J_Bip_R_Shoulder": (0.7, 0.6, 0.7),
    "J_Bip_L_UpperArm": (0.75, 0.5, 0.75), "J_Bip_R_UpperArm": (0.75, 0.5, 0.75),
    "J_Bip_L_LowerArm": (0.75, 0.5, 0.75), "J_Bip_R_LowerArm": (0.75, 0.5, 0.75),
    "J_Bip_L_Hand": (0.8, 0.8, 0.8), "J_Bip_R_Hand": (0.8, 0.8, 0.8),
    "J_Bip_L_UpperLeg": (0.8, 0.4, 0.8), "J_Bip_R_UpperLeg": (0.8, 0.4, 0.8),
    "J_Bip_L_LowerLeg": (0.8, 0.4, 0.8), "J_Bip_R_LowerLeg": (0.8, 0.4, 0.8),
    "J_Bip_L_Foot": (0.75, 0.75, 0.75), "J_Bip_R_Foot": (0.75, 0.75, 0.75),
    # halo: smaller relative to the bigger head; orb: keep its size
    "Halo": (0.72, 0.72, 0.72),
    "Orb": (0.8, 0.8, 0.8),
}
NO_INHERIT = set(SCALE) - {"J_Bip_C_Hips", "Halo"}


def world_scale(arm, name):
    """The bone's total scale in the pose, per local axis, for rescaling spring data."""
    m = arm.pose.bones[name].matrix @ arm.data.bones[name].matrix_local.inverted()
    return np.array(m.to_scale())


def bake_pose(arm):
    dg = bpy.context.evaluated_depsgraph_get()
    for obj in [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]:
        keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
        saved = [k.value for k in keys]
        for k in keys:
            k.value = 0.0
        dg.update()
        n = len(obj.data.vertices)

        def evaluated():
            ev = obj.evaluated_get(dg)
            co = np.empty(n * 3)
            ev.data.vertices.foreach_get("co", co)
            return co

        base = evaluated()
        new = {}
        for k in list(keys)[1:]:
            k.value = 1.0
            dg.update()
            new[k.name] = evaluated()
            k.value = 0.0
        obj.data.vertices.foreach_set("co", base)
        if keys:
            keys[0].data.foreach_set("co", base)
            for k in list(keys)[1:]:
                k.data.foreach_set("co", new[k.name])
        for k, v in zip(keys, saved):
            k.value = v
        obj.data.update()


def ground(arm):
    """Shorter legs leave her floating: move bones and meshes down so her soles touch z=0."""
    dz = min(v.co.z for v in bpy.data.objects["Body"].data.vertices)
    # one transform for the whole armature: moving connected edit bones one by one shifts
    # each chain twice (a child's head is its parent's tail)
    arm.data.transform(Matrix.Translation((0, 0, -dz)))
    for obj in [o for o in bpy.data.objects if o.type == "MESH"]:
        blocks = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
        for data in [obj.data.vertices] + [k.data for k in blocks]:
            co = np.empty(len(data) * 3)
            data.foreach_get("co", co)
            co[2::3] -= dz
            data.foreach_set("co", co)
        obj.data.update()


def run():
    arm = rlib.armature()
    sb = rlib.ext(arm).spring_bone1
    before = []
    for c in sb.colliders:
        sh = c.shape
        before.append((c, c.node.bone_name, c.shape_type if hasattr(c, "shape_type") else None,
                       tuple(sh.sphere.offset), sh.sphere.radius,
                       tuple(sh.capsule.offset), tuple(sh.capsule.tail), sh.capsule.radius))
    joints = [(j, j.node.bone_name, j.hit_radius) for s in sb.springs for j in s.joints]
    look = rlib.ext(arm).vrm1.look_at
    look_off = Vector(look.offset_from_head_bone)

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for name, s in SCALE.items():
        pb = arm.pose.bones.get(name)
        if not pb:
            continue
        pb.scale = s
        if name in NO_INHERIT:
            arm.data.bones[name].inherit_scale = "NONE"
    bpy.context.view_layer.update()
    scales = {b.name: world_scale(arm, b.name) for b in arm.data.bones}
    bpy.ops.object.mode_set(mode="OBJECT")

    bake_pose(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for b in arm.data.bones:
        b.inherit_scale = "FULL"

    for c, bone, _, s_off, s_r, c_off, c_tail, c_r in before:
        k = scales.get(bone, np.ones(3))
        c.shape.sphere.offset = tuple(np.array(s_off) * k)
        c.shape.sphere.radius = s_r * float(k.mean())
        c.shape.capsule.offset = tuple(np.array(c_off) * k)
        c.shape.capsule.tail = tuple(np.array(c_tail) * k)
        c.shape.capsule.radius = c_r * float(k.mean())
    for j, bone, r in joints:
        j.hit_radius = r * float(scales.get(bone, np.ones(3)).mean())
    look.offset_from_head_bone = tuple(look_off * float(scales["J_Bip_C_Head"].mean()))

    ground(arm)
    feet = min(v.co.z for v in bpy.data.objects["Body"].data.vertices)
    head_top = max((arm.matrix_world @ v.co).z for v in bpy.data.objects["Hair"].data.vertices)
    chin = rlib.bone_head(arm, "J_Bip_C_Neck").z + 0.0
    print(f"RAPHAEL chibi height={head_top - feet:.3f} m head={head_top - chin:.3f} m "
          f"heads_tall={(head_top - feet) / (head_top - chin):.2f}")
