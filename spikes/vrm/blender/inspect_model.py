"""Print a VRM's meshes, materials, textures, expressions and spring bones.

    X:\Blender\blender.exe -b --factory-startup --python spikes/vrm/blender/inspect_model.py -- IN.vrm
"""
import sys

import addon_utils
import bpy

src = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("bl_ext.system.vrm", default_set=True)
bpy.ops.import_scene.vrm(filepath=src)

for o in bpy.data.objects:
    if o.type == "MESH":
        print(f"MESH {o.name} verts={len(o.data.vertices)} mats={[m.name for m in o.data.materials]}")
        if o.data.shape_keys:
            print("  KEYS", [k.name for k in o.data.shape_keys.key_blocks])
for m in bpy.data.materials:
    mt = m.vrm_addon_extension.mtoon1
    tex = mt.pbr_metallic_roughness.base_color_texture.index.source
    sh = mt.extensions.vrmc_materials_mtoon.shade_multiply_texture.index.source
    print(f"MAT {m.name} base={tuple(round(c,3) for c in mt.pbr_metallic_roughness.base_color_factor)} "
          f"tex={tex.name if tex else None} shade={tuple(round(c,3) for c in mt.extensions.vrmc_materials_mtoon.shade_color_factor)} "
          f"shadetex={sh.name if sh else None} alpha={mt.alpha_mode}")
for i in bpy.data.images:
    print(f"IMG {i.name} {i.size[0]}x{i.size[1]}")
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
ext = arm.data.vrm_addon_extension
ex = ext.vrm1.expressions
for name, e in ex.preset.name_to_expression_dict().items():
    binds = [(b.node.mesh_object_name, b.index, round(b.weight, 2)) for b in e.morph_target_binds]
    print(f"EXPR {name} {binds} mats={len(e.material_color_binds)}+{len(e.texture_transform_binds)}")
for e in ex.custom:
    print(f"CUSTOM {e.custom_name}")
sb = ext.spring_bone1
print(f"SPRING springs={len(sb.springs)} colliders={len(sb.colliders)} groups={len(sb.collider_groups)}")
for s in sb.springs:
    print(f"  SPRING {s.vrm_name} joints={[j.node.bone_name for j in s.joints][:3]}... n={len(s.joints)}")
print("BONES", [b.name for b in arm.data.bones if not b.name.startswith("J_Sec")])
