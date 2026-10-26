extends Node
## Her props (props/, from Character Design's Raphael_Props_v01; the futon is futon-v02): shown
## only while they're used.
##
## Headset: on for a spoken conversation (push-to-talk until her reply ends; with the mic) and
## while media plays (no mic), off 5 s after both end. The overlay decides (stage.py `headset`):
## not for voice reactions, poses, briefings or typed chat (Saber, 2026-10-26).
## Beanbag: appears under her while she sits (Sit) and squashes as she settles.
## Futon (v02): appears under her while she sleeps (Sleep), laid along her body, the blanket
## shaped for the take (clip_sources.cfg `cover`: Cover_Front, Cover_Side, Cover_SitUp...).
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
const SHOW_FUTON := true  # false: she sleeps on the floor (set the Sleep lifts in clip_sources.cfg to 0)
# The props were made and previewed in Blender: soft light from several sides and its AgX view,
# which lifts and desaturates colour. Under her one sharp key light the same PBR colours come out
# vivid and dark-sided. So the furniture gets a fill light of its own (render layer 2: it can't
# reach her toon-shaded body) and its colours are lifted toward the Blender look.
const PROP_LAYER := 2
const DESATURATE := 0.4  # albedo saturation kept (Blender's AgX greys bright colours)
const VALUE := 0.92  # albedo brightness kept
const SPECULAR := 0.2  # softer sheen than the PBR default 0.5
const FILL_ENERGY := 0.45  # front-left fill
const BOUNCE_ENERGY := 0.6  # from below: the floor bounce Blender's studio had

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
var _cover := &""  # the blanket shape key set on the futon


func attach(b: Node) -> void:
	body = b
	model = b.model
	skeleton = b.skeleton
	headset = HEADSET.instantiate()
	headset.set("head_bone", &"Head")  # godot-vrm's humanoid name (the helper defaults to VRoid's)
	beanbag = BEANBAG.instantiate()
	futon = FUTON.instantiate() if SHOW_FUTON else null
	for prop in [headset, beanbag, futon]:
		if prop == null:
			continue
		model.add_child(prop)
		prop.visible = false
		_shown[prop] = 0.0
	if futon:
		futon.call("set_shape", &"Pillow_Dent", 1.0)  # her head's dent, under every cover
	# the helper looks its skeleton up by path in _ready, before it has a parent: hand it over
	headset.set("_skeleton", skeleton)
	headset.set("_head", skeleton.find_bone("Head"))
	_mic = headset.find_child("Microphone_Boom", true, false) as Node3D
	beanbag.position = Vector3(0, 0, -BEANBAG_BACK)
	for prop in [beanbag, futon]:
		if prop != null:
			_studio_look(prop)
	for light in [["PropFill", FILL_ENERGY, Vector3(-20, -35, 0)], ["PropBounce", BOUNCE_ENERGY, Vector3(35, 15, 0)]]:
		var l := DirectionalLight3D.new()
		l.name = light[0]
		l.light_energy = light[1]
		l.light_cull_mask = 1 << (PROP_LAYER - 1)
		l.rotation_degrees = light[2]  # fill: front-left, a little above; bounce: front, from below
		add_child(l)


## Once per frame, after the body has posed. `mode`: the headset's "talk", "music" or "" (the overlay's).
func update(delta: float, clip: String, mode: String) -> void:
	_t += delta
	var talk := mode == "talk"
	if mode != "":
		_headset_until = _t + HEADSET_OFF_AFTER
		if _mic:
			_mic.visible = talk  # the mic for a conversation, plain headphones for music
	_pop(headset, _t < _headset_until, delta)

	var sitting := clip == "Sit"
	_pop(beanbag, sitting, delta)
	_settle = move_toward(_settle, 1.0 if sitting else 0.0, delta / SETTLE)
	beanbag.call("set_occupied", _settle)

	if futon == null:
		return
	var sleeping := clip == "Sleep"
	if sleeping or _shown[futon] > 0.0:
		_lay_futon()
	if sleeping:  # the take's blanket shape; set_cover clears the others, so only on a change
		var cover := StringName(body.take_meta().get("cover", "Occupied"))
		if cover != _cover:
			_cover = cover
			futon.call("set_cover", cover)
	_pop(futon, sleeping, delta)


## Put a prop on the prop render layer (her key light still reaches it, the fill reaches only
## props) and lift its colours toward how it looked in Blender.
func _studio_look(prop: Node3D) -> void:
	for mi in prop.find_children("*", "MeshInstance3D", true, false):
		mi.layers = 1 | (1 << (PROP_LAYER - 1))
		for s in mi.mesh.get_surface_count():
			var mat := mi.get_active_material(s) as StandardMaterial3D
			if mat == null:
				continue
			mat = mat.duplicate()
			var c := mat.albedo_color
			mat.albedo_color = Color.from_hsv(c.h, c.s * DESATURATE, minf(1.0, c.v * VALUE), c.a)
			mat.metallic_specular = SPECULAR
			mi.set_surface_override_material(s, mat)


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
