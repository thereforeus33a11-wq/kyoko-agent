"""Restyle the rigged "Huna" character .blend to match the rebel reference look.

Run with Blender 4.1 / 4.2 (or the matching `bpy` module):

    blender -b input.blend -P restyle.py -- output.blend

What it changes (everything stays rigged; new props are bone-parented):
  * skin      -> warm tan (tint node inside the shared "Skin Shader" group)
  * eyes      -> smaller dark-red irises painted into the head texture; eye
                 corners, lids and lips re-posed (sharper eyes, thinner lips,
                 neutral expression)
  * make-up   -> blush toned down, deeper lipstick, long red nails (rig props)
  * hair      -> adds the antenna strand ("ahoge") on the crown
  * outfit    -> sailor top turned into an open, long-sleeved white shirt knotted
                 under the bust over a black lettered bandeau; skirt recoloured
                 navy with a white hem stripe, white belt and gold heart buckle
                 and dropped to the hips; navy thigh-highs with a white band
  * jewellery -> black choker with a printed wavy line, gold hoop earrings,
                 gold navel ring, gold lip and tongue barbells, black leather
                 cuff on the left wrist
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None

TAN = (0.88, 0.64, 0.44, 1.0)        # multiplied over the skin albedo
NAIL_RED = (0.55, 0.0, 0.01, 1.0)
LIP_PINK = (0.75, 0.25, 0.25, 1.0)
IRIS_DARK = (0.20, 0.0, 0.01)
IRIS_LIGHT = (0.70, 0.03, 0.04)
SKIRT_DROP = 0.055                   # metres
SKIRT_LENGTH = 0.78                  # fraction of the original pleat length
PLEATS = 12
NAVY = (0.018, 0.030, 0.075, 1.0)
WHITE = (0.80, 0.80, 0.82, 1.0)
HERE = os.path.dirname(os.path.abspath(__file__))

scene = bpy.context.scene
arm = bpy.data.objects["_Armature"]
body = bpy.data.objects["Body"]


# ---------------------------------------------------------------- helpers
def make_mat(name, color, metallic=0.0, rough=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    m.diffuse_color = color
    return m


def new_obj(name, mesh, coll, mat, smooth=True):
    o = bpy.data.objects.new(name, mesh)
    coll.objects.link(o)
    mesh.materials.append(mat)
    if smooth:
        for p in mesh.polygons:
            p.use_smooth = True
    return o


def bone_parent(o, bone):
    """Parent to a bone of the main armature, keeping the world position."""
    mw = o.matrix_world.copy()
    o.parent = arm
    o.parent_type = "BONE"
    o.parent_bone = bone
    bpy.context.view_layer.update()
    o.matrix_world = mw


def torus(name, center, major, minor, axis, coll, mat, seg=40, ring=10):
    """Torus whose hole points along `axis`."""
    bm = bmesh.new()
    rot = Vector((0, 0, 1)).rotation_difference(Vector(axis).normalized()).to_matrix()
    vs = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        row = []
        for j in range(ring):
            b = 2 * math.pi * j / ring
            r = major + minor * math.cos(b)
            p = Vector((r * math.cos(a), r * math.sin(a), minor * math.sin(b)))
            row.append(bm.verts.new(rot @ p + Vector(center)))
        vs.append(row)
    for i in range(seg):
        for j in range(ring):
            bm.faces.new((vs[i][j], vs[(i + 1) % seg][j],
                          vs[(i + 1) % seg][(j + 1) % ring], vs[i][(j + 1) % ring]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return new_obj(name, me, coll, mat)


def band(name, rings, coll, mat, thickness):
    """Closed strip through a list of point loops (each loop same length)."""
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in loop] for loop in rings]
    n = len(rings[0])
    for a in range(len(rings) - 1):
        for i in range(n):
            bm.faces.new((vs[a][i], vs[a][(i + 1) % n], vs[a + 1][(i + 1) % n], vs[a + 1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = new_obj(name, me, coll, mat)
    s = o.modifiers.new("Solidify", "SOLIDIFY")
    s.thickness = thickness
    s.offset = 1.0
    return o


def barbell(name, p0, p1, ball, bar, coll, mat):
    """Straight bar from p0 to p1 with a ball on each end."""
    p0, p1 = Vector(p0), Vector(p1)
    bm = bmesh.new()
    for p in (p0, p1):
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=ball, matrix=Matrix.Translation(p))
    rot = Vector((0, 0, 1)).rotation_difference((p1 - p0).normalized()).to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=bar, radius2=bar, depth=(p1 - p0).length,
                          matrix=Matrix.Translation((p0 + p1) / 2) @ rot)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return new_obj(name, me, coll, mat)


def bone_pt(name, tail=False):
    """Bone end in world space, as posed (the rig's default pose is not its rest pose)."""
    b = arm.pose.bones[name]
    return arm.matrix_world @ (b.tail if tail else b.head)


# ---------------------------------------------------------------- collections
uniform = bpy.data.collections["School Uniform"]
uniform.hide_render = uniform.hide_viewport = False
acc = bpy.data.collections.new("Rebel Accessories")
bpy.data.collections["Clothes"].children.link(acc)

gold = make_mat("Rebel Gold", (0.83, 0.55, 0.16, 1), metallic=1.0, rough=0.22)
steel = make_mat("Rebel Steel", (0.75, 0.75, 0.78, 1), metallic=1.0, rough=0.25)
leather = make_mat("Rebel Black Leather", (0.012, 0.012, 0.014, 1), rough=0.42)
cotton = make_mat("Rebel White Shirt", (0.86, 0.86, 0.88, 1), rough=0.8)
cotton.use_backface_culling = False

# ---------------------------------------------------------------- skin tone
grp = bpy.data.node_groups["Skin Shader"]
gamma = next(n for n in grp.nodes if n.type == "GAMMA")
tint = grp.nodes.new("ShaderNodeMix")
tint.name = tint.label = "Rebel Tan"
tint.data_type = "RGBA"
tint.blend_type = "MULTIPLY"
tint.inputs[0].default_value = 1.0
tint.inputs[7].default_value = TAN
tint.location = (gamma.location.x + 20, gamma.location.y - 160)
for link in list(gamma.outputs[0].links):
    grp.links.new(tint.outputs[2], link.to_socket)
grp.links.new(gamma.outputs[0], tint.inputs[6])

# ---------------------------------------------------------------- rig-driven make-up
props = arm.pose.bones["Properties"]


def setp(key, val):
    if key not in props.keys():
        print("  (rig has no property %r, skipped)" % key)
        return
    cur = props[key]
    if hasattr(cur, "__len__") and not isinstance(cur, str):
        seq = list(val) if hasattr(val, "__len__") else [val] * len(cur)
        props[key] = seq[: len(cur)]
    else:
        props[key] = val


setp("2. Nails Length", 1.0)
setp("2. Nails Color", NAIL_RED)
setp("2. Nails Color Opacity", 1.0)
setp("2. Blush", 0.12)
setp("2. Lipstick", 0.22)
setp("2. Lipstick Color", LIP_PINK)

wardrobe = arm.pose.bones["Clothes 2"]
wardrobe["1. Bra"] = 4                    # no optional top (0-2 pick one), the bandeau replaces it
wardrobe["3. Stockings"] = 4              # no optional stockings (0-2 pick one of the three sets)
wardrobe["4. Color Base"] = list(WHITE)
# swap the bikini bottom for the thong: read which value of the switch shows it
import re
for fc in bpy.data.objects["Thong_01"].animation_data.drivers:
    if fc.data_path == "hide_render":
        found = re.search(r"==\s*(\d+)", fc.driver.expression)
        print("thong driver:", fc.driver.expression)
        if found:
            wardrobe["3. Bottom"] = int(found.group(1))

# ---------------------------------------------------------------- eyes
img = bpy.data.images["T_F_Std_Head_D.png"]
w, h = img.size
px = np.empty(w * h * 4, dtype=np.float32)
img.pixels.foreach_get(px)
px = px.reshape(h, w, 4)
# the two eyeballs sit on a white patch in the top-right corner of the sheet
x0, y0 = int(w * 0.885), int(h * 0.52)
sub = px[y0:, x0:, :3]
dark = sub.max(axis=2) < 0.08
ys, xs = np.nonzero(dark)
mid = (ys.min() + ys.max()) / 2
for sel in (ys < mid, ys >= mid):
    cy, cx = ys[sel].mean(), xs[sel].mean()
    rad = math.sqrt(sel.sum() / math.pi)
    yy, xx = np.mgrid[0:sub.shape[0], 0:sub.shape[1]]
    d = np.hypot(yy - cy, xx - cx) / rad
    # smaller, darker iris: black pupil, maroon ring brightening toward the lower rim, dark outline
    IR = 0.80
    sclera = np.array((0.80, 0.79, 0.76))
    ring = (d >= IR) & (d < 1.05)
    sub[ring] = sclera
    iris = (d > 0.34) & (d < IR)
    t = np.clip((d - 0.34) / (IR - 0.34), 0, 1)[..., None]
    col = np.array(IRIS_DARK) * (1 - t) + np.array(IRIS_LIGHT) * t
    col = np.where(t > 0.88, np.array(IRIS_DARK), col)
    sub[iris] = col[iris]
img.pixels.foreach_set(px.ravel())
img.update()
img.pack()

# soften the mirror-like eyeball reflection so the new iris colour reads
for node in bpy.data.materials["MI_Base_Eyes"].node_tree.nodes:
    if node.type == "GROUP" and "Rough Min" in node.inputs:
        node.inputs["Rough Min"].default_value = 0.45

# hair: push the red toward the vivid reference colour
hmat = bpy.data.materials["头发"]
hnt = hmat.node_tree
hfx = next(n for n in hnt.nodes if n.type == "GROUP" and "Diffuse" in n.inputs)
src = hfx.inputs["Diffuse"].links[0].from_socket
hsv = hnt.nodes.new("ShaderNodeHueSaturation")
hsv.name = "Rebel Hair Boost"
hsv.inputs["Saturation"].default_value = 1.2
hsv.inputs["Value"].default_value = 1.35
hnt.links.new(src, hsv.inputs["Color"])
hnt.links.new(hsv.outputs["Color"], hfx.inputs["Diffuse"])

# half-lidded stare (rig control: 0 = open, -0.015 = closed); reset it to 0 to undo
arm.pose.bones["Blink Eyes"].location.y = -0.0055

# face shape, set as pose offsets on the facial bones (world-space metres; "her" left/right).
# Clear the pose on these bones to get the original face back.
FACE = {
    # sharper, upturned eyes
    "L_EyeCornerOuter": (0.002, 0, 0.008), "R_EyeCornerOuter": (-0.002, 0, 0.008),
    "L_EyeCornerInner": (0, 0, -0.004), "R_EyeCornerInner": (0, 0, -0.004),
    "L_EyelidLowerA": (0, 0, 0.002), "R_EyelidLowerA": (0, 0, 0.002),
    # thinner lips, slightly wider mouth; expression stays neutral and closed
    "C_LipUpper": (0, 0.003, -0.002), "L_LipUpper": (0, 0.003, -0.002), "R_LipUpper": (0, 0.003, -0.002),
    "C_LipLower": (0, 0.003, 0.002), "L_LipLower": (0, 0.003, 0.002), "R_LipLower": (0, 0.003, 0.002),
    "L_LipsCorner": (0.004, 0, 0.0005), "R_LipsCorner": (-0.004, 0, 0.0005),
}
for bone, off in FACE.items():
    pb = arm.pose.bones[bone]
    bpy.context.view_layer.update()
    m = pb.matrix.copy()
    m.translation = m.translation + Vector(off)
    pb.matrix = m
bpy.context.view_layer.update()

# ---------------------------------------------------------------- body surface lookup
deps = bpy.context.evaluated_depsgraph_get()
bvh = BVHTree.FromObject(body, deps)


def hit(origin, direction, dist=2.0):
    loc, nor, _i, _d = bvh.ray_cast(Vector(origin), Vector(direction).normalized(), dist)
    return loc, nor


def wrap(center, axis, radius_from, n=48):
    """Points on the body surface around `center`, in the plane normal to `axis`."""
    axis = Vector(axis).normalized()
    ref = Vector((0, 1, 0)) if abs(axis.y) < 0.9 else Vector((1, 0, 0))
    u = axis.cross(ref).normalized()      # fixed start direction so stacked loops do not twist
    v = axis.cross(u)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        d = u * math.cos(a) + v * math.sin(a)
        loc, _ = hit(Vector(center) + d * radius_from, -d, radius_from)
        pts.append((loc, d))
    found = [(p - Vector(center)).length for p, _d in pts if p]
    mean = sum(found) / len(found) if found else 0.03
    return [p if p else Vector(center) + d * mean for p, d in pts]


def offset_loop(loop, center, axis, amount):
    axis = Vector(axis).normalized()
    out = []
    for p in loop:
        r = (p - Vector(center))
        r -= axis * r.dot(axis)
        out.append(p + r.normalized() * amount)
    return out


# nearest-vertex skinning so new garments follow the rig like the body does
from mathutils.kdtree import KDTree

def body_verts(keep):
    """Body vertex positions with only the modifier types in `keep` enabled."""
    saved = [(m, m.show_viewport) for m in body.modifiers]
    for m, _ in saved:
        m.show_viewport = m.type in keep
    deps.update()
    out = [body.matrix_world @ v.co for v in body.evaluated_get(deps).data.vertices]
    for m, state in saved:
        m.show_viewport = state
    deps.update()
    return out


rest = body_verts(())                 # shape keys only
posed = body_verts(("ARMATURE",))     # what the renders / ray casts see
unpose = [r - p for r, p in zip(rest, posed)]
kd = KDTree(len(posed))
for i, co in enumerate(posed):
    kd.insert(co, i)
kd.balance()


def skin_to_body(o):
    groups = {}
    for v in o.data.vertices:
        _co, idx, _d = kd.find(v.co)
        v.co += unpose[idx]               # built on the posed body; store it in rest space
        for g in body.data.vertices[idx].groups:
            name = body.vertex_groups[g.group].name
            if name not in arm.data.bones:
                continue
            if name not in groups:
                groups[name] = o.vertex_groups.new(name=name)
            groups[name].add([v.index], g.weight, "REPLACE")
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    o.modifiers.move(len(o.modifiers) - 1, 0)
    o.parent = arm


# ---------------------------------------------------------------- black bandeau with lettering
label = bpy.data.images.load(os.path.join(HERE, "label_bitch.png"))
label.pack()
band_mat = bpy.data.materials.new("Rebel Bandeau")
band_mat.use_nodes = True
tex = band_mat.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = label
bsdf = band_mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.7
band_mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
N = 72
bust_z = (bone_pt("L_Nipple").z + bone_pt("R_Nipple").z) / 2      # centre the band on the bust
levels = [bust_z - 0.040 + 0.016 * k for k in range(6)]
loops = []
for z in levels:
    c = Vector((0, 0.03, z))
    loop = []
    for i in range(N):
        a = 2 * math.pi * (i / N - 0.5)          # a = 0 is straight ahead
        d = Vector((math.sin(a), -math.cos(a), 0))
        loc, _ = hit(c, d, 0.6)
        loop.append(loc + d * 0.002)
    # stretch flat across the cleavage instead of dipping into it
    left = min((p for p in loop if p.x > 0.02), key=lambda p: p.y)
    right = min((p for p in loop if p.x < -0.02), key=lambda p: p.y)
    for p in loop:
        if right.x < p.x < left.x:
            t = (p.x - right.x) / (left.x - right.x)
            p.y = min(p.y, right.y + (left.y - right.y) * t)
    loops.append(loop)
# keep the lettering undistorted: one image tile is as wide as (band height x image aspect)
girth = sum((loops[2][i] - loops[2][(i + 1) % N]).length for i in range(N))
tiles = girth / ((levels[-1] - levels[0]) * label.size[0] / label.size[1])
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
vs = [[bm.verts.new(p) for p in loop] for loop in loops]
for r in range(len(loops) - 1):
    for i in range(N):
        j = (i + 1) % N
        f = bm.faces.new((vs[r][i], vs[r][j], vs[r + 1][j], vs[r + 1][i]))
        f.smooth = True
        for lp, (uu, vv) in zip(f.loops, ((i, r), (i + 1, r), (i + 1, r + 1), (i, r + 1))):
            lp[uvl].uv = ((uu / N - 0.5) * tiles + 0.5, vv / (len(loops) - 1))
me = bpy.data.meshes.new("Bandeau")
bm.to_mesh(me)
bm.free()
bandeau = new_obj("Bandeau", me, bpy.data.collections["Top"], band_mat)
tex.extension = "CLIP"
skin_to_body(bandeau)
sol = bandeau.modifiers.new("Solidify", "SOLIDIFY")
sol.thickness = 0.0012
sol.offset = 1.0

# ---------------------------------------------------------------- long sleeves, pushed up the forearm
for side, sx in (("L", 1), ("R", -1)):
    chain = [bone_pt(side + "_ShldrBend"), bone_pt(side + "_ShldrBend", True),
             bone_pt(side + "_ShldrTwist", True),
             bone_pt(side + "_ForearmBend"), bone_pt(side + "_ForearmBend", True),
             bone_pt(side + "_ForearmTwist", True)]
    stops = [(0, 1, 0.50), (0, 1, 0.80), (1, 2, 0.15), (1, 2, 0.55), (1, 2, 0.95), (3, 4, 0.25), (3, 4, 0.65),
             (4, 5, 0.05), (4, 5, 0.25), (4, 5, 0.36), (4, 5, 0.37), (4, 5, 0.47)]
    rings = []
    for k, (i0, i1, t) in enumerate(stops):
        c = chain[i0].lerp(chain[i1], t)
        ax = (chain[i1] - chain[i0]).normalized()
        ease = 0.003 if k < 2 else 0.0045                 # tucks under the shirt body at the shoulder
        if k >= len(stops) - 2:
            ease = 0.008                                   # last two rings = turned-back cuff
        rings.append(offset_loop(wrap(c, ax, 0.085, n=24), c, ax, ease))
    sleeve = band("Shirt Sleeve " + side, rings, uniform, cotton, 0.0012)
    skin_to_body(sleeve)
    sleeve.modifiers.new("Subdivision", "SUBSURF").levels = 1

# ---------------------------------------------------------------- choker
n1, n2 = bone_pt("neck_01"), bone_pt("neck_01", True)
ax = (n2 - n1).normalized()
c_mid = n1.lerp(n2, 0.75)
rings = []
for k in (-0.009, 0.0, 0.009):
    c = c_mid + ax * k
    rings.append(offset_loop(wrap(c, ax, 0.2), c, ax, 0.0025))
choker = band("Choker", rings, acc, leather, 0.0025)
bone_parent(choker, "neck_01")
# printed design: a white wavy line running round the band (no pendant)
print_mat = make_mat("Rebel Choker Print", (0.85, 0.85, 0.85, 1), rough=0.6)
WN, WAVES = 168, 14
line = offset_loop(wrap(c_mid, ax, 0.2, n=WN), c_mid, ax, 0.0056)
pc = bpy.data.curves.new("Choker Print", "CURVE")
pc.dimensions = "3D"
pc.bevel_depth = 0.0008
pc.bevel_resolution = 1
ps = pc.splines.new("POLY")
ps.points.add(WN - 1)
for i, pnt in enumerate(line):
    tri = abs((i * WAVES / WN) % 1.0 - 0.5) * 4 - 1          # zig-zag between -1 and 1
    ps.points[i].co = (*(pnt + ax * 0.0038 * tri), 1)
ps.use_cyclic_u = True
cprint = bpy.data.objects.new("Choker Print", pc)
acc.objects.link(cprint)
pc.materials.append(print_mat)
bone_parent(cprint, "neck_01")

# ---------------------------------------------------------------- wrist cuff (her left)
a, b = bone_pt("L_ForearmTwist"), bone_pt("L_ForearmTwist", True)
ax = (b - a).normalized()
c_mid = a.lerp(b, 0.74)
rings = []
for k in (-0.024, -0.008, 0.008, 0.024):
    c = c_mid + ax * k
    rings.append(offset_loop(wrap(c, ax, 0.12), c, ax, 0.003))
cuff = band("Wrist Cuff", rings, acc, leather, 0.0035)
bone_parent(cuff, "L_ForearmTwist")
for k in (-0.012, 0.012):   # two stitched seams / straps
    c = c_mid + ax * k
    strap = band("Wrist Cuff Strap", [offset_loop(wrap(c + ax * s, ax, 0.12), c, ax, 0.0068) for s in (-0.0035, 0.0035)],
                 acc, leather, 0.0015)
    bone_parent(strap, "L_ForearmTwist")

# ---------------------------------------------------------------- navel ring
prof = []
z = 1.08
while z < 1.34:
    loc, _ = hit((0, -1, z), (0, 1, 0))
    if loc:
        prof.append((z, loc.y))
    z += 0.002
best = None
for i in range(12, len(prof) - 12):
    around = (prof[i - 12][1] + prof[i + 12][1]) / 2
    depth = prof[i][1] - around
    if best is None or depth > best[0]:
        best = (depth, prof[i][0], prof[i][1], around)
_, nz, ny, skin_y = best
print("navel at z=%.3f depth=%.4f" % (nz, best[0]))
navel = torus("Navel Ring", (0, skin_y - 0.0045, nz - 0.0125), 0.0105, 0.0021, (0, 1, 0), acc, gold)
bone_parent(navel, "abdomenLower")
bead_me = bpy.data.meshes.new("Navel Bead")
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.0042)
bmesh.ops.translate(bm, verts=bm.verts, vec=(0, skin_y - 0.003, nz - 0.0005))
bm.to_mesh(bead_me)
bm.free()
bead = new_obj("Navel Bead", bead_me, acc, gold)
bone_parent(bead, "abdomenLower")

