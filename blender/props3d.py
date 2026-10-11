"""Parametric 3D props in METRES, base at z=0, front = -Y. Low-poly, flat shaded, weathered.
Registry PROPS: name -> fn(cfg, **params) -> object. Used for .glb/.fbx export and (scaled) iso sprites."""
import math
import random

import bpy
from mathutils import Vector, noise

import kitbash as K


def _prim(kind, **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(**kw)
    o = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    return o


def jitter(o, amp, seed=0):
    off = Vector((seed * 7.3, seed * 3.1, seed * 5.7))
    for v in o.data.vertices:
        p = v.co * 3 + off
        v.co += Vector((noise.noise(p), noise.noise(p + Vector((9, 0, 0))), noise.noise(p + Vector((0, 9, 0))))) * amp


def cyl(name, r, h, z0, mat, seg=16, x=0.0, y=0.0, r2=None, bevel=0.004, rot=None):
    o = _prim("cone", vertices=seg, radius1=r, radius2=r if r2 is None else r2, depth=h, location=(x, y, z0 + h / 2))
    o.name = name
    if rot:
        o.rotation_euler = rot
    return K._finish(o, mat, bevel)


def barrel(cfg, rust=0.7, seed=0, **_):
    m = K.make_material("rust", seed)
    paint = K.make_material("concrete", seed + 1, base=(0.16, 0.22, 0.14))
    body = cyl("body", .29, .88, 0, paint if rust < 0.5 else m, 20, bevel=0.006)
    parts = [body] + [cyl(f"ring{i}", .305, .035, z, m, 20, bevel=0.004) for i, z in enumerate((.04, .42, .81))]
    parts.append(cyl("lid", .26, .02, .88, m, 20))
    for o in parts:
        jitter(o, .004 + .01 * rust, seed)
    return K.join(parts, "barrel")


def crate(cfg, size=0.9, seed=0, **_):
    wood, rust = K.make_material("wood", seed), K.make_material("rust", seed + 1)
    s = size / 2
    parts = [K.box("body", -s, -s, s, s, 0, size, wood, seed, rough=.006, cuts=3)]
    for i, (x0, y0, x1, y1) in enumerate([(-s - .01, -s - .01, s + .01, -s + .06), (-s - .01, s - .06, s + .01, s + .01)]):
        parts.append(K.box(f"band{i}", x0, y0, x1, y1, 0, size + .01, rust, seed + i, bevel=0))
    return K.join(parts, "crate")


def container(cfg, colour=(0.36, 0.14, 0.1), seed=0, **_):
    L, W, H = 6.0, 2.44, 2.6
    paint = K.make_material("concrete", seed, base=colour)
    dark = K.make_material("rust", seed + 1)
    parts = [K.box("shell", -W / 2, -L / 2, W / 2, L / 2, 0.15, H, paint, seed, rough=.01, cuts=6)]
    for i in range(14):  # side corrugation ribs
        y = -L / 2 + .25 + i * (L - .5) / 13
        for sx in (-1, 1):
            parts.append(K.box(f"rib{i}{sx}", sx * W / 2 - (0.03 if sx < 0 else 0), y - .05, sx * W / 2 + (0.03 if sx > 0 else 0), y + .05, .25, H - .1, paint, seed + i, bevel=0))
    parts += [K.box("base", -W / 2, -L / 2, W / 2, L / 2, 0, .15, dark, seed + 2)]
    parts += [K.box(f"door{i}", -W / 2 + i * W / 2 + .03, -L / 2 - .04, -W / 2 + (i + 1) * W / 2 - .03, -L / 2, .25, H - .1, paint, seed + 3 + i, bevel=0) for i in range(2)]
    return K.join(parts, "container")


def car(cfg, variant="sedan", colour=(0.42, 0.15, 0.1), wrecked=False, seed=0, **_):
    L, W = {"sedan": (4.4, 1.8), "van": (4.8, 1.95), "pickup": (5.1, 1.95)}[variant]
    H = {"sedan": 1.45, "van": 1.95, "pickup": 1.75}[variant]
    paint, glass, tyre = K.make_material("concrete", seed, base=colour), K._glass(), K.make_material("concrete", seed + 2, base=(.04, .04, .04))
    parts = [K.box("lower", -W / 2, -L / 2, W / 2, L / 2, .32, .86, paint, seed, rough=.008, cuts=5)]
    cab0, cab1 = (-L * .22, L * .2) if variant == "sedan" else (-L * .2, L * .36) if variant == "pickup" else (-L * .5 + .1, L * .5 - .1)
    top = K.box("cabin", -W / 2 + .1, cab0, W / 2 - .1, cab1, .86, H, paint, seed + 1, rough=.006, cuts=4)
    parts.append(top)
    parts.append(K.box("windows", -W / 2 + .08, cab0 + .12, W / 2 - .08, cab1 - .12, .98, H - .1, glass, seed, bevel=0))
    if wrecked:
        parts = [o for o in parts]
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        if wrecked and i == 3:
            continue
        parts.append(cyl(f"wheel{i}", .34, .24, 0, tyre, 14, sx * (W / 2 - .02), sy * L * .33, rot=(0, math.pi / 2, 0)))
        parts[-1].location.z = .34
    o = K.join(parts, f"car_{variant}")
    if wrecked:
        o.rotation_euler = (math.radians(3), math.radians(4), 0)
    return o


def tree(cfg, variant="pine", seed=0, **_):
    bark, leaf = K.make_material("wood", seed), K.make_material("concrete", seed + 1, base=(.16, .26, .12))
    parts = [cyl("trunk", .18, 2.2, 0, bark, 8, r2=.1, bevel=0)]
    rnd = random.Random(seed)
    if variant == "pine":
        for i in range(4):
            parts.append(cyl(f"cone{i}", 1.3 - i * .27, 1.5, 1.3 + i * .9, leaf, 9, r2=.05, bevel=0))
    else:
        for i in range(3):
            s = _prim("ico_sphere", subdivisions=1, radius=1.3 - i * .25, location=(rnd.uniform(-.4, .4), rnd.uniform(-.4, .4), 2.8 + i * .7))
            parts.append(K._finish(s, leaf, 0))
    for o in parts[1:]:
        jitter(o, .05, seed)
    return K.join(parts, f"tree_{variant}")


def rock(cfg, size=1.0, seed=0, **_):
    o = _prim("ico_sphere", subdivisions=2, radius=size / 2, location=(0, 0, size * .3))
    jitter(o, size * .18, seed)
    o.scale.z = .7
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    z0 = min(v.co.z for v in o.data.vertices)
    for v in o.data.vertices:
        v.co.z -= z0
    return K._finish(o, K.make_material("concrete", seed + 4, base=(.35, .33, .3)), 0)


def lamp_post(cfg, height=4.5, seed=0, **_):
    iron = K.make_material("rust", seed)
    parts = [cyl("pole", .06, height, 0, iron, 8, r2=.045), cyl("base", .14, .25, 0, iron, 8, bevel=0),
             K.box("arm", -.04, 0, .04, .9, height - .1, height - .04, iron, seed, bevel=0),
             K.box("lamp", -.14, .7, .14, 1.05, height - .22, height - .08, K._glass(), seed, bevel=0)]
    return K.join(parts, "lamp_post")


def fuel_tank(cfg, seed=0, **_):
    steel, rust = K.make_material("rust", seed), K.make_material("concrete", seed + 1, base=(.3, .3, .28))
    o = cyl("tank", .85, 3.4, 0, rust, 18, rot=(math.pi / 2, 0, 0), bevel=0.01)
    o.location.z = 1.25
    parts = [o] + [K.box(f"saddle{i}", -.6, -1.0 + i * 2.0 - .08, .6, -1.0 + i * 2.0 + .08, 0, .6, steel, seed + i, bevel=0) for i in range(2)]
    return K.join(parts, "fuel_tank")


def sandbags(cfg, rows=3, per_row=5, seed=0, **_):
    m, rnd = K.make_material("wood", seed, base=(.4, .35, .24)), random.Random(seed)
    parts = []
    for r in range(rows):
        for i in range(per_row):
            s = _prim("uv_sphere", segments=8, ring_count=5, radius=.25, location=((i - per_row / 2 + .5 + (.5 if r % 2 else 0) - .25) * .55, rnd.uniform(-.03, .03), .12 + r * .2))
            s.scale = (1.15, .8, .55)
            bpy.context.view_layer.objects.active = s
            s.select_set(True)
            bpy.ops.object.transform_apply(scale=True)
            parts.append(K._finish(s, m, 0))
    return K.join(parts, "sandbags")


PROPS = {"barrel": barrel, "crate3d": crate, "container": container, "car": car, "tree": tree, "rock": rock,
         "lamp_post": lamp_post, "fuel_tank": fuel_tank, "sandbags": sandbags}
