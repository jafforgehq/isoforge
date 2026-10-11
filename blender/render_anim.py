"""Render a character: every animation x 8 directions x frames through the shared iso rig, one Blender session.
payload: {cfg, name, preset, params, anims, directions, out_dir, blender_dir}"""
import json
import math
import os
import sys

pj = sys.argv[sys.argv.index("--") + 1]
payload = json.load(open(pj))
sys.path.insert(0, payload["blender_dir"])
import bpy  # noqa: E402
import character as C  # noqa: E402
import scene_rig as rig  # noqa: E402

cfg = payload["cfg"]
os.makedirs(payload["out_dir"], exist_ok=True)
DIRS = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
rig.reset()
sc, cam = rig.setup(cfg)
sc.eevee.taa_render_samples = 32
arm, mesh = C.build(cfg, payload.get("preset", "survivor"), **payload.get("params", {}))
s = 1.0 / cfg.get("meters_per_tile", 2.0)       # metres -> tile units
arm.scale = (s, s, s)
acts = C.make_actions(arm, arm["hunch"], payload["anims"])
ox, oy = rig.origin_px(cam, cfg)
out = {"origin": [ox, oy], "anims": {}}
for a in payload["anims"]:
    n, fps, loop = C.ANIMS[a]
    arm.animation_data.action = acts[a]
    files = {}
    for di, d in enumerate(DIRS[:payload.get("directions", 8)]):
        arm.rotation_euler.z = math.radians(45 - 45 * di)   # S faces screen-down; clockwise on screen
        files[d] = []
        for f in range(n):
            sc.frame_set(f + 1)
            p = os.path.join(payload["out_dir"], f"{payload['name']}_{a}_{d}_{f:02d}.png")
            rig.render(p)
            files[d].append(p)
    out["anims"][a] = {"fps": fps, "loop": loop, "frames": n, "files": files}
json.dump(out, open(pj.replace(".json", ".result.json"), "w"))
