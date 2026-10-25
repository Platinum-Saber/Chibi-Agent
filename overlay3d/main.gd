extends Node3D
## Her 3D body as a renderer for the Python overlay (overlay/chibi_overlay/godot3d.py), or a
## small preview window on its own.
##
## Renderer (`--renderer=PORT --token=T`): the overlay starts this, owns the window (covers
## the monitor she's on, sits just under the overlay's window, never takes clicks) and sends
## one frame per tick over a local TCP line-JSON link: her feet and height in window px,
## clip, expression, Live2D-style params, gaze. This sends back a hull around her in window
## px, which the overlay hit-tests for clicks. Brain, physics, input and her panels all
## stay in the overlay.
##
## Preview (no `--renderer`): a 520x1000 window bottom-right for checks and screenshots. It
## never takes focus (no_focus: the overlay's fullscreen watcher must not mistake it for a
## game), so there are no keys; use the arguments.
##   --model=res://models/x.vrm   another model (default raphael_teen.vrm)
##   --clip=NAME                  play a clip slot (default Idle)
##   --coat-clearance=off        disable post-animation coat/arm correction for comparison
##   --source=keyed               the keyed clips (clips.gd) only, no Mixamo takes
##   --expr=happy                 hold an expression
##   --gaze=X,Y                   look at this window point
##   --turn=DEG                   turn her about the vertical axis (180 = back view)
##   --take=NAME                  play this Mixamo take of the clip slot (file name without .fbx)
##   --listen=S                   pretend the agent is listening for the first S seconds (headset)
##   --offscreen                  keep the window off-screen (measuring)
##   --height=PX                  her height in the preview (default 850; in the overlay she's 520 at 100 %)
##   --seconds=S                  run S seconds, print the average fps, then quit
##   --screenshot=PATH            with --seconds: save the last frame (with alpha) as PNG

const Body = preload("res://raphael.gd")
const Props = preload("res://props.gd")
const DEFAULT_MODEL := "res://models/raphael_teen.vrm"
const PREVIEW_PX := 850.0  # her height in the preview window
const MARGIN := 30.0  # px of hull around her outline points (bones sit inside the mesh)
const HULL_RING := 8  # points per outline point when padding the hull
const TURN := 70.0  # degrees she turns while walking
const LINK_TIMEOUT_S := 15.0
const SMOOTH := 30.0  # 1/s: how fast her shown position closes on the predicted one (~8 px behind at 260 px/s)
const SNAP_PX := 60.0  # further than this (a drag, a throw, a monitor hop): jump there at once
const STATS_S := 10.0  # how often the link's timing goes to the log

@onready var camera: Camera3D = $Camera

var body: Body
var props: Props
var _listening := false  # the agent's listening mood (from the overlay's frames)
var model: Node3D
var args := {}
var height_m := 1.0  # her mesh height at rest
var _base_y := 0.0  # metres from her mesh bottom up to the model origin
var half_width_m := 0.2
var _hull := PackedVector2Array()
var _link: StreamPeerTCP
var _linked := false
var _since := 0.0
var _rx := ""
var _frame := {}
var _frame_at := 0  # usec when _frame arrived
var _shown := Vector2.INF  # where her feet are drawn (window px), smoothed
var _new := 0  # frames that arrived this Godot frame
var _stats := {"t": 0.0, "frames": 0, "ticks": 0, "none": 0, "multi": 0, "gap": 0, "last": 0}
var _yaw := 0.0
var _elapsed := 0.0
var _frames := 0


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""

	var path: String = args.get("model", DEFAULT_MODEL)
	if not ResourceLoader.exists(path):
		push_error("No model at %s. Export it first (overlay3d/README.md)." % path)
		get_tree().quit(1)
		return
	model = load(path).instantiate()
	_yaw = float(args.get("turn", "0"))
	model.rotation_degrees.y = _yaw

	# Pose her before the model enters the tree: the spring bones start from the pose they
	# first see, and arms swung down through hanging hair would trap it outside the arm colliders.
	body = Body.new()
	body.name = "Body"
	body.attach(model, args.get("source", "") == "keyed", args.get("coat-clearance", "on") != "off")
	add_child(model)
	add_child(body)
	_measure()
	props = Props.new()  # after measuring: props don't count toward her size
	props.name = "Props"
	add_child(props)
	props.attach(body)
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	_quality()

	if args.has("renderer"):
		_link = StreamPeerTCP.new()
		_link.connect_to_host("127.0.0.1", int(args["renderer"]))
		model.visible = false  # until the first frame places her
	else:
		body.play(args.get("clip", "Idle"))
		if args.has("take") and not body.force_take(args["take"]):
			push_warning("No take %s in %s" % [args["take"], body.clip_name()])
		if args.has("expr"):
			body.hold(args["expr"])
		if not args.has("offscreen"):
			var w := get_window()
			var usable := DisplayServer.screen_get_usable_rect(DisplayServer.get_primary_screen())
			w.position = Vector2i(usable.end.x - w.size.x - 40, usable.end.y - w.size.y)


