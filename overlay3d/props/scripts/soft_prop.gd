@tool
extends Node3D
## Pose targets are exclusive; Pillow_Dent is independent.
const COVERS: Array[StringName] = [&"Occupied", &"Cover_Front", &"Cover_Side", &"Cover_SitUp", &"Folded_Back"]
@export_enum("Flat", "Occupied", "Cover_Front", "Cover_Side", "Cover_SitUp", "Folded_Back") var cover: String = "Flat":
 set(value):
  cover = value
  if is_inside_tree(): set_cover(StringName(value))
@export_range(0.0, 1.0) var pillow_dent: float = 0.0:
 set(value):
  pillow_dent = clampf(value, 0.0, 1.0)
  if is_inside_tree(): set_shape(&"Pillow_Dent", pillow_dent)
@export_range(0.0, 1.0) var occupied: float = 0.0:
 set(value):
  occupied = clampf(value, 0.0, 1.0)
  if is_inside_tree(): set_occupied(occupied)

func _ready() -> void:
 if cover == "Flat" and occupied > 0.0: set_occupied(occupied)
 else: set_cover(StringName(cover))
 set_shape(&"Pillow_Dent", pillow_dent)

func set_shape(shape_name: StringName, weight: float) -> int:
 return _apply_shape(self, shape_name, clampf(weight, 0.0, 1.0))

func set_cover(shape_name: StringName, weight: float = 1.0) -> void:
 for key in COVERS:
  set_shape(key, weight if key == shape_name else 0.0)

func set_occupied(weight: float) -> void:
 set_cover(&"Occupied", weight)

func _apply_shape(node: Node, shape_name: StringName, weight: float) -> int:
 var count := 0
 if node is MeshInstance3D and node.mesh:
  for i in node.mesh.get_blend_shape_count():
   if node.mesh.get_blend_shape_name(i) == shape_name:
    node.set_blend_shape_value(i, weight)
    count += 1
 for child in node.get_children(): count += _apply_shape(child, shape_name, weight)
 return count
