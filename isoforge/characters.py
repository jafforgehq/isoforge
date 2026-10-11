"""Characters: rigged low-poly humanoid -> 8-direction sprite sheets (+ optional .glb with animations)."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import blender as B
from .config import Config
from .manifest import Manifest
from .util import get_logger, slug

DIRS = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
ANIMS = ["idle", "walk", "attack", "death"]
PRESETS = ["survivor", "soldier", "zombie"]


def render_character(cfg: Config, name: str, preset: str = "survivor", params: dict | None = None,
                     anims: list | None = None, directions: int = 8, meters_per_tile: float = 2.0,
                     height_m: float | None = None) -> list[dict]:
    anims = anims or ANIMS
    if preset not in PRESETS or not set(anims) <= set(ANIMS) or directions not in (1, 4, 8):
        raise ValueError(f"preset in {PRESETS}, anims subset of {ANIMS}, directions 1|4|8")
    name = slug(name)
    if height_m:  # humanoid is 1.72 m at scale 1; sprite size follows meters_per_tile
        params = {**(params or {}), "scale": height_m / 1.72}
    W, H = cfg.tile_w * 2, round(cfg.tile_w * 2.2)
    cp = B._cfg_payload(cfg, B.ensure_calibrated(cfg))
    cp.update(canvas=[W, H], origin_y=H - 16 - cfg.tile_h / 2, meters_per_tile=meters_per_tile)
    d = cfg.sub("renders") / f"char_{name}"
    res = B.run(cfg, "render_anim.py", {"cfg": cp, "name": name, "preset": preset, "params": params or {}, "anims": anims,
                                        "directions": directions, "out_dir": str(d)}, timeout=1800)
    ox, oy = res["origin"]
    # one union box for every frame so all sheets of a character share frame size and pivot
    x0, y0, y1 = 1e9, 1e9, 0
    half = cfg.tile_w // 2
    for a in res["anims"].values():
        for fl in a["files"].values():
            for f in fl:
                bb = Image.open(f).getchannel("A").point(lambda v: 255 if v > 127 else 0).getbbox()
                if bb:
                    half = max(half, round(ox - bb[0]), round(bb[2] - ox))
                    y0, y1 = min(y0, bb[1]), max(y1, bb[3])
    bottom = max(y1, round(oy + cfg.tile_h / 2))
    box = (round(ox) - half, int(y0), round(ox) + half, bottom)
    fw, fh = box[2] - box[0], box[3] - box[1]
    man, out = Manifest(cfg.out), []
    for a, info in res["anims"].items():
        sheet = Image.new("RGBA", (fw * info["frames"], fh * len(info["files"])))
        for r, (dname, fl) in enumerate(info["files"].items()):
            for c, f in enumerate(fl):
                sheet.alpha_composite(Image.open(f).convert("RGBA").crop(box), (c * fw, r * fh))
        path = cfg.sub("sprites") / f"{name}_{a}.png"
        sheet.save(path)
        meta = dict(kind="sheet", piece="character", character=name, anim=a, preset=preset, params=params or {}, backend="blender",
                    file=str(path.relative_to(cfg.out)), size=[fw, fh], pivot={"x": fw // 2, "y": fh},
                    sheet={"frame": [fw, fh], "frames": info["frames"], "fps": info["fps"], "loop": info["loop"],
                           "directions": DIRS[:directions], "layout": "rows = directions, columns = frames"},
                    camera_mode=cfg.camera_mode, tile=[cfg.tile_w, cfg.tile_h], meters_per_tile=meters_per_tile,
                    generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        out.append(man.upsert(f"{name}_{a}", **meta))
    man.upsert(name, kind="character", preset=preset, params=params or {}, children=[f"{name}_{a}" for a in res["anims"]],
               file=None, size=None, pivot=None)
    get_logger(cfg.out).info("character %s %s %dx%d frames, %d dirs", name, preset, fw, fh, directions)
    return out


def export_character_model(cfg: Config, name: str, preset: str = "survivor", params: dict | None = None,
                           anims: list | None = None, engine: str = "generic", formats: list | None = None,
                           up: str | None = None, forward: str | None = None, texture_size: int = 512,
                           height_m: float | None = None) -> dict:
    """Skinned character as .glb/.fbx with all animations (idle/walk/attack/death) for 3D engines."""
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {PRESETS}")
    fm = [f for f in (formats or B.ENGINE_PRESETS[engine]["formats"]) if f in ("glb", "fbx")] or ["glb"]
    return B.build_models(cfg, [{"name": slug(name) + "_3d", "kind": "character",
                                 "params": {"preset": preset, "build": params or {}, "anims": anims or ANIMS}}],
                          engine=engine, formats=fm, up=up, forward=forward, texture_size=texture_size, height_m=height_m)[0]
