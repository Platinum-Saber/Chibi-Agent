extends RefCounted
## Post-animation arm clearance. Distances and transforms are skeleton-local, in metres.
## Convex coat volumes and spherical hand/forearm probes are fitted once, then followed.
var enabled := true
var smoothing_speed := 24.0
var release_speed := 9.0
var max_offset := 0.16
var skeleton: Skeleton3D
var volumes: Array[Dictionary] = []
var arms: Array[Dictionary] = []
var diagnostics := {}
var _nodes: Node3D
var _scale := 1.0
var _ready := false

func setup(sk: Skeleton3D, model: Node3D) -> bool:
	skeleton = sk
	for side in ["Left", "Right"]:
		for suffix in ["UpperArm", "LowerArm", "Hand", "MiddleProximal"]:
			if sk.find_bone(side + suffix) < 0:
				return false
	for name in ["Hips", "Spine", "Chest", "UpperChest"]:
		if sk.find_bone(name)<0:return false
	var shoulder := sk.get_bone_global_rest(sk.find_bone("LeftUpperArm")).origin
	var elbow := sk.get_bone_global_rest(sk.find_bone("LeftLowerArm")).origin
	_scale = shoulder.distance_to(elbow) / 0.1765752
	if _scale<0.01 or not is_finite(_scale):return false
	var points: Array[Vector3] = []
	for item in model.find_children("*", "MeshInstance3D", true, false):
		var mesh := item as MeshInstance3D
		for surface in mesh.mesh.get_surface_count():
			var mat := mesh.mesh.surface_get_material(surface)
			if mat == null or not "Tops_01_CLOTH_01" in mat.resource_name:
				continue
			var arrays := mesh.mesh.surface_get_arrays(surface)
			var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var binds: PackedInt32Array = arrays[Mesh.ARRAY_BONES]
			var weights: PackedFloat32Array = arrays[Mesh.ARRAY_WEIGHTS]
			var stride := weights.size() / vertices.size()
			var transform := _relative(mesh, sk)
			for vi in vertices.size():
				var arm_weight := 0.0
				for k in stride:
					var bone := _bind_bone(mesh.skin, binds[vi*stride+k])
					if bone >= 0:
						var bn := String(sk.get_bone_name(bone))
						if "Arm" in bn or "Hand" in bn or "Shoulder" in bn:
							arm_weight += weights[vi*stride+k]
				var p := transform * vertices[vi]
				if arm_weight < 0.35 and absf(p.x) < 0.26 * _scale:
					points.append(p)
	if points.size() < 30:
		return false
	var low := INF
	for p in points: low = minf(low, p.y)
	var top := shoulder.y - 0.025 * _scale
	var rings: Array[Dictionary] = []
	for ri in 21:
		var y := lerpf(low, top, ri / 20.0)
		var near := points.duplicate()
		near.sort_custom(func(a: Vector3,b: Vector3) -> bool: return absf(a.y-y) < absf(b.y-y))
		var mn := Vector3(INF, y, INF)
		var mx := Vector3(-INF, y, -INF)
		for j in mini(36, near.size()):
			var p: Vector3 = near[j]
			mn.x=minf(mn.x,p.x);mn.z=minf(mn.z,p.z)
			mx.x=maxf(mx.x,p.x);mx.z=maxf(mx.z,p.z)
		rings.append({"y":y,"x":(mn.x+mx.x)*0.5,"z":(mn.z+mx.z)*0.5,
			"rx":maxf((mx.x-mn.x)*0.5,0.04*_scale)+0.003*_scale,
			"rz":maxf((mx.z-mn.z)*0.5,0.035*_scale)+0.003*_scale})
	_nodes=Node3D.new();_nodes.name="CoatArmClearance";sk.add_child(_nodes)
	var spine_y := sk.get_bone_global_rest(sk.find_bone("Spine")).origin.y
	var chest_y := sk.get_bone_global_rest(sk.find_bone("Chest")).origin.y
	var bands := [["Hips", low, spine_y+0.015*_scale], ["Spine", spine_y-0.015*_scale,chest_y+0.015*_scale], ["UpperChest",chest_y-0.015*_scale,top]]
	for band in bands:
		var index := sk.find_bone(band[0])
		if index < 0:continue
		var subset: Array[Dictionary] = []
		subset.append(_ring(rings,band[1]))
		for ring in rings:
			if ring.y > band[1] and ring.y < band[2]:subset.append(ring)
		subset.append(_ring(rings,band[2]))
		var shape := ConvexPolygonShape3D.new()
		var vertices := PackedVector3Array()
		for ring in subset:
			for i in 24:
				var angle := TAU*i/24.0
				vertices.append(Vector3(ring.x+ring.rx*signf(cos(angle))*sqrt(absf(cos(angle))),ring.y,ring.z+ring.rz*signf(sin(angle))*sqrt(absf(sin(angle)))))
		shape.points=vertices
		var area := Area3D.new();area.name="Coat_"+String(band[0]);area.collision_layer=1<<19;area.collision_mask=0;area.monitoring=false;area.monitorable=false
		var collision := CollisionShape3D.new();collision.shape=shape;area.add_child(collision);_nodes.add_child(area)
		volumes.append({"bone":index,"rest_inverse":sk.get_bone_global_rest(index).affine_inverse(),"rings":subset,"node":area})
	for side in ["Left","Right"]:
		var arm := {"side":side,"upper":sk.find_bone(side+"UpperArm"),"lower":sk.find_bone(side+"LowerArm"),"hand":sk.find_bone(side+"Hand"),"offset":Vector3.ZERO,"pole_offset":Vector3.ZERO,"probes":[]}
		for t in [0.35,0.65,0.9]:arm.probes.append({"type":"forearm","t":t,"radius":0.014*_scale})
		arm.probes.append({"type":"bone","bone":arm.hand,"radius":0.018*_scale})
		arm.probes.append({"type":"palm","bone":sk.find_bone(side+"MiddleProximal"),"radius":0.022*_scale})
		for finger in ["Thumb","Index","Middle","Ring","Little"]:
			for joint in ["Proximal","Intermediate","Distal"]:
				var finger_bone := sk.find_bone(side+finger+joint)
				if finger_bone>=0:arm.probes.append({"type":"bone","bone":finger_bone,"radius":0.009*_scale})
			var suffix := "Distal"
			var bone := sk.find_bone(side+finger+suffix)
			var parent := sk.get_bone_parent(bone) if bone>=0 else -1
			if bone>=0:arm.probes.append({"type":"tip","bone":bone,"parent":parent,"radius":0.009*_scale})
		for probe in arm.probes:
			var area := Area3D.new();area.name=side+"Probe";area.collision_layer=0;area.collision_mask=1<<19;area.monitoring=false;area.monitorable=false
			var collision:=CollisionShape3D.new();var sphere:=SphereShape3D.new();sphere.radius=probe.radius;collision.shape=sphere;area.add_child(collision);_nodes.add_child(area);probe["node"]=area
		arms.append(arm)
	_ready=true
	_update_volumes()
	diagnostics={"fitted_vertices":points.size(),"coat_rings":rings,"volume_count":volumes.size(),"probe_count":arms[0].probes.size()*2}
	return true

