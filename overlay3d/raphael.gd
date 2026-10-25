extends Node
## Her body for a VRM imported by godot-vrm: clips with crossfades, and over them breath,
## blinks, gaze, the Live2D-style params the overlay sends, and an expression mixer.
##
## A clip slot (Idle, Talk, Walk...) plays Mixamo motion when clip_sources.cfg names files for
## it that are in anims/mixamo/ (baked onto her skeleton at load, mixamo.gd; several files =
## a random one each time it starts or loops), else the clip keyed in clips.gd. Poses are her
## local bone rotations over the humanoid profile bones only: spring-bone hair and scarf are
## left to their physics.
##
## godot-vrm renames the bones to Godot's humanoid profile (Head, LeftUpperArm, ...),
## faces the model +Z and turns each VRM expression into an animation of blend-shape
## tracks. The mixer reads those tracks once and sets the blend shapes itself, so
## several expressions (a held mood, a blink, a mouth shape) can mix.

const Clips = preload("res://clips.gd")
const Mixamo = preload("res://mixamo.gd")
const CoatClearance = preload("res://coat_clearance.gd")
const SOURCES := "res://clip_sources.cfg"
const BREATH_PERIOD := 4.2
const CROSSFADE := 0.25  # s between clips
const FADE := 8.0  # expression weight change per second

var model: Node3D
var skeleton: Skeleton3D
var coat_clearance: CoatClearance
var talking := false  # fake lip sync (standalone key M)
var mouth := -1.0  # 0..1 from the overlay (ParamMouthOpenY); -1: not driven
var eyes_closed := false
var params := {}  # Live2D-style ids from the overlay's Stage.params

var _clip := "Idle"
var _clip_t := 0.0
var _src: Mixamo.Baked = null  # the Mixamo take playing now; null: the keyed clip
var _prev_pose := {}  # the pose when the last clip change started, faded out from
var _last_pose := {}
var _fade := 1.0  # 0 -> 1 from _prev_pose to the clip
var _hips_rest := Vector3.ZERO
var _sources := {}  # slot -> {"takes": [Baked...], "loop": bool}
var _profile: Array[String] = []  # her humanoid bones, the only ones poses touch
var _axes := {}  # bone index -> [x, y, z] model axes in the bone's rest frame

var _binds := {}  # expression -> [[MeshInstance3D, shape index, weight], ...]
var _weight := {}  # expression -> current weight
var _target := {}  # expression -> target weight
var _shapes := {}  # "id:index" -> [MeshInstance3D, shape index], every shape we drive
var _held := ""
var _rest := {}  # bone index -> rest rotation
var _gaze := Vector2.ZERO  # degrees: yaw, pitch
var _gaze_goal := Vector2.ZERO
var _t := 0.0
var _next_blink := 2.0
var _blink_t := -1.0
var _bone := {}


func attach(m: Node3D, keyed := false, clearance_enabled := true) -> void:
	model = m
	skeleton = m.find_children("*", "Skeleton3D", true, false)[0]
	for i in skeleton.get_bone_count():  # profile names: Hips, LeftUpperArm, RightIndexDistal, ...
		_bone[skeleton.get_bone_name(i)] = i
		_rest[i] = skeleton.get_bone_rest(i).basis.get_rotation_quaternion()
		var to_local := skeleton.get_bone_global_rest(i).basis.orthonormalized().inverse()
		_axes[i] = [(to_local * Vector3.RIGHT).normalized(), (to_local * Vector3.UP).normalized(),
				(to_local * Vector3.BACK).normalized()]
	var profile := SkeletonProfileHumanoid.new()
	for k in profile.bone_size:
		if _bone.has(profile.get_bone_name(k)):
			_profile.append(profile.get_bone_name(k))
	_hips_rest = skeleton.get_bone_rest(_bone["Hips"]).origin
	_read_expressions(m)
	_fix_alpha(m)
	load_sources(keyed)
	coat_clearance = CoatClearance.new()
	if not coat_clearance.setup(skeleton, model):
		push_warning("Coat clearance unavailable: expected coat/arm bones not found")
		coat_clearance = null
	elif not clearance_enabled:
		coat_clearance.enabled = false
	_pose(0.0)
	process_priority = -10  # pose before the spring bones read it