# ---------------------------------------------------------------- earrings
eval_body = body.evaluated_get(deps)
for side, sx in (("L", 1), ("R", -1)):
    ear = bone_pt(side + "_Ear")
    # walk down the ear from outside to find the lobe (lowest point still hit)
    lobe = None
    z = ear.z
    while z > ear.z - 0.05:
        loc, _ = hit((sx * 0.3, ear.y - 0.004, z), (-sx, 0, 0), 0.3)
        if loc and abs(loc.x) > abs(ear.x) - 0.012:
            lobe = loc
        z -= 0.002
    if lobe is None:
        lobe = ear + Vector((0, 0, -0.03))
    hoops = [(0.013, 0.0)] if side == "L" else [(0.013, 0.0), (0.009, 0.012)]
    for i, (r, up) in enumerate(hoops):
        c = lobe + Vector((sx * 0.003, -0.003 * i, up - r + 0.003))
        e = torus("Earring %s %d" % (side, i + 1), c, r, 0.0012, (1, 0.25 * sx, 0), acc, gold)
        bone_parent(e, "head")

# ---------------------------------------------------------------- lip barbell (her right) + tongue barbell
lp = bone_pt("R_LipLower")
top, _ = hit((lp.x - 0.004, -0.5, lp.z + 0.0005), (0, 1, 0))
low, _ = hit((lp.x - 0.004, -0.5, lp.z - 0.0075), (0, 1, 0))
if top and low:
    lipbar = barbell("Lip Barbell", top + Vector((0, -0.0012, 0)), low + Vector((0, -0.0012, 0)),
                     0.0019, 0.0007, acc, gold)
    bone_parent(lipbar, "R_LipLower")