## Render quality, from the overlay's [overlay] render_scale / msaa (godot3d.py passes them).
## Supersampling renders the 3D view larger and filters it down: her eyes, lashes and mouth
## get more pixels before they're shrunk, so they read clearer at the same size.
func _quality() -> void:
	var vp := get_viewport()
	vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	vp.scaling_3d_scale = clampf(float(args.get("render-scale", "1.0")), 0.5, 2.0)
	var msaa := {"0": Viewport.MSAA_DISABLED, "2": Viewport.MSAA_2X, "4": Viewport.MSAA_4X, "8": Viewport.MSAA_8X}
	vp.msaa_3d = msaa.get(args.get("msaa", "0"), Viewport.MSAA_DISABLED)
	print("RAPHAEL3D quality: render scale %.2f, msaa %s" % [vp.scaling_3d_scale, args.get("msaa", "0")])


func _measure() -> void:
	var box := AABB()
	var first := true
	for m in model.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = model.global_transform.affine_inverse() * m.global_transform * m.get_aabb()
		box = b if first else box.merge(b)
		first = false
	height_m = box.size.y
	_base_y = -box.position.y
	var xs: Array = body.outline_points().map(func(p: Vector3) -> float: return absf(p.x - model.global_position.x))
	half_width_m = xs.max() if not xs.is_empty() else 0.2


func _process(delta: float) -> void:
	if body == null:
		return
	if _link:
		_pump(delta)
	else:
		_preview()
		_listening = args.has("listen") and _elapsed < float(args["listen"])
	props.update(delta, body.clip_name(), _listening, body.mouth)
	_update_hull()
	if args.has("seconds"):
		_elapsed += delta
		_frames += 1
		if _elapsed >= float(args["seconds"]):
			_finish()


# --- preview ------------------------------------------------------------------------------
func _preview() -> void:
	var view := get_viewport().get_visible_rect().size
	_place(Vector2(view.x / 2.0, view.y - 30.0), float(args.get("height", PREVIEW_PX)), view)
	var g := Vector2(view.x / 2.0, 0)
	if args.has("gaze"):
		var p: PackedStringArray = args["gaze"].split(",")
		g = Vector2(float(p[0]), float(p[1]))
	body.look_toward(g - camera.unproject_position(body.head_position()) if args.has("gaze") else Vector2.ZERO)


