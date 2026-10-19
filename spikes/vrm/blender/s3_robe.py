"""Step 3: a first white robe with a deep hood, generated around the base's own body.

No cloth sim: the robe is a lofted shell. For each column (angle around her vertical axis)
and row (height) it takes the farthest body vertex in that bin, adds a margin, merges the
legs into one skirt that flares to the ankles, adds soft folds, and cuts the top along a
diagonal so the left shoulder is bare (toga-style). The hood is a shell shrink-wrapped
over the head and hair, open in front, with a cowl that drapes onto the shoulders.
Both copy skin weights from the nearest body vertex, so they follow the rig.

The sample's T-shirt and shorts are removed; shoes are hidden under the hem.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, kdtree  # noqa: E402

import rlib  # noqa: E402

P = rlib.PALETTE
REMOVE = ("Tops_01_CLOTH", "Bottoms_01_CLOTH")
FACE_R_BASE = 0.203  # farthest Face vertex from the head bone on the pixiv base


def world_verts(obj):
    m = np.array(obj.matrix_world)
    co = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return co @ m[:3, :3].T + m[:3, 3]


def remove_material_faces(obj, names):
    idx = {i for i, m in enumerate(obj.data.materials) if m and m.name in names}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in idx], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()


def smooth_grid(r, it=3, wrap_cols=True):
    for _ in range(it):
        a = r.copy()
        if wrap_cols:
            a[:, :] = (np.roll(r, 1, 1) + np.roll(r, -1, 1) + 2 * r) / 4
        b = a.copy()
        b[1:-1] = (a[:-2] + a[2:] + 2 * a[1:-1]) / 4
        r = b
    return r


def fill_empty(r):
    """Fill empty bins (0) from the nearest filled bin in the same row."""
    for i in range(r.shape[0]):
        row = r[i]
        ok = np.nonzero(row > 0)[0]
        if len(ok) == 0:
            continue
        n = len(row)
        idx = np.arange(n)
        xp = np.concatenate([ok - n, ok, ok + n])
        fp = np.concatenate([row[ok]] * 3)
        r[i] = np.interp(idx, xp, fp)
    return r


def grid_mesh(name, pts, closed_cols=True, keep=None):
    """pts: (rows, cols, 3). keep(row, col) -> bool for each quad."""
    rows, cols, _ = pts.shape
    verts = pts.reshape(-1, 3)
    faces = []
    for i in range(rows - 1):
        for j in range(cols if closed_cols else cols - 1):
            j2 = (j + 1) % cols
            if keep and not keep(i, j):
                continue
            faces.append((i * cols + j, i * cols + j2, (i + 1) * cols + j2, (i + 1) * cols + j))
    obj = rlib.mesh_from(name, verts, faces)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def uv_from_grid(obj, rows, cols):
    """Cylindrical/spherical UVs from each vertex's grid position, stored in a layer."""
    me = obj.data
    uv = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        v = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (0.5 + math.atan2(v.x, -v.y) / (2 * math.pi), v.z)


def copy_weights(dst, src, src_co, blend=None, src_idx=None):
    """Give each dst vertex the weights of the nearest src vertex; blend(z) -> {bone: w}."""
    kd = kdtree.KDTree(len(src_co))
    for i, c in enumerate(src_co):
        kd.insert(c, i)
    kd.balance()
    names = {g.index: g.name for g in src.vertex_groups}
    groups = {}
    for v in dst.data.vertices:
        co = dst.matrix_world @ v.co
        _, i, _ = kd.find(co)
        i = int(src_idx[i]) if src_idx is not None else i
        w = {names[g.group]: g.weight for g in src.data.vertices[i].groups if g.weight > 0.001}
        if blend:
            extra, s = blend(co)
            w = {k: x * (1 - s) for k, x in w.items()}
            for k, x in extra.items():
                w[k] = w.get(k, 0) + x * s
        tot = sum(w.values()) or 1
        for k, x in w.items():
            if k not in groups:
                groups[k] = dst.vertex_groups.get(k) or dst.vertex_groups.new(name=k)
            groups[k].add([v.index], x / tot, "REPLACE")


def bind(obj, arm):
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    obj.modifiers.new("Armature", "ARMATURE").object = arm


def robe_material():
    m = rlib.toon_material("Robe_00_CLOTH", P["white"], P["cloth_shadow"])
    mt = rlib.mtoon(m)
    mt.double_sided = True
    ext = mt.extensions.vrmc_materials_mtoon
    ext.shading_toony_factor = 0.85
    ext.shading_shift_factor = -0.05
    ext.outline_width_mode = "worldCoordinates"
    ext.outline_width_factor = 0.0015
    ext.outline_color_factor = rlib.lin("#8A93AC")
    return m