tongue = bpy.data.objects["Tongue"]
tbvh = BVHTree.FromObject(tongue, deps)
tw = [tongue.matrix_world @ Vector(c) for c in tongue.bound_box]
tip_y = min(p.y for p in tw)
t_top, _n, _i, _d = tbvh.ray_cast(Vector((0, tip_y + 0.016, 2.0)), Vector((0, 0, -1)), 1.0)
if t_top:
    stud = barbell("Tongue Barbell", t_top + Vector((0, 0, 0.0012)), t_top + Vector((0, 0, -0.0085)),
                   0.0024, 0.0008, acc, gold)
    tbone = next(b for b in ("Tongue_Front", "Tongue_Master", "C_Jaw") if b in arm.pose.bones)
    bone_parent(stud, tbone)

# ---------------------------------------------------------------- ahoge
hair = bpy.data.objects["Hair.001"]
hbb = [hair.matrix_world @ Vector(c) for c in hair.bound_box]
top = max(p.z for p in hbb)
head_top, _ = hit((0, 0.0, 3.0), (0, 0, -1), 3.0)
root = Vector((0.0, -0.01, max(top - 0.012, head_top.z)))
himg = bpy.data.images["Huna_Tex_Hair_Diffuse.png"]
hp = np.empty(himg.size[0] * himg.size[1] * 4, dtype=np.float32)
himg.pixels.foreach_get(hp)
hp = hp.reshape(-1, 4)[::97]
hp = hp[(hp[:, 3] > 0.5) & (hp[:, 0] > 0.3)]
hcol = np.median(hp[:, :3], axis=0) if len(hp) else np.array((0.8, 0.02, 0.03))
hair_mat = make_mat("Rebel Hair Strand", (float(hcol[0]), float(hcol[1]), float(hcol[2]), 1), rough=0.55)
cu = bpy.data.curves.new("Ahoge", "CURVE")
cu.dimensions = "3D"
cu.bevel_depth = 0.008
cu.bevel_resolution = 3
cu.use_fill_caps = True
sp = cu.splines.new("BEZIER")
pts = [  # (offset from root, radius) - up, hook over to her left, flick back down
    ((0.000, 0.000, 0.000), 1.2),
    ((-0.012, -0.004, 0.060), 1.0),
    ((0.020, -0.008, 0.100), 0.8),
    ((0.062, -0.008, 0.088), 0.55),
    ((0.078, -0.006, 0.050), 0.0),
]
sp.bezier_points.add(len(pts) - 1)
for bp, (off, rad) in zip(sp.bezier_points, pts):
    bp.co = root + Vector(off)
    bp.radius = rad
    bp.handle_left_type = bp.handle_right_type = "AUTO"