func _relative(node: Node3D, sk: Skeleton3D) -> Transform3D:
	# setup also runs before the model enters the SceneTree.
	var a:=Transform3D.IDENTITY;var n:Node=node
	while n!=null:
		if n is Node3D:a=(n as Node3D).transform*a
		n=n.get_parent()
	var b:=Transform3D.IDENTITY;n=sk
	while n!=null:
		if n is Node3D:b=(n as Node3D).transform*b
		n=n.get_parent()
	return b.affine_inverse()*a

func _bind_bone(skin: Skin, index: int) -> int:
	if skin==null or index<0 or index>=skin.get_bind_count():return -1
	var bn:=skin.get_bind_name(index)
	return skeleton.find_bone(bn) if bn!=&"" else skin.get_bind_bone(index)

func _ring(rings: Array[Dictionary], y: float) -> Dictionary:
	if y<=rings[0].y:return rings[0].duplicate()
	for i in range(1,rings.size()):
		if y<=rings[i].y:
			var a:Dictionary=rings[i-1];var b:Dictionary=rings[i];var t:=inverse_lerp(a.y,b.y,y);var out:Dictionary={}
			for key in ["y","x","z","rx","rz"]:out[key]=lerpf(a[key],b[key],t)
			return out
	return rings[-1].duplicate()

