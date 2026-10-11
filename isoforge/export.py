"""Engine-agnostic export. Every asset is a PNG + pivot; this adds metadata other engines can consume.
 generic: PNGs + isoforge_assets.json (pivot px, pivot normalised for Unity/Unreal/Defold, tile grid info)
 tiled:   Tiled .tsx image-collection tilesets (isometric grid) - imported by Godot, Unity (SuperTiled2Unity),
          GameMaker, Defold, Phaser, LDtk-compatible tools, etc."""
import json
import os
import shutil
from pathlib import Path
from xml.sax.saxutils import quoteattr

from PIL import Image

from .config import Config
from .godot import _unique_dest
from .manifest import Manifest
from .util import safe_join

ENGINE_HINTS = {
    "unity": "Sprite: Pixels Per Unit = tile_w, Pivot = Custom (pivot_norm_bl). Grid: Cell Layout Isometric, Cell Size (1, tile_h/tile_w).",
    "unreal": "Paper2D: Pixels Per Unit = 1 and set Sprite pivot to Custom using pivot_px (top-left origin).",
    "gamemaker": "Sprite origin = pivot_px (x, y). Isometric: set room tile size = tile_w x tile_h.",
    "defold": "Atlas animation pivot = pivot_norm_bl; use tile_w/tile_h for the iso grid.",
    "phaser": "sprite.setOrigin(pivot_norm_tl.x, pivot_norm_tl.y); iso projection 2:1 with tile_w x tile_h.",
}


def export_assets(cfg: Config, assets: list[str], dest_dir: str, fmt: str = "generic", set_name: str = "isoforge",
                  subdirs: dict | None = None, meta_dir: str = ".") -> dict:
    """subdirs maps kind -> folder inside dest (tiles|sprites|models); meta_dir = where isoforge_assets.json goes."""
    subdirs = {"tiles": "tiles", "sprites": "sprites", "models": "models", **(subdirs or {})}
    dest = Path(dest_dir).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    man = Manifest(cfg.out)
    meta, files = {}, {}
    for n in man.expand(assets):
        rec = man.get(n)
        if not rec:
            raise ValueError(f"unknown asset '{n}'")
        src = safe_join(cfg.out, rec["file"])
        sub = {"tile": "tiles", "model": "models"}.get(rec["kind"], "sprites")
        out, st = _unique_dest(safe_join(dest, subdirs[sub], src.name), src)
        out.parent.mkdir(parents=True, exist_ok=True)
        if st != "unchanged":
            shutil.copy2(src, out)
        files[n] = out
        mdir = safe_join(dest, meta_dir)
        rel = os.path.relpath(out, mdir)
        if rec["kind"] == "model":
            ex = rec.get("export", {})
            for f in rec.get("all_files", []):   # companions: other formats, LODs, albedo textures
                cf = safe_join(cfg.out, f)
                cd, _ = _unique_dest(out.parent / cf.name, cf)
                if not cd.exists():
                    shutil.copy2(cf, cd)
            meta[n] = {"file": rel, "kind": "model", "files": {k: os.path.relpath(out.parent / Path(v).name, mdir) for k, v in rec.get("files", {}).items()},
                       "units": "metres", "up": ex.get("up"), "forward": ex.get("forward"), "engine": ex.get("engine"),
                       "lods": [{"lod": l["lod"], "tris": l["tris"], "files": {k: os.path.relpath(out.parent / Path(v).name, mdir) for k, v in l["files"].items()}} for l in rec.get("lods", [])],
                       "animations": rec.get("animations")}
            continue
        w, h = rec["size"]
        px, py = rec["pivot"]["x"], rec["pivot"]["y"]
        meta[n] = {"file": rel, "kind": rec["kind"], "piece": rec.get("piece"),
                   "size": [w, h], "pivot_px": [px, py],
                   "pivot_norm_tl": [px / w, py / h],            # origin top-left, y down
                   "pivot_norm_bl": [px / w, 1 - py / h],        # origin bottom-left, y up (Unity)
                   "style": rec.get("style"), "seed": rec.get("seed"), "sheet": rec.get("sheet")}
    doc = {"tile": [cfg.tile_w, cfg.tile_h], "camera_mode": cfg.camera_mode, "projection": "2:1 dimetric"
           if cfg.camera_mode == "dimetric_2_1" else "isometric", "pivot_convention": "bottom-centre of tile diamond",
           "engine_hints": ENGINE_HINTS, "assets": meta}
    mp = safe_join(dest, meta_dir)
    mp.mkdir(parents=True, exist_ok=True)
    (mp / "isoforge_assets.json").write_text(json.dumps(doc, indent=2))
    result = {"dest": str(dest), "assets": list(meta), "metadata": str((mp / "isoforge_assets.json").relative_to(dest))}
    if fmt == "tiled":
        result["tilesets"] = _tiled(cfg, {k: v for k, v in meta.items() if v["kind"] != "model"}, dest / meta_dir, set_name)
    elif fmt != "generic":
        raise ValueError("fmt must be 'generic' or 'tiled'")
    return result


def _tiled(cfg: Config, meta: dict, dest: Path, set_name: str) -> list[str]:
    """One .tsx per group (floor / other). Images padded to a uniform width with the pivot at bottom-centre,
    so one tileoffset fits all (Tiled aligns an iso tile's image bottom-left to the cell's bottom-left)."""
    tw, th = cfg.tile_w, cfg.tile_h
    groups = {"floor": [], "objects": []}
    for n, m in meta.items():
        groups["floor" if m["piece"] == "floor" else "objects"].append((n, m))
    out = []
    for g, items in groups.items():
        if not items:
            continue
        cw = 2 * max(max(m["pivot_px"][0] for _, m in items), tw // 2)
        ch = max(m["size"][1] for _, m in items)
        d = dest / "tiled" / f"{set_name}_{g}"
        d.mkdir(parents=True, exist_ok=True)
        tiles = []
        for i, (n, m) in enumerate(items):
            im = Image.open(dest / m["file"]).convert("RGBA")
            canvas = Image.new("RGBA", (cw, im.height))
            canvas.alpha_composite(im, (cw // 2 - m["pivot_px"][0], 0))
            p = d / f"{n}.png"
            canvas.save(p)
            tiles.append(f'  <tile id="{i}"><image width="{cw}" height="{im.height}" source={quoteattr(p.name)}/></tile>')
        tsx = (f'<?xml version="1.0" encoding="UTF-8"?>\n<tileset version="1.10" name={quoteattr(set_name + "_" + g)} '
               f'tilewidth="{cw}" tileheight="{ch}" tilecount="{len(items)}" columns="0" objectalignment="bottom">\n'
               f' <tileoffset x="{-(cw - tw) // 2}" y="0"/>\n <grid orientation="isometric" width="{tw}" height="{th}"/>\n'
               + "\n".join(tiles) + "\n</tileset>\n")
        (d / f"{set_name}_{g}.tsx").write_text(tsx)
        out.append(str((d / f"{set_name}_{g}.tsx").relative_to(dest)))
    return out