ahoge = bpy.data.objects.new("Ahoge", cu)
bpy.data.collections["Mesh"].objects.link(ahoge)
cu.materials.append(hair_mat)
ahoge.scale = (1.0, 0.45, 1.0)       # flatten into a ribbon-like lock
ahoge.location.y = root.y * (1 - 0.45)
bone_parent(ahoge, "head")

# ---------------------------------------------------------------- shirt: sailor top -> open knotted shirt
shirt = bpy.data.objects["Shirt"]
bm = bmesh.new()
bm.from_mesh(shirt.data)
bm.verts.ensure_lookup_table()
seen, islands = set(), []
for v in bm.verts:
    if v.index in seen:
        continue
    stack, comp = [v], []
    seen.add(v.index)
    while stack:
        x = stack.pop()
        comp.append(x)
        for e in x.link_edges:
            o = e.other_vert(x)
            if o.index not in seen:
                seen.add(o.index)
                stack.append(o)
    islands.append(comp)
islands.sort(key=len, reverse=True)
scarf = min(islands, key=lambda isl: sum(v.co.y for v in isl) / len(isl))   # the red neckerchief hangs in front
bmesh.ops.delete(bm, geom=list(scarf), context="VERTS")
# below the bust the old top sits inside the torso, so the shirt is cropped there
KNOT_W = 1.385                            # knot height in world space
SC = shirt.scale.z                        # the uniform objects carry an object scale
KNOT_Z, TOP_Z, HEM_Z = KNOT_W / SC, (KNOT_W + 0.225) / SC, (KNOT_W - 0.04) / SC
front_y = min(v.co.y for v in bm.verts if abs(v.co.x) < 0.03 and KNOT_Z - 0.02 < v.co.z < KNOT_Z + 0.02)


