"""Render a 1x1 floor tile, measure the diamond, tune px-per-unit until it equals tile_w x tile_h (+-1px).
Usage: blender -b --python calibrate.py -- payload.json  -> writes <payload>.result.json"""
import json
import os
import sys

import numpy as np

payload = json.load(open(sys.argv[sys.argv.index("--") + 1]))
sys.path.insert(0, payload["blender_dir"])
import bpy  # noqa: E402
import kitbash  # noqa: E402
import scene_rig as rig  # noqa: E402

cfg = dict(payload["cfg"])
tw, th = rig.expected_diamond(cfg["tile_w"], cfg["camera_mode"])
cfg["ppu"] = rig.default_ppu(cfg["tile_w"])
path = os.path.join(payload["out_dir"], "calibration_tile.png")
os.makedirs(payload["out_dir"], exist_ok=True)


def measure():
    """Sub-pixel diamond size from alpha coverage (area = w*h/2 at the tile aspect), plus the vertical centre."""
    rig.reset()
    _, cam = rig.setup(cfg)
    kitbash.floor_tile(cfg, "plain", "concrete")
    rig.render(path)
    img = bpy.data.images.load(path, check_existing=False)
    W, H = img.size
    al = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)[::-1, :, 3]
    bpy.data.images.remove(img)
    w = float(np.sqrt(2 * al.sum() * tw / th))
    ys = np.where(al.max(axis=1) > 0.5)[0]
    return w, w * th / tw, (ys.max() + ys.min()) / 2, rig.origin_px(cam, cfg)


for i in range(8):
    w, h, cy, (ox, oy) = measure()
    if abs(w - tw) <= 0.25:
        break
    cfg["ppu"] *= tw / w
ok = abs(w - tw) <= 0.5 and abs(h - th) <= 0.5 and abs(cy - oy) <= 1.5
json.dump({"ok": bool(ok), "method": "area", "ppu": cfg["ppu"], "measured": [round(w, 2), round(h, 2)], "expected": [tw, th],
           "centre_y": float(cy), "origin_y": float(oy), "iterations": i + 1},
          open(sys.argv[sys.argv.index("--") + 1].replace(".json", ".result.json"), "w"))
