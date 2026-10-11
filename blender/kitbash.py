"""Procedural kitbash pieces. Footprint = 1x1 unit tile centred on origin; origin = base-centre.
Visible faces from the camera: +x and -y. Back edges: NW (x=-0.5) and NE (y=+0.5)."""
import math
import random

import bmesh
import bpy
from mathutils import Vector, noise

import scene_rig as rig

T = 0.12  # wall thickness (world units)
TEX_GAIN = {"asphalt": 0.42, "concrete": 0.9, "brick": 1.0, "rust": 1.0, "wood": 1.0}  # AI textures come out bright


# ---------------------------------------------------------------- materials
def _n(nt, kind, **kw):
    n = nt.nodes.new(kind)
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def _ramp(nt, stops):
    r = nt.nodes.new("ShaderNodeValToRGB")
    el = r.color_ramp.elements
    while len(el) < len(stops):
        el.new(0.5)
    for e, (pos, col) in zip(el, stops):
        e.position, e.color = pos, col
    return r


def make_material(kind, seed=0, tex=None, base=None):
    """kind: concrete|asphalt|brick|rust|wood. tex = path to a tileable image (overrides colour)."""
    m = bpy.data.materials.new(f"{kind}_{seed}")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = _n(nt, "ShaderNodeOutputMaterial")
    bsdf = _n(nt, "ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    tc = _n(nt, "ShaderNodeTexCoord")
    mp = _n(nt, "ShaderNodeMapping")
    mp.inputs["Location"].default_value = (seed * 1.37, seed * 0.91, seed * 0.53)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])

    def noise_tex(scale, detail=8, rough=0.55):
        t = _n(nt, "ShaderNodeTexNoise")
        t.inputs["Scale"].default_value, t.inputs["Detail"].default_value = scale, detail
        t.inputs["Roughness"].default_value = rough
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        return t.outputs["Fac"]

    PAL = {
        "concrete": ([(0.0, (0.12, 0.115, 0.11, 1)), (0.5, (0.30, 0.29, 0.275, 1)), (1.0, (0.52, 0.50, 0.46, 1))], 0.92),
        "asphalt": ([(0.0, (0.035, 0.035, 0.04, 1)), (0.6, (0.085, 0.085, 0.09, 1)), (1.0, (0.15, 0.145, 0.14, 1))], 0.95),
        "brick": ([(0.0, (0.18, 0.07, 0.05, 1)), (1.0, (0.42, 0.22, 0.16, 1))], 0.9),
        "rust": ([(0.0, (0.12, 0.05, 0.03, 1)), (0.6, (0.38, 0.17, 0.07, 1)), (1.0, (0.5, 0.28, 0.12, 1))], 0.8),
        "wood": ([(0.0, (0.10, 0.07, 0.045, 1)), (1.0, (0.34, 0.24, 0.15, 1))], 0.85),
    }
    stops, rough = PAL[kind]
    if base:  # painted surface: dark/base/light variants of one colour
        r, g, b = base
        stops = [(0.0, (r * .45, g * .45, b * .45, 1)), (0.6, (r, g, b, 1)), (1.0, (min(r * 1.3, 1), min(g * 1.3, 1), min(b * 1.3, 1), 1))]
        rough = 0.75
    if tex:
        it = _n(nt, "ShaderNodeTexImage", image=bpy.data.images.load(tex), projection="BOX")
        it.projection_blend = 0.25
        nt.links.new(mp.outputs["Vector"], it.inputs["Vector"])
        gain = _n(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        gain.inputs[0].default_value = 1.0
        g = TEX_GAIN.get(kind, 1.0)
        gain.inputs["B"].default_value = (g, g, g, 1)
        nt.links.new(it.outputs["Color"], gain.inputs["A"])
        col = gain.outputs["Result"]
    else:
        grain = noise_tex(9 if kind != "asphalt" else 60, 10)
        col = _ramp(nt, stops)
        nt.links.new(grain, col.inputs["Fac"])
        col = col.outputs["Color"]
    # grime: low-frequency darkening
    grime = noise_tex(1.6, 6)
    gr = _ramp(nt, [(0.35, (1, 1, 1, 1)), (0.8, (0.45, 0.4, 0.36, 1))])
    nt.links.new(grime, gr.inputs["Fac"])
    mix = _n(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    mix.inputs[0].default_value = 1.0
    nt.links.new(col, mix.inputs["A"])
    nt.links.new(gr.outputs["Color"], mix.inputs["B"])
    base = mix.outputs["Result"]
    height = noise_tex(14, 8)

    if kind == "asphalt":  # cracks = thin band near Voronoi cell edges
        v = _n(nt, "ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE")
        v.inputs["Scale"].default_value = 2.2
        nt.links.new(mp.outputs["Vector"], v.inputs["Vector"])
        crack = _ramp(nt, [(0.0, (0, 0, 0, 1)), (0.035, (1, 1, 1, 1))])  # 0 on crack, 1 away
        nt.links.new(v.outputs["Distance"], crack.inputs["Fac"])
        dark = _n(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        dark.inputs[0].default_value = 1.0
        nt.links.new(base, dark.inputs["A"])
        nt.links.new(crack.outputs["Color"], dark.inputs["B"])
        base = dark.outputs["Result"]
        hm = _n(nt, "ShaderNodeMath", operation="MULTIPLY")
        nt.links.new(height, hm.inputs[0])
        nt.links.new(crack.outputs["Color"], hm.inputs[1])  # color->float uses luminance
        height = hm.outputs["Value"]

    bump = _n(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(height, bump.inputs["Height"])
    nt.links.new(base, bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = rough
    return m


# ---------------------------------------------------------------- geometry
def _finish(obj, mat, bevel=0.012):
    obj.data.materials.append(mat)
    if bevel:
        md = obj.modifiers.new("bevel", "BEVEL")
        md.width, md.segments, md.limit_method = bevel, 2, "ANGLE"
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=md.name)
    for p in obj.data.polygons:
        p.use_smooth = False
    return obj


def box(name, x0, y0, x1, y1, z0, z1, mat, seed=0, rough=0.0, crumble=0.0, cuts=0, bevel=0.012):
    """Axis-aligned box. rough = random vertex jitter; crumble = top-edge erosion (dilapidated)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector(((x0 + x1) / 2 + v.co.x * (x1 - x0), (y0 + y1) / 2 + v.co.y * (y1 - y0),
                       (z0 + z1) / 2 + v.co.z * (z1 - z0)))
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    rnd = random.Random(seed)
    off = Vector((rnd.random() * 50, rnd.random() * 50, rnd.random() * 50))
    for v in bm.verts:
        p = v.co.copy()
        if rough:
            d = Vector((noise.noise(p * 7 + off), noise.noise(p * 7 + off + Vector((9, 0, 0))),
                        noise.noise(p * 7 + off + Vector((0, 9, 0))))) * rough
            if v.co.z > z0 + 1e-4:
                v.co += d
            else:
                v.co.x += d.x
                v.co.y += d.y
        if crumble and v.co.z > z1 - 1e-4 - crumble * 0.25:
            h = (noise.noise(Vector((p.x * 4, p.y * 4, 0)) + off) + 1) / 2
            v.co.z -= max(0.0, h - 0.35) * crumble * 1.4 * (z1 - z0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return _finish(obj, mat, bevel)


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.active_object
    o.name = name
    return o


def floor_tile(cfg, variant="plain", mat="asphalt", tex=None, seed=0, footprint=(1, 1)):
    """Flat slab exactly covering the footprint diamond (default 1x1 tile)."""
    X, Y = footprint[0] / 2, footprint[1] / 2
    m = make_material(mat, seed, tex)
    me = bpy.data.meshes.new("floor")
    me.from_pydata([(-X, -Y, 0), (X, -Y, 0), (X, Y, 0), (-X, Y, 0)], [], [(0, 1, 2, 3)])
    o = bpy.data.objects.new("floor", me)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(m)
    if variant == "cracked":  # same shader, denser cracks via different seed offset
        m.node_tree.nodes["Mapping"].inputs["Scale"].default_value = (1.4, 1.4, 1.4)
    return o


def _segs(kind, X, Y):
    """Wall rectangles (x0,y0,x1,y1) for a footprint of 2X by 2Y tiles; NW wall at x=-X, NE wall at y=+Y."""
    nw, ne = (-X, -Y, -X + T, Y), (-X, Y - T, X, Y)
    return {"nw": [nw], "ne": [ne], "corner": [nw, (-X + T, Y - T, X, Y)],
            "end_nw": [(-X, -Y, -X + T, Y - .28 * 2 * Y)], "end_ne": [(-X + .28 * 2 * X, Y - T, X, Y)],
            "t_nw": [nw, (-X + T, -T / 2, X, T / 2)], "t_ne": [ne, (-T / 2, -Y, T / 2, Y - T)]}[kind]


def _posts(kind, X, Y):
    if kind == "end_nw":
        y = Y - .28 * 2 * Y
        return [(-X, y - .04, -X + .2, y + .16)]
    if kind == "end_ne":
        x = -X + .28 * 2 * X
        return [(x - .16, Y - .2, x + .04, Y)]
    return []


WALL_KINDS = ["nw", "ne", "corner", "end_nw", "end_ne", "t_nw", "t_ne"]


def wall(cfg, kind="nw", mat="concrete", tex=None, seed=0, height_px=None, dilapidated=True, footprint=(1, 1)):
    h = rig.z_units(height_px or cfg["wall_height_px"], cfg)
    X, Y = footprint[0] / 2, footprint[1] / 2
    m = make_material(mat, seed, tex)
    parts = []
    for i, (x0, y0, x1, y1) in enumerate(_segs(kind, X, Y)):
        n = max(1, round(max(x1 - x0, y1 - y0)))                     # more subdivisions on longer walls
        parts.append(box(f"w{i}", x0, y0, x1, y1, 0, h, m, seed + i, rough=0.012 if dilapidated else 0,
                         crumble=0.35 if dilapidated else 0, cuts=14 * n if dilapidated else 0))
    for i, (x0, y0, x1, y1) in enumerate(_posts(kind, X, Y)):
        parts.append(box(f"p{i}", x0, y0, x1, y1, 0, h * 1.06, m, seed + 9 + i, rough=0.01, crumble=0.2, cuts=10))
    return join(parts, f"wall_{kind}") if len(parts) > 1 else parts[0]


# ------------------------------------------------------- openings, fences, stairs, roofs
def _along(side, a0, a1, X=.5, Y=.5):
    """Rect of a wall slab spanning a0..a1 along the wall (coordinate centred on the wall); nw runs along y, ne along x."""
    return (-X, a0, -X + T, a1) if side == "nw" else (a0, Y - T, a1, Y)


def slab(name, side, a0, a1, z0, z1, mat, X=.5, Y=.5, **kw):
    x0, y0, x1, y1 = _along(side, a0, a1, X, Y)
    return box(name, x0, y0, x1, y1, z0, z1, mat, **kw)


def _glass(name="glass"):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.05, 0.08, 0.1, 1)
    b.inputs["Roughness"].default_value = 0.15
    return m


def opening(cfg, kind="door", side="nw", variant="open", mat="concrete", tex=None, seed=0, height_px=None,
            footprint=(1, 1), count=1):
    """Wall slab with `count` door/window holes built from jambs + lintel (+ sill). variant: open|closed."""
    H = rig.z_units(height_px or cfg["wall_height_px"], cfg)
    X, Y = footprint[0] / 2, footprint[1] / 2
    L = 2 * Y if side == "nw" else 2 * X
    m, wood = make_material(mat, seed, tex), make_material("wood", seed + 3)
    ow = 0.42 if kind == "door" else 0.36
    z0, z1 = (0.0, H * 0.72) if kind == "door" else (H * 0.34, H * 0.70)
    centres = [-L / 2 + L * (i + .5) / count for i in range(count)]
    edges = [-L / 2] + [e for c in centres for e in (c - ow / 2, c + ow / 2)] + [L / 2]
    parts, i = [], 0
    for a0, a1 in zip(edges[::2], edges[1::2]):                      # full-height wall between openings
        parts.append(slab(f"s{i}", side, a0, a1, 0, H, m, X, Y, seed=seed + i, rough=0.01, crumble=0.3, cuts=12 * max(1, round(a1 - a0))))
        i += 1
    fr = 0.03
    for c in centres:
        parts.append(slab(f"head{i}", side, c - ow / 2, c + ow / 2, z1, H, m, X, Y, seed=seed + i, rough=0.01, crumble=0.3, cuts=8))
        i += 1
        if z0 > 0:
            parts.append(slab(f"sill{i}", side, c - ow / 2, c + ow / 2, 0, z0, m, X, Y, seed=seed + i, rough=0.01, cuts=8))
            i += 1
        if kind == "door" and variant == "closed":
            parts.append(slab(f"leaf{i}", side, c - ow / 2 + fr, c + ow / 2 - fr, z0, z1 - fr, wood, X, Y, seed=seed, bevel=0))
        elif kind == "door":  # leaf swung open toward the visible side, hinged at the lower jamb
            a = c - ow / 2 + fr
            if side == "nw":
                parts.append(box(f"leaf{i}", -X + T, a, -X + T + ow - 2 * fr, a + .035, z0, z1 - fr, wood, seed, bevel=0))
            else:
                parts.append(box(f"leaf{i}", a, Y - T - (ow - 2 * fr), a + .035, Y - T, z0, z1 - fr, wood, seed, bevel=0))
        elif kind == "window":
            g = _glass()
            if variant == "closed":
                parts.append(slab(f"pane{i}", side, c - ow / 2, c + ow / 2, z0, z1, g, X, Y, seed=seed, bevel=0))
                for a0, a1, lo, hi in [(c - fr / 2, c + fr / 2, z0, z1), (c - ow / 2, c + ow / 2, (z0 + z1) / 2 - fr / 2, (z0 + z1) / 2 + fr / 2)]:
                    parts.append(slab(f"bar{i}", side, a0, a1, lo, hi, wood, X, Y, seed=seed, bevel=0))
        i += 1
    return join(parts, f"{kind}_{side}_{variant}")


def fence(cfg, side="nw", mat="wood", tex=None, seed=0, height_px=None, footprint=(1, 1)):
    H = rig.z_units(height_px or cfg["wall_height_px"] * 0.55, cfg)
    X, Y = footprint[0] / 2, footprint[1] / 2
    L = 2 * Y if side == "nw" else 2 * X
    m = make_material(mat, seed, tex)
    n = max(4, round(4 * L))
    parts = [slab(f"post{i}", side, -L / 2 + .05 + i * (L - .1) / (n - 1) - .025, -L / 2 + .05 + i * (L - .1) / (n - 1) + .025, 0, H, m, X, Y,
                  seed=seed + i, rough=0.006, bevel=0.004) for i in range(n)]
    for j, (lo, hi) in enumerate(((H * .35, H * .45), (H * .72, H * .82))):
        parts.append(slab(f"rail{j}", side, -L / 2 + .02, L / 2 - .02, lo, hi, m, X, Y, seed=seed + 9 + j, rough=0.006, bevel=0.004))
    return join(parts, f"fence_{side}")


def stairs(cfg, mat="concrete", tex=None, seed=0, height_px=None, steps=None, footprint=(1, 1)):
    """Steps descend along +x toward the camera; width = footprint y."""
    H = rig.z_units(height_px or cfg["wall_height_px"] * 0.6, cfg)
    X, Y = footprint[0] / 2, footprint[1] / 2
    steps = steps or 6 * footprint[0]
    m = make_material(mat, seed, tex)
    parts = [box(f"st{i}", -X + i * 2 * X / steps, -Y, -X + (i + 1) * 2 * X / steps, Y, 0, H * (steps - i) / steps, m, seed + i,
                 rough=0.008, cuts=4) for i in range(steps)]
    return join(parts, "stairs")


def roof(cfg, mat="rust", tex=None, seed=0, height_px=None, pitch=0.35, footprint=(1, 1)):
    """Pitched roof slab over the footprint (ridge along x) resting at height_px."""
    z = rig.z_units(height_px or cfg["wall_height_px"], cfg)
    X, Y = footprint[0] / 2 + .05, footprint[1] / 2 + .05
    m = make_material(mat, seed, tex)
    verts = [(-X, -Y, z), (X, -Y, z), (X, 0, z + pitch * footprint[1]), (-X, 0, z + pitch * footprint[1]), (-X, Y, z), (X, Y, z)]
    me = bpy.data.meshes.new("roof")
    me.from_pydata(verts, [], [(0, 1, 2, 3), (3, 2, 5, 4)])
    o = bpy.data.objects.new("roof", me)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(m)
    sol = o.modifiers.new("solid", "SOLIDIFY")
    sol.thickness = 0.04
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.modifier_apply(modifier=sol.name)
    return o


def crate(cfg, mat="wood", tex=None, seed=0, size=0.5):
    m = make_material(mat, seed, tex)
    h = size
    body = box("body", -size / 2, -size / 2, size / 2, size / 2, 0, h, m, seed, rough=0.006, cuts=3)
    straps = [box(f"band{i}", -size / 2 - .01, -size / 2 - .01 + i * (size * .75), size / 2 + .01, -size / 2 + .06 + i * (size * .75), 0, h + .01,
                  make_material("rust", seed + 1), seed + i, bevel=0) for i in range(2)]
    return join([body] + straps, "crate")


def barricade(cfg, mat="wood", tex=None, seed=0):
    m = make_material(mat, seed, tex)
    rnd = random.Random(seed)
    planks = []
    for i in range(5):
        z = 0.06 + i * 0.1
        o = box(f"pl{i}", -.4, -.05, .4, .05, z, z + .08, m, seed + i, rough=0.01, cuts=6)
        o.rotation_euler.z = math.radians(rnd.uniform(-8, 8))
        o.location.x += rnd.uniform(-.04, .04)
        planks.append(o)
    for j, x in enumerate((-.3, .3)):
        planks.append(box(f"leg{j}", x - .04, -.08, x + .04, .08, 0, .6, m, seed + 20 + j, rough=0.006))
    bpy.ops.object.select_all(action="DESELECT")
    for o in planks:
        o.select_set(True)
    bpy.context.view_layer.objects.active = planks[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return join(planks, "barricade")


def tower(cfg, mat="concrete", tex=None, seed=0, height_px=None):
    H = rig.z_units(height_px or cfg["wall_height_px"] * 2.4, cfg)
    m, wood = make_material(mat, seed, tex), make_material("wood", seed + 2)
    parts = [box("shaft", -.22, -.22, .22, .22, 0, H, m, seed, rough=0.008, crumble=0.12, cuts=14),
             box("deck", -.4, -.4, .4, .4, H, H + .05, wood, seed + 1, bevel=0.006)]
    for i, (x0, y0, x1, y1) in enumerate([(-.4, -.4, .4, -.36), (.36, -.4, .4, .4), (-.4, .36, .4, .4), (-.4, -.4, -.36, .4)]):
        parts.append(box(f"rail{i}", x0, y0, x1, y1, H + .05, H + .22, wood, seed + 3 + i, bevel=0.004))
    return join(parts, "tower")


def build(cfg, kind, **kw):
    fp = kw.pop("footprint", None)
    if fp is not None and not (isinstance(fp, (list, tuple)) and len(fp) == 2 and all(isinstance(v, int) and 1 <= v <= 12 for v in fp)):
        raise ValueError("footprint must be [fx, fy], whole tiles 1..12")
    if fp and kind.startswith("prop_"):
        raise ValueError("props size themselves (their footprint is automatic); footprint applies to floor, wall_*, door, window, fence, stairs, roof")
    if fp and kind in ("crate", "barricade", "tower"):
        raise ValueError(f"'{kind}' is a single-tile object; footprint is not supported")
    if fp:
        kw["footprint"] = tuple(fp)
    if kind == "floor":
        return floor_tile(cfg, **kw)
    if kind.startswith("wall_"):
        return wall(cfg, kind[5:], **kw)
    if kind in ("door", "window"):
        return opening(cfg, kind, **kw)
    simple = {"fence": fence, "stairs": stairs, "roof": roof, "crate": crate, "barricade": barricade, "tower": tower}
    if kind in simple:
        return simple[kind](cfg, **kw)
    import props3d
    if kind.startswith("prop_") and kind[5:] in props3d.PROPS:  # metre-sized 3D props, scaled to tile units for sprites
        o = props3d.PROPS[kind[5:]](cfg, **kw)
        s = 1.0 / cfg.get("meters_per_tile", 2.0)
        o.scale = (s, s, s)
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.object.transform_apply(scale=True)
        return o
    raise ValueError(f"unknown piece kind: {kind}. Known: prop_<{'|'.join(props3d.PROPS)}>, floor, wall_<{'|'.join(WALL_KINDS)}>, door, window, "
                     "fence, stairs, roof, crate, barricade, tower")
