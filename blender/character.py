"""Low-poly humanoid: rigid-skinned single mesh + armature + short animation set. Metres, feet on z=0, front = -Y.
Presets give variation (survivor/soldier/zombie); colours and an optional AI texture on clothes vary the look."""
import math

import bpy
from mathutils import Vector

import kitbash as K

# name, parent, head, tail  (L = +x). Legs/arms point down, spine/head up.
def _bones(s):
    b = [("root", None, (0, 0, 0), (0, 0, .1)), ("hips", "root", (0, 0, .92 * s), (0, 0, 1.02 * s)),
         ("torso", "hips", (0, 0, 1.02 * s), (0, 0, 1.45 * s)), ("head", "torso", (0, 0, 1.45 * s), (0, 0, 1.72 * s))]
    for n, sx in (("L", 1), ("R", -1)):
        b += [(f"upper_arm.{n}", "torso", (sx * .24 * s, 0, 1.40 * s), (sx * .24 * s, 0, 1.12 * s)),
              (f"fore_arm.{n}", f"upper_arm.{n}", (sx * .24 * s, 0, 1.12 * s), (sx * .24 * s, 0, .86 * s)),
              (f"thigh.{n}", "hips", (sx * .1 * s, 0, .92 * s), (sx * .1 * s, 0, .5 * s)),
              (f"shin.{n}", f"thigh.{n}", (sx * .1 * s, 0, .5 * s), (sx * .1 * s, 0, .08 * s))]
    return b


PRESETS = {
    "survivor": dict(skin=(.55, .38, .28), shirt=(.22, .3, .22), trousers=(.2, .2, .25), boots=(.08, .07, .06), hunch=0.0, rough=0.0),
    "soldier": dict(skin=(.5, .36, .27), shirt=(.25, .28, .2), trousers=(.2, .22, .16), boots=(.05, .05, .05), hunch=0.0, rough=0.0),
    "zombie": dict(skin=(.38, .5, .32), shirt=(.28, .2, .17), trousers=(.16, .15, .14), boots=(.08, .06, .05), hunch=0.35, rough=0.012),
}


def build(cfg, preset="survivor", scale=1.0, tex=None, seed=0, **colours):
    p = {**PRESETS[preset], **{k: v for k, v in colours.items() if v}}
    s = scale
    skin = K.make_material("concrete", seed, base=p["skin"])
    shirt = K.make_material("concrete", seed + 1, tex=tex, base=p["shirt"])
    trou = K.make_material("concrete", seed + 2, base=p["trousers"])
    boot = K.make_material("concrete", seed + 3, base=p["boots"])
    sc = bpy.context.scene

    ad = bpy.data.armatures.new("Rig")
    arm = bpy.data.objects.new("Rig", ad)
    sc.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent, head, tail in _bones(s):
        e = ad.edit_bones.new(name)
        e.head, e.tail = head, tail
        if parent:
            e.parent = ad.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    parts = []  # (bone, x0,y0,x1,y1,z0,z1, material)
    parts.append(("hips", -.17 * s, -.1 * s, .17 * s, .1 * s, .88 * s, 1.04 * s, trou))
    parts.append(("torso", -.2 * s, -.115 * s, .2 * s, .115 * s, 1.04 * s, 1.45 * s, shirt))
    parts.append(("head", -.12 * s, -.12 * s, .12 * s, .12 * s, 1.47 * s, 1.72 * s, skin))
    parts.append(("head", -.125 * s, -.04 * s, .125 * s, .13 * s, 1.64 * s, 1.74 * s, boot if preset != "zombie" else trou))  # hair/helmet
    for n, sx in (("L", 1), ("R", -1)):
        x = sx * .24 * s
        parts += [(f"upper_arm.{n}", x - .05 * s, -.05 * s, x + .05 * s, .05 * s, 1.12 * s, 1.42 * s, shirt),
                  (f"fore_arm.{n}", x - .045 * s, -.045 * s, x + .045 * s, .045 * s, .94 * s, 1.12 * s, shirt),
                  (f"fore_arm.{n}", x - .04 * s, -.04 * s, x + .04 * s, .04 * s, .84 * s, .94 * s, skin),
                  (f"thigh.{n}", sx * .1 * s - .07 * s, -.07 * s, sx * .1 * s + .07 * s, .07 * s, .5 * s, .92 * s, trou),
                  (f"shin.{n}", sx * .1 * s - .06 * s, -.06 * s, sx * .1 * s + .06 * s, .06 * s, .1 * s, .5 * s, trou),
                  (f"shin.{n}", sx * .1 * s - .065 * s, -.12 * s, sx * .1 * s + .065 * s, .07 * s, 0, .1 * s, boot)]
    objs = []
    for i, (bone, x0, y0, x1, y1, z0, z1, m) in enumerate(parts):
        o = K.box(f"part{i}", x0, y0, x1, y1, z0, z1, m, seed + i, rough=p["rough"], cuts=2 if p["rough"] else 0, bevel=0.008)
        vg = o.vertex_groups.new(name=bone)
        vg.add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
        objs.append(o)
    mesh = K.join(objs, "body")
    mesh.parent = arm
    mod = mesh.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    arm["preset"], arm["hunch"] = preset, p["hunch"]
    return arm, mesh


