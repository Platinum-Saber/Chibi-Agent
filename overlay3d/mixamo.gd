extends RefCounted
## Mixamo FBX clips (overlay3d/anims/mixamo/, out of git) retargeted onto her skeleton and
## baked once at load into her own local bone rotations at 30 fps.
##
## Retarget: both skeletons rest in a T-pose facing +Z (her left along +X). For each frame
## the clip's world-space change of a bone from its rest, D = G_pose * G_rest^-1, is applied
## to her rest: target = D * her_global_rest, local = parent_pose^-1 * target. That holds
## whatever the two rigs' bone axes are. Only the hips' height carries over (scaled by hip
## height); sideways and forward root motion is dropped: the overlay moves her.

const FPS := 30.0
const PREFIX := "mixamorig_"
const BASE := {  # Mixamo -> Godot humanoid profile (godot-vrm renamed her bones to these)
	"Hips": "Hips", "Spine": "Spine", "Spine1": "Chest", "Spine2": "UpperChest",
	"Neck": "Neck", "Head": "Head",
}
const SIDED := {
	"Shoulder": "Shoulder", "Arm": "UpperArm", "ForeArm": "LowerArm", "Hand": "Hand",
	"UpLeg": "UpperLeg", "Leg": "LowerLeg", "Foot": "Foot", "ToeBase": "Toes",
	"HandThumb1": "ThumbMetacarpal", "HandThumb2": "ThumbProximal", "HandThumb3": "ThumbDistal",
	"HandIndex1": "IndexProximal", "HandIndex2": "IndexIntermediate", "HandIndex3": "IndexDistal",
	"HandMiddle1": "MiddleProximal", "HandMiddle2": "MiddleIntermediate", "HandMiddle3": "MiddleDistal",
	"HandRing1": "RingProximal", "HandRing2": "RingIntermediate", "HandRing3": "RingDistal",
	"HandPinky1": "LittleProximal", "HandPinky2": "LittleIntermediate", "HandPinky3": "LittleDistal",
}


## One baked clip: her bone name -> PackedFloat32Array of quaternions (x, y, z, w per frame),
## plus the hip drop per frame (metres, + = lower).
class Baked:
	var name := ""
	var frames := 0
	var length := 0.0
	var bones := {}
	var drop := PackedFloat32Array()

	## Her local rotations and hip drop at time t (looping wraps, else holds the last frame).
	func sample(t: float, loop: bool) -> Dictionary:
		var f := t * FPS
		var last := frames - 1
		if loop and last > 0:
			f = fmod(f, float(last))
		f = clampf(f, 0.0, float(last))
		var i := int(f)
		var j := mini(i + 1, last)
		var w := f - i
		var out := {}
		for b in bones:
			var a: PackedFloat32Array = bones[b]
			var q0 := Quaternion(a[i * 4], a[i * 4 + 1], a[i * 4 + 2], a[i * 4 + 3])
			var q1 := Quaternion(a[j * 4], a[j * 4 + 1], a[j * 4 + 2], a[j * 4 + 3])
			out[b] = q0.slerp(q1, w)
		out["_drop"] = lerpf(drop[i], drop[j], w)
		return out


static func profile_name(mixamo: String) -> String:
	var n := mixamo.trim_prefix(PREFIX)
	if BASE.has(n):
		return BASE[n]
	for side in ["Left", "Right"]:
		if n.begins_with(side) and SIDED.has(n.substr(side.length())):
			return side + SIDED[n.substr(side.length())]
	return ""