## The scarf's Blender shader is unlit (texture -> emission, alpha from the texture). glTF
## exports that as a black base colour plus an emissive texture and drops the alpha, so its
## transparent fringe turns black. Rebuild such materials as an unlit texture cut at its alpha.
func _fix_alpha(m: Node3D) -> void:
	for mesh in m.find_children("*", "MeshInstance3D", true, false):
		for s in mesh.mesh.get_surface_count():
			var mat := mesh.mesh.surface_get_material(s) as StandardMaterial3D
			if mat == null or mat.albedo_texture or not mat.emission_texture or mat.albedo_color.v > 0.01:
				continue
			mat.albedo_texture = mat.emission_texture
			mat.albedo_color = Color.WHITE
			mat.emission_enabled = false
			mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
			mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
			mat.alpha_scissor_threshold = 0.4
			mat.cull_mode = BaseMaterial3D.CULL_DISABLED
			print("RAPHAEL3D unlit alpha-cut material: ", mat.resource_name)


func _read_expressions(m: Node3D) -> void:
	var player: AnimationPlayer = m.get_node_or_null("AnimationPlayer")
	if player == null:
		push_warning("No AnimationPlayer: expressions off")
		return
	var root := player.get_node(player.root_node)
	for anim_name in player.get_animation_list():
		if anim_name == "RESET":
			continue
		var anim := player.get_animation(anim_name)
		var binds := []
		for t in anim.get_track_count():
			if anim.track_get_type(t) != Animation.TYPE_BLEND_SHAPE or anim.track_get_key_count(t) == 0:
				continue
			var path := anim.track_get_path(t)
			var mesh := root.get_node_or_null(NodePath(path.get_concatenated_names())) as MeshInstance3D
			if mesh == null:
				continue
			var idx := mesh.find_blend_shape_by_name(path.get_concatenated_subnames())
			if idx < 0:
				continue
			var w := 0.0
			for k in anim.track_get_key_count(t):
				w = maxf(w, anim.track_get_key_value(t, k))
			binds.append([mesh, idx, w])
			_shapes["%d:%d" % [mesh.get_instance_id(), idx]] = [mesh, idx]
		if not binds.is_empty():
			var key := String(anim_name).to_lower()
			_binds[key] = binds
			_weight[key] = 0.0
			_target[key] = 0.0
	print("RAPHAEL3D expressions: ", ", ".join(_binds.keys()))


## Bake the Mixamo takes named in clip_sources.cfg (skipped with `keyed`: clips.gd only).
func load_sources(keyed := false) -> void:
	_sources = {}
	if keyed:
		return
	var cfg := ConfigFile.new()
	if cfg.load(SOURCES) != OK:
		push_warning("No %s: keyed clips only" % SOURCES)
		return
	var t0 := Time.get_ticks_msec()
	var used := []
	for slot in cfg.get_sections():
		var takes := []
		for f in cfg.get_value(slot, "files", []):
			var path := "res://anims/mixamo/%s" % f
			if not ResourceLoader.exists(path):
				continue
			var b := Mixamo.bake(path, skeleton, cfg.get_value(slot, "start", 0.0),
					cfg.get_value(slot, "end", 0.0), cfg.get_value(slot, "lift", 0.0),
					cfg.get_value(slot, "keep_height", false))
			if b:
				takes.append(b)
		if not takes.is_empty():
			_sources[slot] = {"takes": takes, "loop": cfg.get_value(slot, "loop", Clips.LOOPING.get(slot, true))}
			used.append("%s(%d)" % [slot, takes.size()])
	print("RAPHAEL3D clips: Mixamo for %s; keyed for the rest; baked in %d ms" % [
		", ".join(used), Time.get_ticks_msec() - t0])
	_src = _take(_clip)


## Play a clip slot (clips.gd names; unknown names play Idle). The same name keeps running.
func play(clip: String) -> void:
	if clip == _clip:
		return
	_restart(clip)


func _restart(clip: String) -> void:
	_prev_pose = _last_pose
	_fade = 0.0
	_clip = clip
	_clip_t = 0.0
	_src = _take(clip)


func _take(slot: String) -> Mixamo.Baked:
	var s = _sources.get(slot)
	return null if s == null else s["takes"].pick_random()