# --- renderer -----------------------------------------------------------------------------
func _pump(delta: float) -> void:
	_link.poll()
	var st := _link.get_status()
	_since += delta
	if st == StreamPeerTCP.STATUS_CONNECTED:
		if not _linked:
			_linked = true
			_link.set_no_delay(true)  # the hull every frame: no Nagle batching
			_send({"t": "hello", "token": args.get("token", ""),
				"hwnd": DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE),
				"height_m": height_m, "half_width_m": half_width_m})
		var n := _link.get_available_bytes()
		if n > 0:
			_rx += _link.get_utf8_string(n)
			var lines := _rx.split("\n")
			_rx = lines[lines.size() - 1]
			for i in lines.size() - 1:
				var msg = JSON.parse_string(lines[i])
				if msg is Dictionary:
					_on_message(msg)
	elif (_linked and st != StreamPeerTCP.STATUS_CONNECTING) or st == StreamPeerTCP.STATUS_ERROR \
			or (not _linked and _since > LINK_TIMEOUT_S):
		print("RAPHAEL3D overlay link closed: quitting")  # the overlay quit, crashed or never came
		get_tree().quit()
		return
	_link_stats(delta)
	if _frame.is_empty():
		return
	_apply(_frame, delta)


## How evenly frames arrive, to the log every STATS_S: frames/s, the longest gap, and the share
## of Godot frames that got no new frame (she'd stand still) or several (she'd jump).
func _link_stats(delta: float) -> void:
	_stats["t"] += delta
	_stats["ticks"] += 1
	_stats["frames"] += _new
	if _new == 0:
		_stats["none"] += 1
	elif _new > 1:
		_stats["multi"] += 1
	_new = 0
	if _stats["t"] >= STATS_S:
		var k: int = _stats["ticks"]
		print("RAPHAEL3D link: %.1f frames/s, %.1f draws/s, longest gap %.1f ms, draws with no new frame %.0f%%, with 2+ %.0f%%" % [
			_stats["frames"] / _stats["t"], k / _stats["t"], _stats["gap"] / 1000.0,
			100.0 * _stats["none"] / k, 100.0 * _stats["multi"] / k])
		_stats = {"t": 0.0, "frames": 0, "ticks": 0, "none": 0, "multi": 0, "gap": 0, "last": _stats["last"]}


func _on_message(msg: Dictionary) -> void:
	match msg.get("t", ""):
		"frame":
			if _frame.is_empty():
				print("RAPHAEL3D first frame: ", msg)
			_frame = msg
			_frame_at = Time.get_ticks_usec()
			_new += 1
			if _stats["last"] > 0:
				_stats["gap"] = maxi(_stats["gap"], _frame_at - _stats["last"])
			_stats["last"] = _frame_at
		"quit":
			get_tree().quit()


func _apply(f: Dictionary, delta: float) -> void:
	model.visible = f.get("visible", true)
	if not model.visible:
		return
	var view := get_viewport().get_visible_rect().size
	var feet: Array = f.get("feet", [view.x / 2, view.y])
	var vel: Array = f.get("vel", [0, 0])
	# the overlay's frames and this window's vsync aren't in step: carry her on at her velocity
	# since the frame came (at most 50 ms, so a stalled overlay can't fling her)
	var ahead := minf((Time.get_ticks_usec() - _frame_at) / 1e6, 0.05)
	var target := Vector2(feet[0] + vel[0] * ahead, feet[1] + vel[1] * ahead)
	# and close on that prediction smoothly, so uneven arrivals don't show as steps
	if _shown == Vector2.INF or _shown.distance_to(target) > SNAP_PX:
		_shown = target
	else:
		_shown = _shown.lerp(target, 1.0 - exp(-delta * SMOOTH))
	_place(_shown, float(f.get("h", PREVIEW_PX)), view)
	# walking she turns toward where she goes; at rest she faces where Kryo turned her (middle-drag)
	var goal: float = (-TURN if f.get("facing_left", false) else TURN) if f.get("walking", false) else f.get("yaw", 0.0)
	_yaw = rad_to_deg(lerp_angle(deg_to_rad(_yaw), deg_to_rad(goal), 1.0 - exp(-delta * 12.0)))
	model.rotation_degrees.y = _yaw
	body.play(f.get("motion", "Idle"))
	body.hold(f.get("expression", ""))
	var params: Dictionary = f.get("params", {})
	body.params = params
	body.mouth = params.get("ParamMouthOpenY", 0.0)
	_listening = f.get("listening", false)
	body.eyes_closed = params.get("ParamEyeLOpen", 1.0) < 0.5
	var gaze = f.get("gaze")
	var head := camera.unproject_position(body.head_position())
	body.look_toward(Vector2(gaze[0], gaze[1]) - head if gaze is Array else Vector2.ZERO)
	if Engine.get_process_frames() % 600 == 0:
		print("RAPHAEL3D view=%s feet=%s h=%s clip=%s model_at=%s" % [view, feet, f.get("h"), body.clip_name(), model.position])


