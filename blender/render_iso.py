"""Render jobs through the shared rig. Usage: blender -b --python render_iso.py -- payload.json
payload: {cfg:{...}, jobs:[{name,kind,params,directions}], out_dir, blender_dir}
Writes result.json next to payload: [{name, canvas, origin:[x,y]}]"""
import json
import math
import os
import sys

payload = json.load(open(sys.argv[sys.argv.index("--") + 1]))
sys.path.insert(0, payload["blender_dir"])
import bpy  # noqa: E402
import kitbash  # noqa: E402
import scene_rig as rig  # noqa: E402

cfg = payload["cfg"]
os.makedirs(payload["out_dir"], exist_ok=True)
results = []
for job in payload["jobs"]:
    n = max(1, int(job.get("directions", 1)))
    for k in range(n):
        rig.reset()
        jcfg = dict(cfg)
        obj = kitbash.build(jcfg, job["kind"], **job.get("params", {}))
        dims = obj.dimensions
        fp = job.get("params", {}).get("footprint")
        if not fp:  # props size themselves: smallest whole-tile footprint that holds them (centred on the origin)
            fp = (max(1, math.ceil(dims.x - 0.05)), max(1, math.ceil(dims.y - 0.05))) if job["kind"].startswith("prop_") else (1, 1)
        if n > 1:
            fp = (max(fp),) * 2     # rotated copies must share one footprint
        jcfg.update(rig.canvas_for(jcfg, fp[0], fp[1], dims.z))
        _, cam = rig.setup(jcfg)
        obj.rotation_euler.z = math.radians(360 / n * k)
        name = job["name"] if n == 1 else f"{job['name']}_d{k}"
        path = os.path.join(payload["out_dir"], f"{name}_canvas.png")
        rig.render(path)
        ox, oy = rig.origin_px(cam, jcfg)          # nominal tile geometry (calibration targets the visible 128x64 px)
        hw, qh = jcfg["tile_w"] * (fp[0] + fp[1]) / 4, jcfg["tile_h"] * (fp[0] + fp[1]) / 4
        res = {"name": name, "canvas": path, "footprint": list(fp), "diamond": [ox - hw, oy - qh, ox + hw, oy + qh],
               "pivot": [ox + jcfg["tile_w"] * (fp[0] - fp[1]) / 4, oy + qh]}   # bottom vertex of the footprint diamond
        if job.get("shadow"):  # shadow pass: piece invisible to camera but still casting onto a white ground plane
            me = bpy.data.meshes.new("ground")
            me.from_pydata([(-12, -12, 0), (12, -12, 0), (12, 12, 0), (-12, 12, 0)], [], [(0, 1, 2, 3)])
            g = bpy.data.objects.new("ground", me)
            bpy.context.scene.collection.objects.link(g)
            gm = bpy.data.materials.new("white")
            gm.use_nodes = True
            gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 1, 1, 1)
            gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1
            g.data.materials.append(gm)
            obj.visible_camera = False
            res["shadow_canvas"] = os.path.join(payload["out_dir"], f"{name}_shadowpass.png")
            rig.render(res["shadow_canvas"])
        results.append(res)
json.dump(results, open(sys.argv[sys.argv.index("--") + 1].replace(".json", ".result.json"), "w"))