func _looping(slot: String) -> bool:
	var s = _sources.get(slot)
	return s["loop"] if s != null else Clips.LOOPING.get(slot, true)


func clip_name() -> String:
	return _clip


## Hold one expression ("" or "neutral" clears). Unknown names are ignored with a warning.
func hold(expr: String) -> void:
	expr = expr.to_lower()
	if expr == "neutral":
		expr = ""
	if expr == _held:
		return
	if _held != "":
		_target[_held] = 0.0
	_held = expr if _binds.has(expr) else ""
	if expr != "" and _held == "":
		push_warning("No expression '%s' (have: %s)" % [expr, ", ".join(_binds.keys())])
	if _held != "":
		_target[_held] = 1.0
		if expr == "blink":
			_next_blink = INF


## Screen-space offset in px from her head to what she should look at.
func look_toward(offset: Vector2) -> void:
	_gaze_goal = Vector2(clampf(offset.x / 700.0, -1, 1) * 22.0, clampf(offset.y / 700.0, -1, 1) * 14.0)


func head_position() -> Vector3:
	return skeleton.global_transform * skeleton.get_bone_global_pose(_bone["Head"]).origin


## Points that outline her: every bone (hair and scarf chains included, so their swing
## counts), the top of her head and the floor under her feet.
func outline_points() -> Array[Vector3]:
	var out: Array[Vector3] = []
	for i in skeleton.get_bone_count():
		out.append(skeleton.global_transform * skeleton.get_bone_global_pose(i).origin)
	out.append(head_position() + model.global_basis.y * 0.28)
	out.append(model.global_position)
	return out


func _process(delta: float) -> void:
	if skeleton == null:
		return
	_t += delta
	_pose(delta)
	_blink(delta)
	_mouth()
	_apply_expressions(delta)


func _pose(delta: float) -> void:
	_clip_t += delta
	_fade = minf(1.0, _fade + delta / CROSSFADE)
	var loop := _looping(_clip)
	if _src and loop and _clip_t >= _src.length and _sources[_clip]["takes"].size() > 1:
		_restart(_clip)  # another take of the same slot (variety while she talks or idles)
	var p := _src.sample(_clip_t, loop) if _src else _keyed(_clip, _clip_t)
	if _fade < 1.0 and not _prev_pose.is_empty():
		p = _blend(_prev_pose, p, smoothstep(0.0, 1.0, _fade))
	_last_pose = p

	# layers over the clip, in degrees about the model axes: breath, the overlay's params, gaze
	var breath := sin(_t * TAU / BREATH_PERIOD)
	_gaze = _gaze.lerp(_gaze_goal, 1.0 - exp(-delta * 4.0))
	var lay := {}
	_add(lay, "Spine", Vector3(breath * 0.6, 0, 0))
	_add(lay, "Chest", Vector3(breath * 0.9, 0, 0))
	_add(lay, "LeftUpperArm", Vector3(0, 0, breath * 0.8))
	_add(lay, "RightUpperArm", Vector3(0, 0, -breath * 0.8))
	_add(lay, "Hips", Vector3(0, 0, params.get("ParamBodyAngleX", 0.0)))  # dance sway, held tilt
	_add(lay, "Head", Vector3(-params.get("ParamAngleY", 0.0) - breath * 0.4,
			params.get("ParamAngleX", 0.0), -params.get("ParamAngleZ", 0.0)))
	_add(lay, "Neck", Vector3(_gaze.y * 0.4, _gaze.x * 0.4, 0))
	_add(lay, "Head", Vector3(_gaze.y * 0.6, _gaze.x * 0.6, 0))
	if _bone.has("LeftEye"):
		lay["LeftEye"] = Vector3(_gaze.y * 0.5, _gaze.x * 0.5, 0)
		lay["RightEye"] = lay["LeftEye"]
	elif _binds.has("lookleft"):
		_target["lookleft"] = clampf(_gaze.x / 22.0, 0, 1)
		_target["lookright"] = clampf(-_gaze.x / 22.0, 0, 1)
		_target["lookdown"] = clampf(_gaze.y / 14.0, 0, 1)
		_target["lookup"] = clampf(-_gaze.y / 14.0, 0, 1)

	for bone in _profile:  # every humanoid bone each frame, so nothing from the last clip sticks
		var i: int = _bone[bone]
		var q: Quaternion = p.get(bone, _rest[i])
		if lay.has(bone):
			q = q * _turn(i, lay[bone])
		skeleton.set_bone_pose_rotation(i, q)
	skeleton.set_bone_pose_position(_bone["Hips"], _hips_rest - Vector3(0, p.get("_drop", 0.0), 0))
	# Last humanoid layer: preserve Mixamo/keyed motion while keeping hands outside the coat.
	# Spring-bone hair/scarf run later, and read this final arm pose.
	if coat_clearance != null:
		coat_clearance.apply(delta)


