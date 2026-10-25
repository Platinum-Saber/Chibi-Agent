extends RefCounted
## Her body clips, keyed in code (Kryo's choice until real Mixamo/VRMA clips replace them
## through overlay/rigs/raphael_3d.toml).
##
## A pose is {bone: Vector3(x, y, z)}: degrees about the model axes at rest, applied Z
## first, then Y, then X (raphael.gd `_rot`). The model faces +Z; +X is her left.
##   x: pitch. Spine/neck/head: + leans forward/looks down. Legs: - swings forward, lower leg + bends the knee.
##      Arms (after Z/Y): - raises the arm forward.
##   y: yaw. Spine/head: + turns to her left (screen right). Left arm: - swings forward. Lower arm: bends the elbow.
##   z: roll. Left arm: - lowers it from the T-pose, + raises it. Head: + tilts to her right.
## Right-side bones mirror left ones: (x, -y, -z). "_drop" lowers her hips by metres.
## Missing clip names fall back to Idle; every clip starts from STANCE.

const ARM_DOWN := 70.0
const ELBOW := 12.0
const CURL := {"Proximal": 18.0, "Intermediate": 28.0, "Distal": 18.0}
const FINGERS := ["Index", "Middle", "Ring", "Little"]

const LOOPING := {
	"Idle": true, "Talk": true, "AnswerPoint": false, "Answer": true, "Think": true, "Analyse": true, "Notice": true, "Happy": true,
	"Surprised": false, "Pout": true, "Upset": true, "Held": true, "Fall": true, "Land": false,
	"FallFlat": true, "FlatImpact": false, "GetUp": false, "Carried": false, "Dizzy": true, "Walk": true, "Sleep": true, "DanceVibe": true, "DanceExcited": true,
	"LookAround": true, "Stretch": false, "Sit": true, "Wave": true,
}


static func names() -> Array:
	return LOOPING.keys()


static func pose(name: String, t: float) -> Dictionary:
	var p := stance()
	match name:
		"Talk", "Answer": _talk(p, t)
		"Think": _think(p, t)
		"Analyse", "AnswerPoint": _analyse(p, t)
		"Notice": _notice(p, t)
		"Happy": _happy(p, t)
		"Surprised": _surprised(p, t)
		"Pout": _pout(p, t)
		"Upset": _upset(p, t)
		"Held", "Carried": _held(p, t)  # Carried: picked up by the legs (Mixamo "Being Carried")
		"Fall", "FallFlat": _fall(p, t)  # FallFlat: Mixamo "Falling-facedown" after a carried drop
		"Land", "FlatImpact", "GetUp": _land(p, t)  # FlatImpact/GetUp: its landing (clip_sources.cfg)
		"Dizzy": _dizzy(p, t)
		"Walk": _walk(p, t)
		"Sleep": _sleep(p, t)
		"DanceVibe": _dance(p, t, false)
		"DanceExcited": _dance(p, t, true)
		"LookAround": _look_around(p, t)
		"Stretch": _stretch(p, t)
		"Sit": _sit(p, t)
		"Wave": _wave(p, t)
		_: _idle(p, t)
	return p


## Arms relaxed at her sides, elbows soft, fingers curled.
static func stance() -> Dictionary:
	var p := {"_drop": 0.0}
	_both(p, "UpperArm", Vector3(0, 0, -ARM_DOWN))
	_both(p, "LowerArm", Vector3(0, -ELBOW, 0))
	for f in FINGERS:
		for j in CURL:
			_both(p, f + j, Vector3(0, 0, -CURL[j]))
	return p


# --- helpers ------------------------------------------------------------------------------
static func _mirror(v: Vector3) -> Vector3:
	return Vector3(v.x, -v.y, -v.z)


## Same pose on both sides, given for the left.
static func _both(p: Dictionary, bone: String, left: Vector3) -> void:
	p["Left" + bone] = left
	p["Right" + bone] = _mirror(left)


## One side, given as if it were the left (mirrored for the right).
static func _side(p: Dictionary, side: String, bone: String, as_left: Vector3) -> void:
	p[side + bone] = as_left if side == "Left" else _mirror(as_left)


static func _add(p: Dictionary, bone: String, v: Vector3) -> void:
	p[bone] = p.get(bone, Vector3.ZERO) + v


static func _ease(t: float, length: float) -> float:
	## 0 -> 1 -> 0 over `length` seconds (one-shot clips hold at the end).
	return sin(clampf(t / length, 0.0, 1.0) * PI)


# --- clips --------------------------------------------------------------------------------
static func _idle(p: Dictionary, t: float) -> void:
	_add(p, "Hips", Vector3(0, 0, 0.8 * sin(t * TAU / 7.3)))
	_add(p, "Spine", Vector3(0, 1.5 * sin(t * TAU / 11.0), -0.6 * sin(t * TAU / 7.3)))


