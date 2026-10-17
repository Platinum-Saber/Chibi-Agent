"""Smoke test: import a VRM, report its rig, export it again.

    X:\\Blender\\blender.exe -b --factory-startup --python spikes/vrm/blender/roundtrip.py -- IN.vrm OUT.vrm

The VRM add-on lives in Blender's System extensions (X:\\Blender\\5.2\\extensions\\system\\vrm),
so headless runs enable it here instead of relying on user preferences.
"""
import sys

import addon_utils
import bpy

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)  # unloads add-ons, so enable after it
addon_utils.enable("bl_ext.system.vrm", default_set=True)
bpy.ops.import_scene.vrm(filepath=src)

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
keys = sorted({k.name for o in meshes if o.data.shape_keys for k in o.data.shape_keys.key_blocks})
human = arm.data.vrm_addon_extension.vrm1.humanoid.human_bones
print(f"ROUNDTRIP armature={arm.name} bones={len(arm.data.bones)} meshes={len(meshes)} shape_keys={len(keys)}")
print(f"ROUNDTRIP head bone={human.head.node.bone_name} hips={human.hips.node.bone_name}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.vrm(filepath=dst)
print(f"ROUNDTRIP exported {dst}")