def build_robe(arm, body, co, mat, hair_co):
    b = lambda n: rlib.bone_head(arm, n)  # noqa: E731
    z_hips = b("J_Bip_C_Hips").z
    z_knee = b("J_Bip_L_LowerLeg").z
    z_ankle = b("J_Bip_L_Foot").z
    z_shoulder = b("J_Bip_L_UpperArm").z
    x_shoulder = abs(b("J_Bip_L_UpperArm").x)
    z_armpit = z_shoulder - 0.07
    z_bottom = 0.012  # floor length: hides the shoes, she is barefoot under it

    # torso + legs only: drop the T-posed arms
    keep = (co[:, 2] < z_armpit - 0.02) | (np.abs(co[:, 0]) < x_shoulder * 0.92)
    keep &= co[:, 2] > z_bottom - 0.05
    pts = co[keep]
    # back hair (below the hood, above the hips) goes under the robe, so the robe must enclose it
    hz = hair_co[:, 2]
    hair_back = hair_co[(hz > z_hips) & (hz < z_shoulder) & (np.abs(hair_co[:, 0]) < x_shoulder * 0.9) & (hair_co[:, 1] > np.median(pts[:, 1]) + 0.02)]
    sample = np.concatenate([pts, hair_back])

    rows, cols = 44, 64
    ang = np.linspace(-math.pi, math.pi, cols, endpoint=False)
    # top edge: high over the right shoulder (-X in Blender), low under the left armpit (+X)
    side = np.cos(ang)  # +1 at +X (her left), -1 at -X (her right)
    z_top = np.interp(side, [-1, -0.3, 1], [z_shoulder + 0.035, z_shoulder - 0.005, z_armpit - 0.06])
    t = np.linspace(0, 1, rows)[:, None]
    z = z_bottom + t * (z_top[None, :] - z_bottom)

    # axis centre per height band (legs and torso aren't centred on y=0)
    def centre_y(zz):
        sel = np.abs(pts[:, 2] - zz) < 0.04
        return pts[sel, 1].mean() if sel.any() else 0.0

    r = np.zeros((rows, cols))
    cy = np.zeros((rows, cols))
    for i in range(rows):
        for j in range(cols):
            zz = z[i, j]
            cy[i, j] = centre_y(zz)
        band = np.abs(sample[:, 2][:, None] - z[i][None, :]) < 0.03  # (n, cols)
        dx, dy = sample[:, 0], sample[:, 1] - cy[i].mean()
        a_pts = np.arctan2(dy, dx)
        rad = np.hypot(dx, dy)
        jj = ((a_pts + math.pi) / (2 * math.pi) * cols).astype(int) % cols
        for j in range(cols):
            sel = band[:, j] & (jj == j)
            if sel.any():
                r[i, j] = rad[sel].max()
    r = fill_empty(r)
    cy_row = cy.mean(axis=1)

    # skirt: never narrower than the hip ring, flaring towards the hem; adds soft folds
    i_hips = int(np.argmin(np.abs(z[:, 0] - (z_hips - 0.06))))
    hip_ring = r[i_hips].copy()
    for i in range(i_hips):
        s = float(np.clip((z[i_hips, 0] - z[i, 0]) / (z[i_hips, 0] - z_bottom), 0, 1))
        r[i] = np.maximum(r[i], hip_ring * (1 + 0.42 * s))
        cy_row[i] = cy_row[i_hips]
    r = smooth_grid(r, 4)
    r += 0.014
    down = np.clip((z_knee + 0.15 - z) / (z_knee + 0.15 - z_bottom), 0, 1)
    folds = 0.018 * down * (np.sin(7 * ang + 0.6)[None, :] + 0.5 * np.sin(13 * ang + 1.7)[None, :])
    # a drape line from the right shoulder across the chest
    diag = np.exp(-((z - (z_armpit - 0.10 + 0.08 * (-side[None, :]))) / 0.05) ** 2) * 0.008
    r += folds + diag

    grid = np.stack([np.cos(ang)[None, :] * r, cy_row[:, None] + np.sin(ang)[None, :] * r, z], axis=-1)
    robe = grid_mesh("Robe", grid)
    rlib.assign(robe, mat)
    uv_from_grid(robe, rows, cols)

    def blend(c):
        if c.z >= z_hips - 0.02:
            return {}, 0.0
        s = min(1.0, (z_hips - c.z) / (z_hips - z_knee)) * 0.75
        return {"J_Bip_C_Hips": 1.0}, s

    # weights from torso and legs only: arms are bare, so the robe must not follow them
    copy_weights(robe, body, pts, blend, src_idx=np.nonzero(keep)[0])
    bind(robe, arm)
    return robe


