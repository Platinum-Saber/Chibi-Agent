extends Node3D
## Optional attachment: set skeleton_path and the actual Head bone name.
@export_node_path("Skeleton3D") var skeleton_path: NodePath
@export var head_bone: StringName = &"J_Bip_C_Head"
@export var mount_adjustment: Transform3D = Transform3D.IDENTITY
@export var microphone_visible: bool = true
var _skeleton: Skeleton3D
var _head: int = -1

func _ready() -> void:
 process_priority = 20
 if not skeleton_path.is_empty():
  _skeleton = get_node_or_null(skeleton_path) as Skeleton3D
  if _skeleton:
   _head = _skeleton.find_bone(head_bone)
 var mic := find_child("Microphone_Boom", true, false) as Node3D
 if mic:
  mic.visible = microphone_visible

func _process(_delta: float) -> void:
 if is_instance_valid(_skeleton) and _head >= 0:
  var rest := _skeleton.get_bone_global_rest(_head)
  var baseline := Transform3D(Basis.IDENTITY, rest.origin)
  global_transform = _skeleton.global_transform * _skeleton.get_bone_global_pose(_head) * rest.affine_inverse() * baseline * mount_adjustment
