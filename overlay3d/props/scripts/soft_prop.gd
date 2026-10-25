@tool
extends Node3D
## Visual squash or blanket lift. Support collision stays fixed.
@export_range(0.0, 1.0) var occupied: float = 0.0:
 set(value):
  occupied = clampf(value, 0.0, 1.0)
  if is_inside_tree():
   _apply(self)

func _ready() -> void:
 _apply(self)

func set_occupied(weight: float) -> void:
 occupied = weight

func _apply(node: Node) -> void:
 if node is MeshInstance3D and node.mesh:
  for i in node.mesh.get_blend_shape_count():
   if node.mesh.get_blend_shape_name(i) == &"Occupied":
    node.set_blend_shape_value(i, occupied)
 for child in node.get_children():
  _apply(child)