static func _talk(p: Dictionary, t: float) -> void:
	_idle(p, t)
	var g := 0.5 + 0.5 * sin(t * 2.3)
	_side(p, "Right", "UpperArm", Vector3(-18 * g, -10 * g, -ARM_DOWN + 8 * g))
	_side(p, "Right", "LowerArm", Vector3(0, -ELBOW - 55 * g, 0))
	var h := 0.5 + 0.5 * sin(t * 1.7 + 1.0)
	_side(p, "Left", "LowerArm", Vector3(0, -ELBOW - 25 * h, 0))
	_add(p, "Head", Vector3(2.0 * sin(t * 3.1), 0, 1.5 * sin(t * 1.3)))


static func _think(p: Dictionary, t: float) -> void:
	# right hand to her chin, left arm across her waist
	_side(p, "Right", "UpperArm", Vector3(-55, -15, -ARM_DOWN + 5))
	_side(p, "Right", "LowerArm", Vector3(0, -135, 0))
	_side(p, "Left", "UpperArm", Vector3(-12, -60, -ARM_DOWN))  # twisted in: the forearm crosses her waist
	_side(p, "Left", "LowerArm", Vector3(0, -95, 0))
	_add(p, "Head", Vector3(-4, 0, -7 + 1.5 * sin(t * 0.9)))
	_add(p, "Spine", Vector3(0, 0, 1.5))


static func _analyse(p: Dictionary, t: float) -> void:
	# right palm up beside her, looking at it (the HUD scan)
	_side(p, "Right", "UpperArm", Vector3(-25, -10, -45))
	_side(p, "Right", "LowerArm", Vector3(0, -75, 0))
	_add(p, "Head", Vector3(3, -12 + 3 * sin(t * 0.8), 0))
	_idle(p, t)


static func _notice(p: Dictionary, t: float) -> void:
	_both(p, "UpperArm", Vector3(-10, 0, -60))
	_both(p, "LowerArm", Vector3(0, -30, 0))
	_add(p, "Spine", Vector3(6, 0, 0))
	_add(p, "Chest", Vector3(3, 0, 0))
	_add(p, "Head", Vector3(-6, 4 * sin(t * 1.4), 0))


static func _happy(p: Dictionary, t: float) -> void:
	var b := absf(sin(t * TAU * 1.4))
	p["_drop"] = -0.025 * b
	_both(p, "UpperArm", Vector3(-20, 0, -42 + 6 * b))
	_both(p, "LowerArm", Vector3(0, -35, 0))
	_add(p, "Head", Vector3(0, 0, 5 * sin(t * TAU * 0.7)))


static func _surprised(p: Dictionary, t: float) -> void:
	var a := clampf(t / 0.15, 0.0, 1.0)
	_both(p, "UpperArm", Vector3(-35 * a, 0, -ARM_DOWN + 18 * a))
	_both(p, "LowerArm", Vector3(0, -ELBOW - 60 * a, 0))
	_add(p, "Spine", Vector3(-6 * a, 0, 0))
	_add(p, "Head", Vector3(-6 * a, 0, 0))


static func _pout(p: Dictionary, t: float) -> void:
	# arms crossed, head turned away
	_both(p, "UpperArm", Vector3(-28, -55, -ARM_DOWN + 5))  # twisted in: forearms cross
	_both(p, "LowerArm", Vector3(0, -105, 0))
	_add(p, "Head", Vector3(4, -14, 8))
	_add(p, "Spine", Vector3(0, -4, 0))
	_add(p, "Hips", Vector3(0, 0, 1.5 * sin(t * 2.0)))


static func _upset(p: Dictionary, t: float) -> void:
	# hands to her face, shoulders shaking
	_both(p, "UpperArm", Vector3(-70, -10, -ARM_DOWN + 10))
	_both(p, "LowerArm", Vector3(0, -140, 0))
	_add(p, "Head", Vector3(14, 0, 0))
	_add(p, "Chest", Vector3(4, 0, 2.0 * sin(t * 17.0)))


static func _held(p: Dictionary, t: float) -> void:
	_both(p, "UpperArm", Vector3(-10, 0, -45 + 4 * sin(t * 3.0)))
	_both(p, "LowerArm", Vector3(0, -25, 0))
	var s := sin(t * 2.4)
	p["LeftUpperLeg"] = Vector3(-6 * s, 0, 0)
	p["RightUpperLeg"] = Vector3(6 * s, 0, 0)
	_both(p, "LowerLeg", Vector3(14, 0, 0))
	_add(p, "Head", Vector3(6, 0, 0))


static func _fall(p: Dictionary, t: float) -> void:
	var f := sin(t * 14.0)
	_both(p, "UpperArm", Vector3(-15, 0, 25 + 12 * f))
	_both(p, "LowerArm", Vector3(0, -20, 0))
	_both(p, "UpperLeg", Vector3(-18, 0, 0))
	_both(p, "LowerLeg", Vector3(35, 0, 0))
	_add(p, "Head", Vector3(-8, 0, 0))