## A keyed clip (clips.gd degrees) as local rotations.
func _keyed(clip: String, t: float) -> Dictionary:
	var deg := Clips.pose(clip, t)
	var out := {"_drop": deg.get("_drop", 0.0)}
	for bone in deg:
		if bone != "_drop" and _bone.has(bone):
			var i: int = _bone[bone]
			out[bone] = _rest[i] * _turn(i, deg[bone])
	return out


static func _add(p: Dictionary, bone: String, v: Vector3) -> void:
	p[bone] = p.get(bone, Vector3.ZERO) + v


func _blend(a: Dictionary, b: Dictionary, w: float) -> Dictionary:
	var out := {"_drop": lerpf(a.get("_drop", 0.0), b.get("_drop", 0.0), w)}
	for bone in _profile:
		if a.has(bone) or b.has(bone):
			var r: Quaternion = _rest[_bone[bone]]
			out[bone] = (a.get(bone, r) as Quaternion).slerp(b.get(bone, r), w)
	return out


## Degrees about the model axes at rest, Z first, then Y, then X (see clips.gd).
func _turn(i: int, deg: Vector3) -> Quaternion:
	var ax: Array = _axes[i]
	return Quaternion(ax[0], deg_to_rad(deg.x)) * Quaternion(ax[1], deg_to_rad(deg.y)) \
			* Quaternion(ax[2], deg_to_rad(deg.z))


func _blink(delta: float) -> void:
	if not _binds.has("blink") or _held == "blink":
		return
	if eyes_closed:  # asleep (ParamEyeL/ROpen = 0)
		_weight["blink"] = move_toward(_weight["blink"], 1.0, delta * 4.0)
		_target["blink"] = _weight["blink"]
		_blink_t = -1.0
		return
	_next_blink -= delta
	if _next_blink <= 0.0 and _blink_t < 0.0:
		_blink_t = 0.0
		_next_blink = randf_range(2.0, 6.0)
	if _blink_t >= 0.0:
		_blink_t += delta
		# close 60 ms, hold 40 ms, open 110 ms
		var w := 0.0
		if _blink_t < 0.06:
			w = _blink_t / 0.06
		elif _blink_t < 0.10:
			w = 1.0
		elif _blink_t < 0.21:
			w = 1.0 - (_blink_t - 0.10) / 0.11
		else:
			_blink_t = -1.0
		_weight["blink"] = w
		_target["blink"] = w
	else:  # awake between blinks: open (after sleep the weight is still at 1)
		_weight["blink"] = move_toward(_weight["blink"], 0.0, delta * 4.0)
		_target["blink"] = _weight["blink"]


func _mouth() -> void:
	# The overlay's lip level (voice RMS) opens her mouth, cycling vowels so it isn't one shape;
	# standalone, key M fakes it.
	var vowels := ["aa", "ih", "ou", "ee", "oh"]
	var open := mouth if mouth >= 0.0 else (maxf(0.0, sin(_t * 11.0)) if talking else 0.0)
	var current: String = vowels[int(_t * 3.0) % vowels.size()]
	for v in vowels:
		if _binds.has(v):
			_target[v] = open if v == current else 0.0


func _apply_expressions(delta: float) -> void:
	var value := {}
	for key in _binds:
		if key != "blink":
			_weight[key] = move_toward(_weight[key], _target[key], FADE * delta)
		var w: float = _weight[key]
		if w <= 0.0:
			continue
		for b in _binds[key]:
			var id := "%d:%d" % [b[0].get_instance_id(), b[1]]
			value[id] = minf(1.0, value.get(id, 0.0) + w * b[2])
	for id in _shapes:
		var s: Array = _shapes[id]
		s[0].set_blend_shape_value(s[1], value.get(id, 0.0))
