"""Render quick EEVEE previews of the restyled character.

    blender -b restyled.blend -P preview.py -- out_prefix [shot ...]
"""
import math
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
prefix, wanted = args[0], args[1:]
sc = bpy.context.scene
if hasattr(sc.render.image_settings, "media_type"):
    sc.render.image_settings.media_type = "IMAGE"
sc.render.image_settings.file_format = "PNG"
sc.render.resolution_percentage = 100
try:
    sc.eevee.taa_render_samples = 16
except AttributeError:
    pass

SHOTS = {  # name: (look-at point, distance, resolution, orbit angle in degrees)
    "full": ((0, 0, 0.97), 5.2, (600, 860), 0),
    "bust": ((0, 0, 1.50), 2.1, (760, 760), 0),
    "face": ((0, 0, 1.80), 0.80, (760, 760), 0),
    "side": ((0, 0, 1.50), 2.1, (760, 760), 55),
    "cuff": ((0.45, 0, 1.26), 0.9, (600, 600), 0),
    "waist": ((0, 0, 1.22), 0.9, (600, 600), 0),
}
for name in wanted or SHOTS:
    target, dist, res, deg = SHOTS[name]
    ang = math.radians(deg)
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = 85
    cam = bpy.data.objects.new(name, cam_data)
    sc.collection.objects.link(cam)
    cam.location = Vector(target) + Vector((math.sin(ang) * dist, -math.cos(ang) * dist, 0))
    cam.rotation_euler = (math.pi / 2, 0, ang)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.filepath = prefix + name + ".png"
    bpy.ops.render.render(write_still=True)
