"""Smoke test: one AI prop end to end (needs Draw Things API up)."""
import sys
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from isoforge.config import load
from isoforge.backends.drawthings import DrawThings
from isoforge.pipeline_a import generate_asset

cfg = load()
be = DrawThings(cfg.drawthings_url)
print(be.check())
for r in generate_asset(cfg, be, sys.argv[1] if len(sys.argv) > 1 else "a rusty oil barrel", name="rusty_oil_barrel"):
    print({k: r[k] for k in ("file", "seed", "size", "pivot", "gate_passed", "gate_failures", "attempts", "rembg_model")})