func _update_volumes() -> void:
	for volume in volumes:
		volume["transform"]=skeleton.get_bone_global_pose(volume.bone)*volume.rest_inverse
		volume["inverse"]=volume.transform.affine_inverse()
		volume.node.transform=volume.transform

func _probe_position(arm: Dictionary, probe: Dictionary) -> Vector3:
	var w:=skeleton.get_bone_global_pose(arm.hand).origin
	if probe.type=="forearm":return skeleton.get_bone_global_pose(arm.lower).origin.lerp(w,probe.t)
	var p:=skeleton.get_bone_global_pose(probe.bone).origin
	if probe.type=="palm":return w.lerp(p,0.65)
	if probe.type=="tip" and probe.parent>=0:
		var previous:=skeleton.get_bone_global_pose(probe.parent).origin
		return p+(p-previous).normalized()*0.013*_scale
	return p

# Rounded-rectangular (power4 superellipse) cross-sections enclose the visible coat.
# Queries are analytic for deterministic post-pose solving; the matching Area3D shapes
# provide inspectable/debuggable volumes, not callbacks that fight animation playback.
func _push(point: Vector3, radius: float, side: String) -> Vector3:
	var best:=Vector3.ZERO
	for volume in volumes:
		var p:Vector3=volume.inverse*point;var rings:Array[Dictionary]=volume.rings
		if p.y<rings[0].y-radius or p.y>rings[-1].y+radius:continue
		var ring:=_ring(rings,p.y);var rx:float=ring.rx+radius+0.002*_scale;var rz:float=ring.rz+radius+0.002*_scale
		var dx:float=p.x-ring.x;var dz:float=p.z-ring.z
		var norm:=pow(pow(absf(dx/rx),4)+pow(absf(dz/rz),4),0.25)
		if norm>=1:continue
		var displacement:Vector3
		if norm<0.0001:displacement=Vector3(rx if side=="Left" else -rx,0,0)
		else:displacement=Vector3(dx/norm-dx,0,dz/norm-dz)
		var result:Vector3=volume.transform.basis*displacement
		if result.length_squared()>best.length_squared():best=result
	return best

func penetration_report() -> Dictionary:
	if not _ready:return {"count":0,"max_m":0.0}
	_update_volumes();var count:=0;var deepest:=0.0
	for arm in arms:
		for probe in arm.probes:
			var p:=_probe_position(arm,probe);var depth:=_push(p,probe.radius,arm.side).length()
			if depth>0.0002*_scale:count+=1;deepest=maxf(deepest,depth)
	return {"count":count,"max_m":deepest}