func _send(msg: Dictionary) -> void:
	if _link and _link.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		_link.put_data((JSON.stringify(msg) + "\n").to_utf8_buffer())


# --- shared -------------------------------------------------------------------------------
## Orthographic camera over the whole window (window px <-> metres, y up from the bottom),
## her feet at `feet` px and `h_px` tall.
func _place(feet: Vector2, h_px: float, view: Vector2) -> void:
	var ppm := h_px / height_m
	camera.size = view.y / ppm
	camera.position = Vector3(view.x / 2.0 / ppm, view.y / 2.0 / ppm, 10.0)
	model.position = Vector3(feet.x / ppm, (view.y - feet.y) / ppm + _base_y, 0)


func _update_hull() -> void:
	if not model.visible:
		_hull = PackedVector2Array()
	else:
		var pts := PackedVector2Array()
		for p in body.outline_points():
			var s := camera.unproject_position(p)
			for k in HULL_RING:
				pts.append(s + Vector2.from_angle(TAU * k / HULL_RING) * MARGIN)
		_hull = Geometry2D.convex_hull(pts)
	if _linked:
		var flat := []
		for v in _hull:
			flat.append(roundi(v.x))
			flat.append(roundi(v.y))
		_send({"t": "hull", "pts": flat})


## --pose-report: her bones' extent in the futon's own space (x across, y up from the floor,
## z along, -z = pillow end), to brief prop makers; in her model's space while the futon is off.
func _pose_report() -> void:
	var sk: Skeleton3D = body.skeleton
	var space: Node3D = props.futon if props.futon != null else model
	var lo := Vector3.INF
	var hi := -Vector3.INF
	for bone in body._profile:  # her humanoid bones: hair and scarf tips droop below her
		var p: Vector3 = space.to_local(sk.to_global(sk.get_bone_global_pose(sk.find_bone(bone)).origin))
		lo = Vector3(minf(lo.x, p.x), minf(lo.y, p.y), minf(lo.z, p.z))
		hi = Vector3(maxf(hi.x, p.x), maxf(hi.y, p.y), maxf(hi.z, p.z))
	var head: Vector3 = space.to_local(sk.to_global(sk.get_bone_global_pose(sk.find_bone("Head")).origin))
	var hips: Vector3 = space.to_local(sk.to_global(sk.get_bone_global_pose(sk.find_bone("Hips")).origin))
	print("RAPHAEL3D pose-report take=%s bones x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f head %s hips %s" % [
		body.take_meta(), lo.x, hi.x, lo.y, hi.y, lo.z, hi.z, head.snapped(Vector3.ONE * 0.01), hips.snapped(Vector3.ONE * 0.01)])


func _finish() -> void:
	if args.has("pose-report"):
		_pose_report()
	print("RAPHAEL3D fps_avg=%.1f frames=%d seconds=%.1f clip=%s" % [_frames / _elapsed, _frames, _elapsed, body.clip_name()])
	if args.has("screenshot"):
		var img := get_viewport().get_texture().get_image()
		img.save_png(args["screenshot"])
		var used := img.get_used_rect()
		var outside := 0
		for y in range(used.position.y, used.end.y, 2):
			for x in range(used.position.x, used.end.x, 2):
				if img.get_pixel(x, y).a > 0.0 and not Geometry2D.is_point_in_polygon(Vector2(x, y), _hull):
					outside += 1
		print("RAPHAEL3D screenshot %s drawn=%s drawn_px_outside_hull=%d" % [args["screenshot"], used, outside])
	get_tree().quit()