## Bake `path` (res://anims/mixamo/x.fbx) for her `skeleton`. `start`/`end` trim in seconds
## (end <= 0: to the end); `lift` raises the take by metres; `keep_height` ignores the take's
## own hip height (her hips stay at standing height, minus `lift`). Null if the file has no skeleton or animation.
static func bake(path: String, skeleton: Skeleton3D, start := 0.0, end := 0.0, lift := 0.0,
		keep_height := false) -> Baked:
	var res = load(path)
	if not res is PackedScene:
		push_warning("mixamo: can't load %s" % path)
		return null
	var scene: Node = res.instantiate()
	var sks := scene.find_children("*", "Skeleton3D", true, false)
	var aps := scene.find_children("*", "AnimationPlayer", true, false)
	if sks.is_empty() or aps.is_empty():
		scene.free()
		push_warning("mixamo: no skeleton or animation in %s" % path)
		return null
	var src: Skeleton3D = sks[0]
	var ap: AnimationPlayer = aps[0]
	var anim := ap.get_animation(ap.get_animation_list()[0])
	var skel_path := String(scene.get_path_to(src))

	# their side: rest rotations, global rests, rotation tracks, hips position track
	var n := src.get_bone_count()
	var parent := PackedInt32Array()
	var rest_local: Array[Quaternion] = []
	var rest_global: Array[Quaternion] = []
	var track := PackedInt32Array()
	for i in n:
		parent.append(src.get_bone_parent(i))
		rest_local.append(src.get_bone_rest(i).basis.get_rotation_quaternion())
		var p := parent[i]
		rest_global.append(rest_local[i] if p < 0 else rest_global[p] * rest_local[i])
		track.append(anim.find_track(NodePath("%s:%s" % [skel_path, src.get_bone_name(i)]), Animation.TYPE_ROTATION_3D))
	var hips_t := src.find_bone(PREFIX + "Hips")
	var hips_pos_track := anim.find_track(NodePath("%s:%s" % [skel_path, PREFIX + "Hips"]), Animation.TYPE_POSITION_3D)
	var their_hip_y := src.get_bone_global_rest(hips_t).origin.y if hips_t >= 0 else 1.0

	# her side: which of her bones each of theirs drives, her global rests and parents
	var drives := {}  # their index -> her index
	for i in n:
		var her := skeleton.find_bone(profile_name(src.get_bone_name(i)))
		if her >= 0:
			drives[i] = her
	var m := skeleton.get_bone_count()
	var her_rest_local: Array[Quaternion] = []
	var her_rest_global: Array[Quaternion] = []
	for j in m:
		her_rest_local.append(skeleton.get_bone_rest(j).basis.get_rotation_quaternion())
		her_rest_global.append(skeleton.get_bone_global_rest(j).basis.get_rotation_quaternion())
	var her_hips := skeleton.find_bone("Hips")
	var her_hip_y := skeleton.get_bone_global_rest(her_hips).origin.y
	var driven := {}  # her index -> their index
	for i in drives:
		driven[drives[i]] = i
	var order := _parents_first(skeleton, driven.keys())

	var t0 := clampf(start, 0.0, anim.length)
	var t1 := anim.length if end <= 0.0 else clampf(end, t0, anim.length)
	var out := Baked.new()
	out.name = path.get_file().get_basename()
	out.frames = maxi(2, int(ceil((t1 - t0) * FPS)) + 1)
	out.length = (out.frames - 1) / FPS
	for j in driven:
		var arr := PackedFloat32Array()
		arr.resize(out.frames * 4)
		out.bones[skeleton.get_bone_name(j)] = arr
	out.drop.resize(out.frames)

	var g_pose: Array[Quaternion] = []
	g_pose.resize(n)
	for f in out.frames:
		var t := minf(t0 + f / FPS, t1)
		for i in n:  # their bones come parents first (FBX import order)
			var q := rest_local[i] if track[i] < 0 else anim.rotation_track_interpolate(track[i], t)
			g_pose[i] = q if parent[i] < 0 else g_pose[parent[i]] * q
		var her_global := {}  # her index -> global pose rotation, filled parents first
		for j in order:
			var i: int = driven[j]
			var target: Quaternion = (g_pose[i] * rest_global[i].inverse()) * her_rest_global[j]
			var pg := _her_parent_global(skeleton, j, her_global, her_rest_local)
			var local := (pg.inverse() * target).normalized()
			her_global[j] = target
			var arr: PackedFloat32Array = out.bones[skeleton.get_bone_name(j)]
			arr[f * 4] = local.x
			arr[f * 4 + 1] = local.y
			arr[f * 4 + 2] = local.z
			arr[f * 4 + 3] = local.w
		var y := their_hip_y
		if hips_pos_track >= 0 and not keep_height:
			y = anim.position_track_interpolate(hips_pos_track, t).y
		out.drop[f] = (their_hip_y - y) * her_hip_y / their_hip_y - lift
	scene.free()
	return out


## Her bones in an order where every driven bone comes after its driven ancestors.
static func _parents_first(skeleton: Skeleton3D, bones: Array) -> Array:
	var depth := {}
	for j in bones:
		var d := 0
		var p := skeleton.get_bone_parent(j)
		while p >= 0:
			d += 1
			p = skeleton.get_bone_parent(p)
		depth[j] = d
	var out := bones.duplicate()
	out.sort_custom(func(a, b): return depth[a] < depth[b])
	return out


## The global pose rotation of her bone j's parent: driven ancestors from this frame,
## undriven ones at rest.
static func _her_parent_global(skeleton: Skeleton3D, j: int, her_global: Dictionary, rest_local: Array) -> Quaternion:
	var chain: Array[int] = []
	var p := skeleton.get_bone_parent(j)
	while p >= 0 and not her_global.has(p):
		chain.append(p)
		p = skeleton.get_bone_parent(p)
	var g: Quaternion = her_global[p] if p >= 0 else Quaternion.IDENTITY
	for k in range(chain.size() - 1, -1, -1):
		g = g * rest_local[chain[k]]
	return g