def build_hood(arm, head_pts, mat, co_body, body):
    b = lambda n: rlib.bone_head(arm, n)  # noqa: E731
    head, top = b("J_Bip_C_Head"), b("J_Bip_C_Head_end")
    neck = b("J_Bip_C_Neck")
    c = head.lerp(top, 0.42) + Vector((0, 0.012, 0))
    d = head_pts - np.array(c)
    rad = np.linalg.norm(d, axis=1)
    az = np.arctan2(d[:, 0], -d[:, 1])  # 0 = straight ahead (-Y)
    el = np.arcsin(np.clip(d[:, 2] / np.maximum(rad, 1e-6), -1, 1))

    rows, cols = 26, 64
    els = np.linspace(-0.95, math.pi / 2 - 0.02, rows)
    azs = np.linspace(-math.pi, math.pi, cols, endpoint=False)
    r = np.zeros((rows, cols))
    ei = np.clip(((el + 0.95) / (math.pi / 2 + 0.93) * (rows - 1)).round().astype(int), 0, rows - 1)
    ai = ((az + math.pi) / (2 * math.pi) * cols).astype(int) % cols
    for i, j, x in zip(ei, ai, rad):
        if x > r[i, j]:
            r[i, j] = x
    r = fill_empty(r)
    r[r == 0] = r[r > 0].mean()
    r = smooth_grid(np.maximum(r, np.percentile(r[r > 0], 35)), 3)
    r += 0.038
    r *= 1.0 + 0.16 * np.clip(-np.cos(azs), 0, 1)[None, :]  # roomier at the back, like cloth
    # point at the crown, pulled back
    r += 0.05 * np.exp(-((els[:, None] - 1.1) / 0.3) ** 2) * np.clip(-np.cos(azs), 0, 1)[None, :]

    E, A = np.meshgrid(els, azs, indexing="ij")
    pts = np.stack([np.sin(A) * np.cos(E) * r, -np.cos(A) * np.cos(E) * r, np.sin(E) * r], -1) + np.array(c)

    # cowl: 5 more rows from the lowest ring, flaring out and down onto the shoulders
    low = pts[0]
    sh = b("J_Bip_L_UpperArm")
    # the hem of the cowl: an ellipse around the neck that rests on the shoulders
    hem = np.stack([np.sin(azs) * (abs(sh.x) + 0.035), neck.y - np.cos(azs) * (0.13 - 0.025 * np.cos(azs)),
                    np.full(cols, sh.z + 0.025) + 0.02 * np.cos(azs) ** 2], -1)
    cowl = []
    for k in range(1, 6):
        s = k / 5
        out = low + (hem - low) * s
        out[:, 2] += 0.035 * math.sin(math.pi * s)  # bulge over the collarbone instead of a straight cone
        cowl.append(out)
    pts = np.concatenate([np.array(cowl[::-1]), pts], 0)
    rows2 = pts.shape[0]
    els_all = np.concatenate([np.full(5, -1.3), els])

    def keep(i, j):
        e = (els_all[i] + els_all[min(i + 1, rows2 - 1)]) / 2
        a = abs((azs[j] + azs[(j + 1) % cols]) / 2) if j != cols - 1 else math.pi
        # the face opening: wide at eye level, rounded at the brow, open down to the chest
        ea = max(0.0, e - 0.02) / 0.55
        return (a / 0.78) ** 2 + ea ** 2 > 1.0

    hood = grid_mesh("Hood", pts, keep=keep)
    rlib.assign(hood, mat)
    uv_from_grid(hood, rows2, cols)

    def blend(co):
        s = float(np.clip((co.z - (neck.z - 0.02)) / (c.z - neck.z), 0, 1))
        return ({"J_Bip_C_Head": s, "J_Bip_C_UpperChest": 1 - s}, 1.0)

    copy_weights(hood, body, co_body, blend)
    bind(hood, arm)
    return hood


def run():
    arm = rlib.armature()
    body = bpy.data.objects["Body"]
    remove_material_faces(body, REMOVE)
    co = world_verts(body)
    mat = robe_material()
    robe = build_robe(arm, body, co, mat, world_verts(bpy.data.objects["Hair"]))
    head_z = rlib.bone_head(arm, "J_Bip_C_Neck").z + 0.02
    hp = [world_verts(o) for o in (bpy.data.objects["Hair"], bpy.data.objects["Face"])]
    hp.append(co)
    hp = np.concatenate(hp)
    c_head = rlib.bone_head(arm, "J_Bip_C_Head")
    # head region only: the long hair below the jaw falls out of the hood
    # 0.24 m on the base; scaled by the face's size so the chibi's bigger head works too
    face_r = np.linalg.norm(world_verts(bpy.data.objects["Face"]) - np.array(c_head), axis=1).max()
    hp = hp[(hp[:, 2] > head_z) & (np.linalg.norm(hp - np.array(c_head), axis=1) < 0.24 * face_r / FACE_R_BASE)]
    hood = build_hood(arm, hp, mat, co, body)
    print(f"RAPHAEL robe verts={len(robe.data.vertices)} hood verts={len(hood.data.vertices)}")


if __name__ == "__main__":
    a = rlib.args()
    rlib.load_vrm(a[0] if a else rlib.EXPORT + "raphael_s2.vrm")
    run()
    rlib.export(a[1] if len(a) > 1 else "raphael_s3_robe")