static func _land(p: Dictionary, t: float) -> void:
	var a := _ease(t, 0.6)
	p["_drop"] = 0.11 * a
	_both(p, "UpperLeg", Vector3(-38 * a, 0, 0))
	_both(p, "LowerLeg", Vector3(70 * a, 0, 0))
	_both(p, "Foot", Vector3(-30 * a, 0, 0))
	_add(p, "Spine", Vector3(12 * a, 0, 0))
	_both(p, "UpperArm", Vector3(-15 * a, 0, -ARM_DOWN + 20 * a))


static func _dizzy(p: Dictionary, t: float) -> void:
	_both(p, "UpperArm", Vector3(0, 0, -76))
	_add(p, "Head", Vector3(7 * cos(t * 4.5), 0, 9 * sin(t * 4.5)))
	_add(p, "Spine", Vector3(0, 0, 3.5 * sin(t * 4.5 - 0.6)))


static func _walk(p: Dictionary, t: float) -> void:
	var ph := t * TAU * 1.7
	var s := sin(ph)
	p["LeftUpperLeg"] = Vector3(-24 * s, 0, 0)
	p["RightUpperLeg"] = Vector3(24 * s, 0, 0)
	p["LeftLowerLeg"] = Vector3(8 + 30 * maxf(0.0, cos(ph)), 0, 0)
	p["RightLowerLeg"] = Vector3(8 + 30 * maxf(0.0, -cos(ph)), 0, 0)
	p["LeftUpperArm"] = Vector3(16 * s, 0, -ARM_DOWN - 4)
	p["RightUpperArm"] = _mirror(Vector3(-16 * s, 0, -ARM_DOWN - 4))
	p["_drop"] = 0.012 * absf(cos(ph))
	_add(p, "Spine", Vector3(3, 4 * s, 0))


static func _sit(p: Dictionary, t: float) -> void:
	# on the floor, legs out in front, hands on her thighs
	p["_drop"] = 0.56
	_both(p, "UpperLeg", Vector3(-82, 0, 0))
	_both(p, "LowerLeg", Vector3(12, 0, 0))
	_both(p, "Foot", Vector3(-12, 0, 0))
	_both(p, "UpperArm", Vector3(-28, 0, -ARM_DOWN + 4))
	_both(p, "LowerArm", Vector3(0, -40, 0))
	_add(p, "Spine", Vector3(4, 0, 0))
	_add(p, "Head", Vector3(0, 0, 2 * sin(t * 0.9)))


static func _sleep(p: Dictionary, t: float) -> void:
	_sit(p, t)
	_add(p, "Spine", Vector3(12 + 1.5 * sin(t * 1.2), 0, 0))
	_add(p, "Neck", Vector3(10, 0, 0))
	_add(p, "Head", Vector3(22, 0, 8))


static func _dance(p: Dictionary, t: float, excited: bool) -> void:
	var w := TAU * 110.0 / 60.0
	var k := 1.8 if excited else 1.0
	p["_drop"] = 0.02 * k * (0.5 - 0.5 * cos(w * t))
	_add(p, "Hips", Vector3(0, 0, 6 * k * sin(w * t / 2)))
	_add(p, "Spine", Vector3(0, 5 * sin(w * t / 2), -4 * k * sin(w * t / 2)))
	_add(p, "Head", Vector3(3 * sin(w * t), 0, 4 * sin(w * t / 2)))
	if excited:  # fist pumps
		var pump := 0.5 + 0.5 * sin(w * t)
		_side(p, "Right", "UpperArm", Vector3(-40, 0, 40 + 30 * pump))
		_side(p, "Right", "LowerArm", Vector3(0, -50 - 30 * pump, 0))
		_side(p, "Left", "UpperArm", Vector3(-20, 0, -50))
		_side(p, "Left", "LowerArm", Vector3(0, -70, 0))
	else:
		_both(p, "UpperArm", Vector3(-10 * sin(w * t / 2), 0, -62))
		_both(p, "LowerArm", Vector3(0, -40, 0))


static func _look_around(p: Dictionary, t: float) -> void:
	_idle(p, t)
	_add(p, "Head", Vector3(-2, 28 * sin(t * TAU / 2.6), 0))
	_add(p, "Neck", Vector3(0, 10 * sin(t * TAU / 2.6), 0))


static func _stretch(p: Dictionary, t: float) -> void:
	var a := _ease(t, 1.8)
	_both(p, "UpperArm", Vector3(0, 0, -ARM_DOWN + 155 * a))
	_both(p, "LowerArm", Vector3(0, -ELBOW + 8 * a, 0))
	_add(p, "Spine", Vector3(-6 * a, 0, 0))
	_add(p, "Head", Vector3(-10 * a, 0, 0))
	p["_drop"] = -0.015 * a


static func _wave(p: Dictionary, t: float) -> void:
	_idle(p, t)
	var a := clampf(t / 0.3, 0.0, 1.0)
	_side(p, "Right", "UpperArm", Vector3(-20 * a, 0, -ARM_DOWN + 62 * a))
	_side(p, "Right", "LowerArm", Vector3(0, 0, (85 + 22 * sin(t * 9.0)) * a))
	_add(p, "Head", Vector3(0, 0, -5 * a))