func apply(delta: float) -> void:
	if not _ready:return
	for child in skeleton.get_children():
		if child is PhysicalBoneSimulator3D and child.is_simulating_physics():
			for arm in arms:arm.offset=Vector3.ZERO;arm.pole_offset=Vector3.ZERO
			return
	if not enabled:
		for arm in arms:arm.offset=Vector3.ZERO;arm.pole_offset=Vector3.ZERO
		return
	_update_volumes()
	for arm in arms:
		var u:int=arm.upper;var l:int=arm.lower;var h:int=arm.hand
		var rotations: Array[Quaternion]=[skeleton.get_bone_pose_rotation(u),skeleton.get_bone_pose_rotation(l),skeleton.get_bone_pose_rotation(h)]
		var shoulder:=skeleton.get_bone_global_pose(u).origin
		var elbow:=skeleton.get_bone_global_pose(l).origin
		var wrist:=skeleton.get_bone_global_pose(h).origin
		var hand_rotation:=skeleton.get_bone_global_pose(h).basis.get_rotation_quaternion()
		var desired:=Vector3.ZERO;var pole:=Vector3.ZERO
		for iteration in 8:
			var request:=_request(arm)
			if request.push.length()<0.0003*_scale:break
			desired=(desired+request.push).limit_length(max_offset*_scale)
			pole=(pole+request.pole).limit_length(0.08*_scale)
			_solve(arm,shoulder,elbow,wrist+desired,hand_rotation,pole)
		for i in 3:skeleton.set_bone_pose_rotation([u,l,h][i],rotations[i])
		var speed:=smoothing_speed if desired.length()>arm.offset.length() else release_speed
		var weight:=1.0 if delta<=0 else 1.0-exp(-maxf(delta,0.0)*speed)
		arm.offset=arm.offset.lerp(desired,weight);arm.pole_offset=arm.pole_offset.lerp(pole,weight)
		if arm.offset.length()<0.00001 and arm.pole_offset.length()<0.00001:
			continue
		_solve(arm,shoulder,elbow,wrist+arm.offset,hand_rotation,arm.pole_offset)
		# Project the blended pose back onto the safe side; release smoothing cannot re-enter cloth.
		for iteration in 8:
			var request:=_request(arm)
			if request.push.length()<0.0003*_scale:break
			arm.offset=(arm.offset+request.push).limit_length(max_offset*_scale)
			arm.pole_offset=(arm.pole_offset+request.pole).limit_length(0.08*_scale)
			_solve(arm,shoulder,elbow,wrist+arm.offset,hand_rotation,arm.pole_offset)
		for probe in arm.probes:probe.node.position=_probe_position(arm,probe)

func _request(arm: Dictionary) -> Dictionary:
	var best:=Vector3.ZERO;var pole:=Vector3.ZERO
	for probe in arm.probes:
		var push:=_push(_probe_position(arm,probe),probe.radius,arm.side)
		var t:float=probe.get("t",1.0)
		var request:=push/maxf(t,0.45)
		if request.length_squared()>best.length_squared():best=request;pole=push*(1.0-t)*1.5
	return {"push":best,"pole":pole}

# Analytical two-bone IK changes rotations only, keeping bone lengths intact.
# The animation elbow supplies the bend plane and the wrist keeps its world orientation.
func _solve(arm: Dictionary, shoulder: Vector3, elbow: Vector3, target: Vector3, hand_rotation: Quaternion, pole_offset: Vector3) -> void:
	var u:int=arm.upper;var l:int=arm.lower;var h:int=arm.hand
	var first:=skeleton.get_bone_rest(l).origin.length()
	var second:=skeleton.get_bone_rest(h).origin.length()
	var ray:=target-shoulder
	if ray.length()<0.00001:return
	var distance:=clampf(ray.length(),absf(first-second)+0.00001,first+second-0.00001)
	var direction:=ray.normalized();var along:=(first*first-second*second+distance*distance)/(2.0*distance)
	var height:=sqrt(maxf(first*first-along*along,0.0))
	var bend:=elbow+pole_offset-shoulder;var pole:=bend-direction*bend.dot(direction)
	if pole.length()<0.00001:pole=direction.cross(Vector3.FORWARD)
	if pole.length()<0.00001:pole=direction.cross(Vector3.UP)
	var wanted_elbow:=shoulder+direction*along+pole.normalized()*height
	_aim(u,skeleton.get_bone_global_pose(l).origin-shoulder,wanted_elbow-shoulder)
	var actual_elbow:=skeleton.get_bone_global_pose(l).origin
	_aim(l,skeleton.get_bone_global_pose(h).origin-actual_elbow,shoulder+direction*distance-actual_elbow)
	_set_global_rotation(h,hand_rotation)

func _aim(index: int, from: Vector3, to: Vector3) -> void:
	if from.length_squared()<1e-10 or to.length_squared()<1e-10:return
	var rotation:=skeleton.get_bone_global_pose(index).basis.get_rotation_quaternion()
	_set_global_rotation(index,(Quaternion(from.normalized(),to.normalized())*rotation).normalized())

func _set_global_rotation(index: int, rotation: Quaternion) -> void:
	var parent:=skeleton.get_bone_parent(index)
	var parent_rotation:=skeleton.get_bone_global_pose(parent).basis.get_rotation_quaternion() if parent>=0 else Quaternion.IDENTITY
	skeleton.set_bone_pose_rotation(index,(parent_rotation.inverse()*rotation).normalized())
