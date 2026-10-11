"""Smoke test: calibrate, then wall set + floor tile end to end."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from isoforge.config import load
from isoforge import blender as B

cfg = load()
print("calibrate:", B.calibrate(cfg))
jobs = [{"name": "floor_asphalt_cracked", "kind": "floor", "params": {"variant": "cracked", "mat": "asphalt", "seed": 3}}]
jobs += [{"name": f"wall_concrete_{k}", "kind": f"wall_{k}", "params": {"mat": "concrete", "seed": 5}}
         for k in ("nw", "ne", "corner", "end_nw", "end_ne", "t_nw", "t_ne")]
for r in B.render_pieces(cfg, jobs):
    print(r["file"], r["size"], r["pivot"])
