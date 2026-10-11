"""Shared camera + light rig + math. Runs inside Blender (bpy). One rig for every piece."""
import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ELEV = {"dimetric_2_1": 30.0, "isometric": 35.264}  # camera elevation above horizon, deg
SQ2 = math.sqrt(2)


def elev_rad(mode):
    return math.radians(ELEV[mode])


def default_ppu(tile_w):
    """Screen px per world unit along the diamond diagonal axis (tile 1x1 unit -> tile_w px)."""
    return tile_w / SQ2


def expected_diamond(tile_w, mode):
    return tile_w, round(tile_w * math.sin(elev_rad(mode)))


def z_units(px, cfg):
    """Vertical screen px -> world Z units."""
    return px / (cfg["ppu"] * math.cos(elev_rad(cfg["camera_mode"])))


def point_px(cam, cfg, p):
    """Canvas pixel of a world point."""
    W, H = cfg["canvas"]
    q = world_to_camera_view(bpy.context.scene, cam, Vector(p))
    return q.x * W, (1 - q.y) * H


def canvas_for(cfg, fx, fy, height_units):
    """Canvas big enough for a fx x fy footprint plus an object `height_units` tall, with the footprint's bottom
    vertex 16 px above the bottom edge. Returns the cfg fields to merge: canvas, origin_y."""
    e = elev_rad(cfg["camera_mode"])
    span = (fx + fy) / 2
    tw = cfg["tile_w"]
    th_px = cfg["tile_h"] * (fx + fy) / 2                         # nominal footprint diamond height in px
    hpx = height_units * cfg["ppu"] * math.cos(e)
    W = int(max(tw * 3, tw * span + 2 * tw)) // 2 * 2
    H = int(max(tw * 4, hpx + th_px + tw)) // 2 * 2
    bottom_off = cfg["tile_h"] * (fx + fy) / 4                      # origin -> bottom vertex, px (nominal)
    return {"canvas": [W, H], "origin_y": H - 16 - bottom_off}


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def _look(obj, direction):
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup(cfg):
    """cfg keys: tile_w, camera_mode, canvas=[W,H], ppu, origin_y (px of world origin)."""
    sc = bpy.context.scene
    W, H = cfg["canvas"]
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    sc.eevee.taa_render_samples = 64

    cam_d = bpy.data.cameras.new("IsoCam")
    cam_d.type = "ORTHO"
    cam_d.sensor_fit = "AUTO"
    cam_d.ortho_scale = max(W, H) / cfg["ppu"]
    cam_d.clip_start, cam_d.clip_end = 0.1, 200
    cam_d.shift_y = (cfg["origin_y"] - H / 2) / max(W, H)
    cam = bpy.data.objects.new("IsoCam", cam_d)
    sc.collection.objects.link(cam)
    cam.rotation_euler = (math.radians(90 - ELEV[cfg["camera_mode"]]), 0, math.radians(45))
    view = cam.rotation_euler.to_matrix() @ Vector((0, 0, -1))
    cam.location = -view * 60
    sc.camera = cam

    # World: dim cool ambient (acts as cheap soft fill / occlusion base)
    w = bpy.data.worlds.new("IsoWorld")
    sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.36, 0.37, 0.40, 1)
    bg.inputs["Strength"].default_value = 0.65

    # Camera sees +x and -y faces. Key from screen top-left = from -y (and a touch -x), high.
    _sun("Key", Vector((-0.35, -1.0, 1.15)), (1.0, 0.88, 0.70), 2.8, 6)
    _sun("Fill", Vector((1.0, 0.25, 0.55)), (0.72, 0.78, 0.90), 1.2, 25)
    _sun("Rim", Vector((0.3, 1.0, 0.7)), (0.8, 0.85, 1.0), 0.5, 10)
    return sc, cam


def _sun(name, to_light, color, energy, angle_deg):
    d = bpy.data.lights.new(name, "SUN")
    d.color, d.energy, d.angle = color, energy, math.radians(angle_deg)
    o = bpy.data.objects.new(name, d)
    bpy.context.scene.collection.objects.link(o)
    _look(o, -to_light.normalized())
    o.location = to_light.normalized() * 40


def origin_px(cam, cfg):
    W, H = cfg["canvas"]
    p = world_to_camera_view(bpy.context.scene, cam, Vector((0, 0, 0)))
    return p.x * W, (1 - p.y) * H


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