def is_front(f):
    return f.calc_center_median().y < -0.02


def bisect(co, no, pred):
    faces = [f for f in bm.faces if pred(f)]
    geom = set(faces)
    for f in faces:
        geom.update(f.edges)
        geom.update(f.verts)
    bmesh.ops.bisect_plane(bm, geom=list(geom), plane_co=co, plane_no=no, dist=1e-5)


# planes are (point, outward normal); a face is removed when it lies on the inner side
planes = []
for sx in (1, -1):
    # open front: a V from the knot up to the collar
    planes.append(("v", sx, Vector((sx * 0.012, 0, KNOT_Z)), Vector((sx * 0.15, 0, -0.085)).normalized()))
    # hem: rises from the hips to the knot
    planes.append(("hem", sx, Vector((sx * 0.02, 0, KNOT_Z)), Vector((sx * (KNOT_Z - HEM_Z), 0, 0.14)).normalized()))
for kind, sx, co, no in planes:
    bisect(co, no, lambda f, sx=sx: is_front(f) and f.calc_center_median().x * sx > -0.005)
bisect(Vector((0, 0, HEM_Z)), Vector((0, 0, 1)), lambda f: not is_front(f))
# drop the puffy short sleeves at the shoulder; the long sleeves take over from there
def near_arm(c, cut):
    """True for points beyond the cut plane that belong to the sleeve, not the side of the torso."""
    rel = c - cut[0]
    along = rel.dot(cut[1])
    return along > -0.02 and (rel - cut[1] * along).length < 0.085


