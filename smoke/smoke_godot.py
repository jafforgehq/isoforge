"""Smoke test: sync + tileset + place barrel in sandbox project. Usage: run_smoke_godot.py <godot_project>"""
import json
import sys
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from isoforge.config import load
from isoforge import blender as B, godot as G

cfg = load()
proj = sys.argv[1]
B.render_pieces(cfg, [{"name": "floor_asphalt_plain", "kind": "floor", "params": {"mat": "asphalt", "seed": 7}}])
tiles = ["floor_asphalt_cracked", "floor_asphalt_plain", "wall_concrete_nw", "wall_concrete_ne", "wall_concrete_corner"]
print(json.dumps(G.sync_to_godot(cfg, proj, tiles + ["rusty_oil_barrel"]), indent=1))
ts = G.build_tileset(cfg, proj, "city", tiles)
print(json.dumps(ts, indent=1))
print(G.place_in_scene(cfg, proj, "scenes/main.tscn", "rusty_oil_barrel", 400, 300, "Props", "OilBarrel"))
print(G.make_scene(cfg, proj, "rusty_oil_barrel", footprint=True))
