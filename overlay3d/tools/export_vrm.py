"""Export full-size Raphael from Kryo's Blender master to VRM for the Godot viewer.

    X:\\Blender\\blender.exe -b SRC.blend --python overlay3d/tools/export_vrm.py -- OUT.vrm [--exclude NAME ...]

SRC is `D:\\Character Design\\output\\3d\\teen\\vrm-appearance\\v01\\source\\Raphael_VRM_Appearance_v01.blend`
(or one of its checkpoints). The .blend is never saved: the other scenes and the excluded
objects (by default the hidden swap-fit guide) are removed in memory only. After the export
the VRM is imported again in a fresh session and its contents are printed, so the run
doubles as the export check.
"""
import sys

import addon_utils
import bpy

SCENE = "01_VRM_Appearance"
ARMATURE = "Armature"

argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]
exclude = argv[argv.index("--exclude") + 1:] if "--exclude" in argv else ["SwapFit_CoveredBase"]
src = bpy.data.filepath

addon_utils.enable("bl_ext.system.vrm", default_set=True)

keep = bpy.data.scenes[SCENE]
for sc in list(bpy.data.scenes):
    if sc != keep:
        bpy.data.scenes.remove(sc)
for name in exclude:
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj)
        print(f"RAPHAEL3D excluded {name}")
    else:
        print(f"RAPHAEL3D exclude: no object {name}")

bpy.ops.export_scene.vrm(filepath=out, armature_object_name=ARMATURE)
print(f"RAPHAEL3D exported {out} from {src}")

# Check: what a fresh import of the file actually contains.
bpy.ops.wm.read_factory_settings(use_empty=True)  # unloads add-ons, so enable after it
addon_utils.enable("bl_ext.system.vrm", default_set=True)
bpy.ops.import_scene.vrm(filepath=out)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
v0 = arm.data.vrm_addon_extension.vrm0
meshes = sorted(o.name for o in bpy.data.objects if o.type == "MESH")
top = max((o.matrix_world @ v.co).z for o in bpy.data.objects if o.type == "MESH" for v in o.data.vertices)
low = min((o.matrix_world @ v.co).z for o in bpy.data.objects if o.type == "MESH" for v in o.data.vertices)
print(f"RAPHAEL3D check bones={len(arm.data.bones)} meshes={len(meshes)} height_m={top - low:.4f}")
print(f"RAPHAEL3D check expressions={len(v0.blend_shape_master.blend_shape_groups)} "
      f"spring_groups={len(v0.secondary_animation.bone_groups)}")
print("RAPHAEL3D check mesh names: " + ", ".join(meshes))