arm_cuts = []
for side, sx in (("L", 1), ("R", -1)):
    a0, a1 = bone_pt(side + "_ShldrBend") / SC, bone_pt(side + "_ShldrBend", True) / SC
    cut = (a0.lerp(a1, 0.72), (a1 - a0).normalized())
    arm_cuts.append((sx, cut))
    bisect(cut[0], cut[1], lambda f, sx=sx, cut=cut: f.calc_center_median().x * sx > 0.10
           and near_arm(f.calc_center_median(), cut))
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)

kill = []
for f in bm.faces:
    c = f.calc_center_median()
    sx = 1 if c.x >= 0 else -1
    v_co, v_no = next((co, no) for k, s, co, no in planes if k == "v" and s == sx)
    h_co, h_no = next((co, no) for k, s, co, no in planes if k == "hem" and s == sx)
    a_co, a_no = next(cut for s, cut in arm_cuts if s == sx)
    if abs(c.x) > 0.10 and (c - a_co).dot(a_no) > 0 and near_arm(c, (a_co, a_no)):
        kill.append(f)
        continue
    if abs(c.x) > 0.21:
        continue
    if is_front(f):
        if (c - v_co).dot(v_no) < 0 and c.z > KNOT_Z - 0.03:
            kill.append(f)
        elif (c - h_co).dot(h_no) < 0:
            kill.append(f)
    elif c.z < HEM_Z:
        kill.append(f)