# ------------------------------------------------------------------ animation
# (frames, fps, loop). Pose functions take t in [0,1) and return {bone: (rx, ry, rz) radians, 'hips_y': bob metres}.
ANIMS = {"idle": (6, 6, True), "walk": (8, 12, True), "attack": (6, 12, False), "death": (8, 10, False)}


def pose(anim, t, hunch=0.0):
    sn, cs = math.sin(2 * math.pi * t), math.cos(2 * math.pi * t)
    P = {"torso": (hunch, 0, 0), "head": (-hunch * .6, 0, 0)}
    arms_up = -1.2 * hunch  # zombies hold arms forward
    P.update({"upper_arm.L": (arms_up, 0, 0), "upper_arm.R": (arms_up, 0, 0), "fore_arm.L": (arms_up * .4, 0, 0), "fore_arm.R": (arms_up * .4, 0, 0)})
    hips_y = 0.0
    if anim == "idle":
        P["torso"] = (hunch + .03 * sn, 0, 0)
        P["upper_arm.L"], P["upper_arm.R"] = (arms_up + .04 * sn, 0, -.06), (arms_up - .04 * sn, 0, .06)
        hips_y = .006 * sn
    elif anim == "walk":
        sw = .65 if not hunch else .45
        P["thigh.L"], P["thigh.R"] = (sw * sn, 0, 0), (-sw * sn, 0, 0)
        P["shin.L"], P["shin.R"] = (.8 * max(0, cs), 0, 0), (.8 * max(0, -cs), 0, 0)
        P["upper_arm.L"] = (arms_up - .55 * sn * (0.3 if hunch else 1), 0, 0)
        P["upper_arm.R"] = (arms_up + .55 * sn * (0.3 if hunch else 1), 0, 0)
        P["torso"] = (hunch, 0, .1 * sn)
        hips_y = .025 * abs(cs)
    elif anim == "attack":
        k = t * 5 / 5
        wind = min(1.0, k / .4)                # raise
        hit = max(0.0, (k - .4) / .3) if k < .7 else max(0.0, 1 - (k - .7) / .3)  # strike then recover
        P["upper_arm.R"] = (-2.6 * wind + 3.0 * min(1, hit) * (1 if k > .4 else 0), 0, 0)
        P["fore_arm.R"] = (-.6 * wind, 0, 0)
        P["torso"] = (hunch + .25 * hit, 0, -.3 * wind + .5 * hit)
        P["thigh.L"], P["thigh.R"] = (.25 * hit, 0, 0), (-.2 * hit, 0, 0)
    elif anim == "death":
        e = t * t * (3 - 2 * t)
        P["hips"] = (1.45 * e, 0, 0)
        P["thigh.L"], P["thigh.R"] = (-.5 * e, 0, 0), (-.2 * e, 0, 0)
        P["shin.L"], P["shin.R"] = (.5 * e, 0, 0), (.9 * e, 0, 0)
        P["upper_arm.L"], P["upper_arm.R"] = (-.2 - .9 * e, 0, .9 * e), (-.2 - .5 * e, 0, -.9 * e)
        P["head"] = (.3 * e, 0, 0)
        hips_y = -.8 * e
    return P, hips_y


def make_actions(arm, hunch=0.0, anims=None):
    """One Action per animation, keyed every frame (low frame counts, so cheap). Returns {name: action}."""
    acts = {}
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    arm.animation_data_create()
    for name in anims or ANIMS:
        n, fps, loop = ANIMS[name]
        act = bpy.data.actions.new(f"{arm.name}_{name}")
        arm.animation_data.action = act
        for f in range(n):
            P, hy = pose(name, f / n if loop else f / (n - 1), hunch)
            for pb in arm.pose.bones:
                pb.rotation_euler = P.get(pb.name, (0, 0, 0))
                pb.keyframe_insert("rotation_euler", frame=f + 1)
            hips = arm.pose.bones["hips"]
            hips.location = (0, hy, 0)          # bone-local Y = up for the hips bone
            hips.keyframe_insert("location", frame=f + 1)
        acts[name] = act
    bpy.ops.object.mode_set(mode="OBJECT")
    return acts
