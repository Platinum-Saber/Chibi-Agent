extends Node
## Her props (props/, from Character Design's Raphael_Props_v01): shown only while they're used.
##
## Headset: on for slow music (the DanceVibe clip, no mic) and for a conversation (listening,
## thinking, talking, mouth moving; with the mic), off 5 s after both end. Not for DanceExcited.
## Beanbag: appears under her while she sits (Sit) and squashes as she settles.
## Futon: appears under her while she sleeps (Sleep), laid along her body, blanket raised.
## They pop in and out by scale; the headset follows her Head bone (props/scripts/
## headphone_attachment.gd), the furniture sits on the floor under her (children of the model,
## so they move and turn with her). Clicks pass through them: the hull is her bones only.

const HEADSET := preload("res://props/scenes/headphones.tscn")
const BEANBAG := preload("res://props/scenes/slime_beanbag.tscn")
const FUTON := preload("res://props/scenes/futon.tscn")
const HEADSET_OFF_AFTER := 5.0  # s after the music or the conversation ends
const POP := 0.2  # s to pop a prop in or out
const SETTLE := 0.4  # s for the beanbag to squash as she sits
const BEANBAG_BACK := 0.15  # m behind her feet: hips on the seat, legs over its front
const PILLOW_FROM_CENTRE := 0.635  # futon: Pillow_Surface along -Z from its centre

var body: Node
var model: Node3D
var skeleton: Skeleton3D
var headset: Node3D
var beanbag: Node3D
var futon: Node3D
var _mic: Node3D
var _t := 0.0
var _headset_until := -INF
var _shown := {}  # prop -> 0..1 popped in
var _settle := 0.0


func attach(b: Node) -> void:
	body = b
	model = b.model
	skeleton = b.skeleton
	headset = HEADSET.instantiate()
	headset.set("head_bone", &"Head")  # godot-vrm's humanoid name (the helper defaults to VRoid's)
	beanbag = BEANBAG.instantiate()
	futon = FUTON.instantiate()
	for prop in [headset, beanbag, futon]:
		model.add_child(prop)
		prop.visible = false
		_shown[prop] = 0.0
	# the helper looks its skeleton up by path in _ready, before it has a parent: hand it over
	headset.set("_skeleton", skeleton)
	headset.set("_head", skeleton.find_bone("Head"))
	_mic = headset.find_child("Microphone_Boom", true, false) as Node3D
	beanbag.position = Vector3(0, 0, -BEANBAG_BACK)


## Once per frame, after the body has posed. `listening`: the agent's listening mood.
func update(delta: float, clip: String, listening: bool, mouth: float) -> void:
	_t += delta
	var talk := listening or clip == "Think" or clip == "Talk" or mouth > 0.03
	if talk or clip == "DanceVibe":
		_headset_until = _t + HEADSET_OFF_AFTER
		if _mic:
			_mic.visible = talk  # the mic for a conversation, plain headphones for music
	_pop(headset, _t < _headset_until, delta)

	var sitting := clip == "Sit"
	_pop(beanbag, sitting, delta)
	_settle = move_toward(_settle, 1.0 if sitting else 0.0, delta / SETTLE)
	beanbag.call("set_occupied", _settle)

	var sleeping := clip == "Sleep"
	if sleeping or _shown[futon] > 0.0:
		_lay_futon()
	if sleeping:  # raised over her, unless the take lies on top of it (clip_sources.cfg `blanket`)
		futon.call("set_occupied", float(body.take_meta().get("blanket", 1.0)))
	_pop(futon, sleeping, delta)


func _pop(prop: Node3D, wanted: bool, delta: float) -> void:
	var s: float = move_toward(_shown[prop], 1.0 if wanted else 0.0, delta / POP)
	if (s > 0.0) != (_shown[prop] > 0.0):
		print("RAPHAEL3D prop %s %s" % [prop.name, "on" if s > 0.0 else "off"])
	if s != _shown[prop]:
		_shown[prop] = s
		var model_node := prop.get_node("Model") as Node3D
		model_node.scale = Vector3.ONE * maxf(0.001, ease(s, 0.4))  # quick out, soft landing
	prop.visible = s > 0.0


## The futon along her body (feet -> head, so it also fits a take propped up on one arm):
## pillow under her head, on the floor under her.
func _lay_futon() -> void:
	var head := _local(skeleton.find_bone("Head"))
	var feet := (_local(skeleton.find_bone("LeftFoot")) + _local(skeleton.find_bone("RightFoot"))) / 2.0
	var along := Vector3(head.x - feet.x, 0, head.z - feet.z)
	if along.length() < 0.15:  # not lying down (yet): keep its last placement
		return
	along = along.normalized()
	var z := -along  # the futon's head end is its -Z
	futon.transform = Transform3D(Basis(Vector3.UP.cross(z), Vector3.UP, z),
			Vector3(head.x, 0, head.z) - along * PILLOW_FROM_CENTRE)


func _local(bone: int) -> Vector3:
	return model.to_local(skeleton.to_global(skeleton.get_bone_global_pose(bone).origin))