bmesh.ops.delete(bm, geom=kill, context="FACES")
bm.normal_update()
for f in bm.faces:
    f.material_index = 0
    f.smooth = True
bm.to_mesh(shirt.data)
bm.free()
shirt.data.materials.clear()
shirt.data.materials.append(cotton)
for m in shirt.modifiers:
    if m.type == "MASK":
        m.show_render = m.show_viewport = False
wrapm = shirt.modifiers.new("Rebel Keep Outside Body", "SHRINKWRAP")   # the old top sat inside the torso
wrapm.target = body
wrapm.wrap_method = "NEAREST_SURFACEPOINT"
wrapm.wrap_mode = "OUTSIDE"
wrapm.offset = 0.0065
sol = shirt.modifiers.new("Rebel Thickness", "SOLIDIFY")
sol.thickness = 0.0012
sol.offset = 1.0

# knot + two tails, riding the lower chest bone
bm = bmesh.new()
skin, _ = hit((0, -1, KNOT_W - 0.012), (0, 1, 0))
ky = skin.y - 0.011
kz = KNOT_W - 0.012
bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.5,
                          matrix=Matrix.Translation((0, ky, kz)) @ Matrix.Diagonal((0.034, 0.020, 0.026, 1)))
for sx in (1, -1):
    tail = bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=0.005, radius2=0.024, depth=0.085)
    mat_t = (Matrix.Translation((sx * 0.026, ky + 0.003, kz - 0.044))
             @ Matrix.Rotation(sx * math.radians(-26), 4, "Y")
             @ Matrix.Diagonal((1.0, 0.12, 1.0, 1))
             @ Matrix.Rotation(math.pi, 4, "X")
             @ Matrix.Rotation(math.radians(45), 4, "Z"))
    bmesh.ops.transform(bm, matrix=mat_t, verts=tail["verts"])
me = bpy.data.meshes.new("Shirt Knot")
bm.to_mesh(me)
bm.free()
knot = new_obj("Shirt Knot", me, uniform, cotton)
knot.modifiers.new("Subdivision", "SUBSURF").levels = 1
bone_parent(knot, "chestLower")

# ---------------------------------------------------------------- skirt: navy pleats, white belt, heart buckle
def striped(name, lo, hi):
    """Navy cloth with a white stripe between two heights (0..1 of the rest-pose bounding box)."""
    m = make_mat(name, NAVY, rough=0.75)
    nt = m.node_tree
    co = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    above = nt.nodes.new("ShaderNodeMath")
    above.operation = "GREATER_THAN"
    above.inputs[1].default_value = lo
    below = nt.nodes.new("ShaderNodeMath")
    below.operation = "LESS_THAN"
    below.inputs[1].default_value = hi
    both = nt.nodes.new("ShaderNodeMath")
    both.operation = "MULTIPLY"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = NAVY
    mix.inputs[7].default_value = WHITE
    nt.links.new(co.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], above.inputs[0])
    nt.links.new(sep.outputs["Z"], below.inputs[0])
    nt.links.new(above.outputs[0], both.inputs[0])
    nt.links.new(below.outputs[0], both.inputs[1])
    nt.links.new(both.outputs[0], mix.inputs[0])
    nt.links.new(mix.outputs[2], nt.nodes["Principled BSDF"].inputs["Base Color"])
    return m


skirt = bpy.data.objects["Skirt"]
bm = bmesh.new()
bm.from_mesh(skirt.data)
bm.verts.ensure_lookup_table()
seen, islands = set(), []
for v in bm.verts:
    if v.index in seen:
        continue
    stack, comp = [v], []
    seen.add(v.index)
    while stack:
        x = stack.pop()
        comp.append(x)
        for e in x.link_edges:
            o = e.other_vert(x)
            if o.index not in seen:
                seen.add(o.index)
                stack.append(o)
    islands.append(comp)
islands.sort(key=len, reverse=True)
pleats, belt, buckle = islands[0], islands[1], islands[2]
for v in belt:
    for f in v.link_faces:
        f.material_index = 1
bz = (sum(v.co.z for v in buckle) / len(buckle) - SKIRT_DROP) * skirt.scale.z
by = min(v.co.y for v in buckle) * skirt.scale.y
bmesh.ops.delete(bm, geom=list(buckle), context="VERTS")
# micro length, flared hem and deep box pleats
p_top = max(v.co.z for v in pleats)
p_low = min(v.co.z for v in pleats)
cy = sum(v.co.y for v in pleats) / len(pleats)
for v in pleats:
    h = (p_top - v.co.z) / (p_top - p_low)             # 0 at the waist, 1 at the hem
    v.co.z = p_top - (p_top - v.co.z) * SKIRT_LENGTH
    ang = math.atan2(v.co.x, -(v.co.y - cy))
    wave = math.sin(ang * PLEATS)
    wave = math.copysign(abs(wave) ** 0.45, wave)      # squared-off folds rather than ripples
    grow = 1 + h * (0.16 + 0.085 * wave)
    v.co.x *= grow
    v.co.y = cy + (v.co.y - cy) * grow
for v in bm.verts:
    v.co.z -= SKIRT_DROP
    k = max(0.0, min(1.0, (v.co.z - 0.93) / 0.12))   # ease the waistband open so it clears the hips
    v.co.x *= 1 + 0.045 * k
    v.co.y = (v.co.y - 0.01) * (1 + 0.06 * k) + 0.01
bm.to_mesh(skirt.data)
bm.free()
white_belt = make_mat("Rebel White Belt", WHITE, rough=0.45)
skirt.data.materials[0] = striped("Rebel Navy Skirt", 0.09, 0.16)
for i in range(1, len(skirt.data.materials)):
    skirt.data.materials[i] = white_belt

hc = bpy.data.curves.new("Heart Buckle", "CURVE")
hc.dimensions = "3D"
hc.bevel_depth = 0.0042
hc.bevel_resolution = 3
hs = hc.splines.new("POLY")
HN = 48
hs.points.add(HN - 1)
for i in range(HN):
    t = 2 * math.pi * i / HN
    hx = 16 * math.sin(t) ** 3
    hz = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
    hs.points[i].co = (hx * 0.0021, by * (1 + 0.06) - 0.008, bz + 0.004 + hz * 0.0021, 1)
hs.use_cyclic_u = True
heart = bpy.data.objects.new("Heart Buckle", hc)
uniform.objects.link(heart)
hc.materials.append(gold)
bone_parent(heart, "pelvis")

# ---------------------------------------------------------------- thong + high-rise white hip straps
strap_mat = make_mat("Rebel White Strap", WHITE, rough=0.6)
for name in ("Thong_01",):
    th = bpy.data.objects[name]
    for i in range(len(th.data.materials)):
        th.data.materials[i] = strap_mat
    # only the part below the belt line is wanted; the tall straps are built separately
    vg = th.vertex_groups.new(name="Rebel Under Belt")
    vg.add([v.index for v in th.data.vertices if (th.matrix_world @ v.co).z < 1.15], 1.0, "REPLACE")
    mask = th.modifiers.new("Rebel Under Belt", "MASK")
    mask.vertex_group = vg.name
SN = 96
Z_FRONT, Z_SIDE, Z_BACK = 1.085, 1.285, 1.15
strap_loops = [[], []]
for i in range(SN):
    a = 2 * math.pi * i / SN                          # 0 = straight ahead
    d = Vector((math.sin(a), -math.cos(a), 0))
    low = Z_FRONT if math.cos(a) > 0 else Z_BACK
    z = low + (Z_SIDE - low) * abs(math.sin(a)) ** 0.8
    for k, dz in enumerate((-0.0055, 0.0055)):
        loc, _ = hit(Vector((0, 0.0, z + dz)), d, 0.6)
        strap_loops[k].append(loc + d * 0.0025)
straps = band("Thong Straps", strap_loops, bpy.data.collections["Bottom"], strap_mat, 0.0015)
skin_to_body(straps)

# ---------------------------------------------------------------- thigh-highs: navy with a white band
socks = bpy.data.objects["Socks"]
sock_mat = striped("Rebel Navy Thigh-highs", 0.875, 0.925)
for i in range(len(socks.data.materials)):
    socks.data.materials[i] = sock_mat

# ---------------------------------------------------------------- done
bpy.context.view_layer.update()
if OUT:
    bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
    print("saved", OUT)
