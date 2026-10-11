"""IsoForge MCP server (stdio). Engine-neutral asset factory: generate once, deliver to any project/engine.
Never print to stdout (it is the MCP channel); logs go to output/isoforge.log."""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from isoforge import blender as B  # noqa: E402
from isoforge import godot as G  # noqa: E402
from isoforge import jobs, targets as T  # noqa: E402
from isoforge.backends.drawthings import DrawThings  # noqa: E402
from isoforge.config import load, load_style, save_state, with_layout, ROOT  # noqa: E402
from isoforge.export import export_assets  # noqa: E402
from isoforge.manifest import Manifest  # noqa: E402
from isoforge.pipeline_a import generate_asset as _gen  # noqa: E402
from isoforge.util import safe_join, slug  # noqa: E402

WALL_KINDS = ["nw", "ne", "corner", "end_nw", "end_ne", "t_nw", "t_ne"]  # mirrors blender/kitbash.py SEGS

mcp = MCPServer("isoforge", instructions=(
    "IsoForge makes isometric 2.5D game assets locally (no paid services) and delivers them to ANY engine. "
    "Structure, 3D props, models and characters = Blender; sprite props = AI; Slow tools (generate_*, build_character) return a job_id: "
    "poll job_status(job_id, wait_seconds=60). Register where assets go with register_target, then deliver_assets. "
    "Godot has extra tools (build_tileset, place_in_scene, make_scene)."))


LAYOUT_DOC = ("layout = optional per-call size overrides {tile_w, tile_h, camera_mode, wall_height_px, sprite_max_px}; "
              "nothing is saved, other sessions/projects are unaffected")


def cfg(layout=None):
    return with_layout(load(), layout)


def backend(c):
    return DrawThings(c.drawthings_url)


def _tex(c, texture):
    """texture = asset name from generate_texture, or a file path."""
    if not texture:
        return None
    rec = Manifest(c.out).get(texture)
    return str(safe_join(c.out, rec["file"])) if rec and rec.get("kind") == "texture" else str(Path(texture).expanduser())


def _proj(c, godot_project=None, target=None):
    if target:
        t = T.resolve(c, target)
        if t["type"] != "godot":
            raise ValueError(f"target '{target}' is type {t['type']}, not godot")
        return t["path"]
    p = godot_project or os.environ.get("ISOFORGE_GODOT_PROJECT") or c.godot_project
    if not p and (Path.cwd() / "project.godot").exists():
        p = str(Path.cwd())
    if not p:
        raise ValueError("no Godot project: pass godot_project (or run from the project folder)")
    return p


# ---------------------------------------------------------------- setup / style
@mcp.tool()
def check_setup() -> dict:
    """Report what is installed/running: Blender, Draw Things API, rembg models, calibration, Godot, TripoSR, targets."""
    c = cfg()
    cal = c.out / "calibration.json"
    return {
        "blender": {"ok": Path(c.blender).exists(), "path": c.blender},
        "image_backend": {c.default_backend: backend(c).check() if c.default_backend == "drawthings" else "n/a"},
        "calibrated_profiles": sorted(B._profiles(c)["profiles"]) if cal.exists() else "none yet (calibrate runs automatically on first Blender use)",
        "godot_binary": Path(G.GODOT_BIN).exists(),
        "triposr": "not installed (Pipeline B optional; see README)" if not shutil.which("triposr") else "found",
        "active_style": c.active_style, "tile": [c.tile_w, c.tile_h], "camera_mode": c.camera_mode,
        "targets": T.list_targets(c), "output_dir": str(c.out),
    }


@mcp.tool()
def list_styles() -> list:
    """List style presets (styles/*.toml) and which one is active."""
    c = cfg()
    return [{"name": p.stem, "active": p.stem == c.active_style, **{k: v for k, v in load_style(p.stem).items()
            if k in ("steps", "size", "post_mode", "palette_size", "lora")}} for p in sorted((ROOT / "styles").glob("*.toml"))]


@mcp.tool()
def set_style(name: str) -> dict:
    """Lock the active style for all new assets (existing assets keep theirs; use regenerate to redo)."""
    c = cfg()
    load_style(name)
    return save_state(c, active_style=name)


@mcp.tool()
def calibrate(tile_w: int | None = None, tile_h: int | None = None, camera_mode: str | None = None,
              make_default: bool = False) -> dict:
    """Calibrate the Blender camera for a tile size / camera ('dimetric_2_1' or 'isometric'); each size keeps its own cached
    profile, so several can coexist. tile_h is derived from the camera if omitted (2:1 -> tile_w/2, isometric -> tile_w*0.577).
    make_default=true also saves it as the default for new calls; otherwise pass layout= on each tool call."""
    lay = {k: v for k, v in (("tile_w", tile_w), ("tile_h", tile_h), ("camera_mode", camera_mode)) if v is not None}
    c = cfg(lay)
    if make_default:
        save_state(load(), tile_w=c.tile_w, tile_h=c.tile_h, camera_mode=c.camera_mode, wall_height_px=c.wall_height_px, sprite_max_px=c.sprite_max_px)
    return B.calibrate(c)


# ---------------------------------------------------------------- generation
@mcp.tool()
def generate_asset(subject: str, name: str | None = None, count: int = 1, seed: int | None = None,
                   max_px: int | None = None, style: str | None = None, target: str | None = None, gen_size: int | None = None,
                   layout: dict | None = None) -> dict:
    """AI prop/item/clutter sprite (Pipeline A). Slow (minutes/image): returns job_id. max_px = final sprite size (longest
    edge, default sprite_max_px ~ 3/4 of tile_w); gen_size = generation resolution (512/768 faster drafts, 1024 default).
    `target` picks that project's style if defined. """ + LAYOUT_DOC + """."""
    c = cfg(layout)
    if target and not style:
        style = T.resolve(c, target).get("style")
    jid = jobs.submit(c.out, f"generate_asset:{subject}", lambda: _gen(c, backend(c), subject, name, count, seed, max_px, style, gen_size))
    return {"job_id": jid, "note": "poll job_status(job_id, wait_seconds=60)"}


@mcp.tool()
def job_status(job_id: str, wait_seconds: float = 0) -> dict:
    """State/result of a background job. wait_seconds blocks up to that long (max 120)."""
    return jobs.status(cfg().out, job_id, min(wait_seconds, 120))


@mcp.tool()
def build_floor_tile(variant: str = "plain", material: str = "asphalt", texture: str | None = None,
                     name: str | None = None, seed: int = 0, footprint: list[int] | None = None, layout: dict | None = None) -> list:
    """Blender floor tile (exact tile_w x tile_h diamond). footprint=[fx,fy] makes one slab covering fx x fy tiles. variant: plain|cracked. material: concrete|asphalt|brick|rust|wood.
    """ + LAYOUT_DOC + """."""
    c = cfg(layout)
    n = name or f"floor_{material}_{variant}"
    return B.render_pieces(c, [{"name": n, "kind": "floor", "params": {"variant": variant, "mat": material, "tex": _tex(c, texture), "seed": seed, "footprint": footprint}}])


@mcp.tool()
def build_wall_set(material: str = "concrete", texture: str | None = None, height: int | None = None,
                   seed: int = 5, dilapidated: bool = True, footprint: list[int] | None = None,
                   layout: dict | None = None) -> list:
    """Full matching wall family (nw, ne, corner, end_nw, end_ne, t_nw, t_ne) sharing pivot, height and lighting.
    height = wall height in screen px (default wall_height_px, which scales with tile_w). """ + LAYOUT_DOC + """."""
    c = cfg(layout)
    return B.render_pieces(c, [{"name": f"wall_{material}_{k}", "kind": f"wall_{k}",
                                "params": {"mat": material, "tex": _tex(c, texture), "seed": seed, "height_px": height, "footprint": footprint,
                                           "dilapidated": dilapidated}} for k in WALL_KINDS])


@mcp.tool()
def build_structure(kind: str, params: dict | None = None, name: str | None = None, shadow: bool = False,
                    layout: dict | None = None) -> list:
    """Render any kitbash piece. kind = floor | wall_<nw|ne|corner|end_nw|end_ne|t_nw|t_ne> | door | window | fence |
    stairs | roof | crate | barricade | tower. params: mat (concrete|asphalt|brick|rust|wood), tex, seed, side (nw|ne),
    variant, height_px, steps, count (openings), footprint=[fx,fy] (whole tiles 1..12; floor, wall_*, door, window, fence, stairs, roof; props size
    themselves). shadow=true also writes a separate soft ground-shadow PNG (alpha layer,
    same crop/pivot). """ + LAYOUT_DOC + """."""
    return B.render_pieces(cfg(layout), [{"name": name or slug(kind), "kind": kind, "params": params or {}, "shadow": shadow}])


@mcp.tool()
def build_door(variant: str = "open", side: str = "nw", material: str = "concrete", texture: str | None = None,
               name: str | None = None, shadow: bool = False, footprint: list[int] | None = None, count: int = 1,
               layout: dict | None = None) -> list:
    """Wall segment with a door (count doors evenly spaced along a footprint-long wall). variant: open|closed. side: nw|ne (the two back walls the camera sees into)."""
    c = cfg(layout)
    return B.render_pieces(c, [{"name": name or f"door_{material}_{side}_{variant}", "kind": "door", "shadow": shadow,
                                "params": {"side": side, "variant": variant, "mat": material, "tex": _tex(c, texture), "footprint": footprint, "count": count}}])


@mcp.tool()
def build_window(variant: str = "open", side: str = "nw", material: str = "concrete", texture: str | None = None,
                 name: str | None = None, shadow: bool = False, footprint: list[int] | None = None, count: int = 1,
                 layout: dict | None = None) -> list:
    """Wall segment with a window (count windows evenly spaced along a footprint-long wall). variant: open|closed (glass + bars). side: nw|ne."""
    c = cfg(layout)
    return B.render_pieces(c, [{"name": name or f"window_{material}_{side}_{variant}", "kind": "window", "shadow": shadow,
                                "params": {"side": side, "variant": variant, "mat": material, "tex": _tex(c, texture), "footprint": footprint, "count": count}}])


@mcp.tool()
def build_model(kind: str, params: dict | None = None, name: str | None = None, engine: str = "generic",
                formats: list[str] | None = None, up: str | None = None, forward: str | None = None,
                meters_per_tile: float = 2.0, lods: list[int] | None = None, bake: bool = True,
                texture_size: int = 512, height_m: float | None = None, scale: float = 1.0,
                layout: dict | None = None) -> list:
    """Export a 3D model for ANY engine. kind: any structure piece (wall_corner, door, crate, tower, ...) or a metre-sized
    prop: prop_barrel | prop_crate3d | prop_container | prop_car (variant sedan|van|pickup, wrecked) | prop_tree (variant
    pine|round) | prop_rock | prop_lamp_post | prop_fuel_tank | prop_sandbags. Materials are baked to one albedo texture.
    engine presets set format/axes: three|unity|godot|unreal|blender|generic; override with formats (glb|fbx|obj|usdz),
    up (y|z), forward (the direction the model faces in the exported file: +x|-x|+y|-y|+z|-z).
    lods = triangle budgets, e.g. [3000, 800, 250] -> name_lod0..2. Units: metres. SIZE: height_m fits the model to an exact
    real-world height; scale multiplies; meters_per_tile (default 2) sets how big a 1-tile piece is. """ + LAYOUT_DOC + """."""
    return B.build_models(cfg(layout), [{"name": name or slug(kind), "kind": kind, "params": params or {}}], engine, formats, up,
                          forward, meters_per_tile, bake, texture_size, lods, height_m, scale)


@mcp.tool()
def build_character(name: str, preset: str = "survivor", params: dict | None = None, anims: list[str] | None = None,
                    directions: int = 8, meters_per_tile: float = 2.0, sprites: bool = True, model: bool = False,
                    engine: str = "generic", formats: list[str] | None = None, height_m: float | None = None,
                    layout: dict | None = None) -> dict:
    """Rigged low-poly humanoid. SIZE: height_m = real height of the model/rig (default 1.72); sprite size follows
    meters_per_tile (smaller = bigger sprite) and tile_w. Slow: returns job_id. preset: survivor|soldier|zombie. anims: idle|walk|attack|death.
    sprites=true -> 8-direction sprite sheets per animation (rows = S,SW,W,NW,N,NE,E,SE; columns = frames) through the
    iso rig; model=true -> skinned .glb/.fbx with all animations. params: skin/shirt/trousers/boots as (r,g,b) 0-1, scale,
    tex (name of a generate_texture texture for the clothes) for variation. Deliver with deliver_assets([name])."""
    from isoforge import characters as Ch
    c = cfg(layout)
    p = dict(params or {})
    if p.get("tex"):
        p["tex"] = _tex(c, p["tex"])

    def run():
        out = {}
        if sprites:
            out["sheets"] = [r["file"] for r in Ch.render_character(c, name, preset, p, anims, directions, meters_per_tile, height_m)]
        if model:
            m = Ch.export_character_model(c, name, preset, p, anims, engine, formats, height_m=height_m)
            out["model"] = m["files"]
        return out
    return {"job_id": jobs.submit(c.out, f"build_character:{name}", run), "note": "poll job_status(job_id, wait_seconds=60)"}


@mcp.tool()
def list_kinds() -> dict:
    """Everything that can be built: structure pieces, 3D props, character presets/animations."""
    from isoforge import characters as Ch
    return {"structures": ["floor"] + [f"wall_{k}" for k in WALL_KINDS] + ["door", "window", "fence", "stairs", "roof", "crate", "barricade", "tower"],
            "props3d": [f"prop_{n}" for n in ("barrel", "crate3d", "container", "car", "tree", "rock", "lamp_post", "fuel_tank", "sandbags")],
            "characters": {"presets": Ch.PRESETS, "animations": Ch.ANIMS, "directions": Ch.DIRS},
            "materials": ["concrete", "asphalt", "brick", "rust", "wood"], "engines": sorted(B.ENGINE_PRESETS)}


@mcp.tool()
def generate_texture(subject: str, name: str | None = None, size: int = 512, seed: int | None = None,
                     style: str | None = None, gen_size: int | None = None) -> dict:
    """Seamless tileable AI texture (e.g. 'cracked asphalt', 'dilapidated concrete'). Slow: returns job_id. Then pass
    its name as texture= to build_floor_tile / build_wall_set. Checks tileability and records edge error."""
    from isoforge.textures import generate_texture as _gt
    c = cfg()
    jid = jobs.submit(c.out, f"generate_texture:{subject}", lambda: _gt(c, backend(c), subject, name, size, seed, style, gen_size))
    return {"job_id": jid, "note": "poll job_status(job_id, wait_seconds=60)"}


# ---------------------------------------------------------------- library
@mcp.tool()
def resize_asset(asset: str, max_px: int | None = None, scale: float | None = None, name: str | None = None,
                 mode: str = "smooth") -> list:
    """Make a resized copy of a sprite, tile, character (all its sheets) without regenerating. Give max_px (longest edge /
    frame edge) OR scale (e.g. 0.5). mode: smooth | pixel. Pivots stay bottom-centre. For Blender pieces, re-rendering with
    layout={'tile_w': N} is crisper than resizing."""
    from isoforge.resize import resize_asset as _rs
    return _rs(cfg(), asset, max_px, scale, name, mode)


@mcp.tool()
def list_assets(kind: str | None = None) -> dict:
    """All assets in the manifest (kind: prop|tile|model)."""
    a = Manifest(cfg().out).all()
    return {k: {f: v.get(f) for f in ("kind", "piece", "file", "size", "pivot", "style", "synced")} for k, v in a.items()
            if not kind or v.get("kind") == kind}


@mcp.tool()
def regenerate(asset: str, tweak: str | None = None) -> dict:
    """Redo an asset. Props: new seed (+ optional extra prompt words in `tweak`). Blender pieces: re-render."""
    c = cfg()
    rec = Manifest(c.out).get(asset)
    if not rec:
        raise ValueError(f"unknown asset {asset}")
    if rec["kind"] == "prop":
        subj = rec["subject"] + (f", {tweak}" if tweak else "")
        return generate_asset(subj, asset, 1, rec["seed_base"] + 1, rec.get("max_px"), rec["style"])
    job = {"name": asset, "kind": rec["piece"], "params": {**rec.get("params", {}), **({"seed": hash(tweak) % 1000} if tweak else {})}}
    return B.render_pieces(c, [job]) if rec["kind"] == "tile" else B.build_models(c, [job], rec.get("meters_per_tile", 2.0))


@mcp.tool()
def delete_asset(asset: str, confirm: bool = False) -> dict:
    """Delete an asset's files inside output/ and its manifest entry. Requires confirm=true."""
    if not confirm:
        return {"deleted": False, "reason": "pass confirm=true to delete"}
    c = cfg()
    m = Manifest(c.out)
    rec = m.get(asset)
    if not rec:
        raise ValueError(f"unknown asset {asset}")
    gone = []
    for rel in (rec.get("file"), rec.get("raw")):
        if rel:
            f = safe_join(c.out, rel)
            for p in (f, f.with_suffix(".json")):
                if p.exists():
                    p.unlink()
                    gone.append(str(p.relative_to(c.out)))
    m.delete(asset)
    return {"deleted": True, "files": gone, "note": "copies already delivered to projects are not touched"}


# ---------------------------------------------------------------- delivery (any engine)
@mcp.tool()
def register_target(name: str, type: str, path: str, style: str | None = None, options: dict | None = None) -> dict:
    """Register a project that receives assets. type: godot | web (three.js/Phaser/Vite: public/...) | folder (generic
    PNG+JSON for Unity/Unreal/GameMaker/Defold) | tiled (.tsx isometric tilesets). options e.g. {"models_dir": "public/models"}."""
    return T.register_target(cfg(), name, type, path, style, **(options or {}))


@mcp.tool()
def list_targets() -> dict:
    """Registered delivery targets."""
    return T.list_targets(cfg())


@mcp.tool()
def deliver_assets(assets: list[str], project_path: str | None = None, type: str | None = None,
                   target: str | None = None, options: dict | None = None) -> dict:
    """Copy assets (+ pivot/size metadata) into a project using that engine's conventions. Never overwrites.
    No registration needed: project_path defaults to the current project (server working dir); engine auto-detected
    (project.godot -> godot, package.json -> web: public/generated + public/models, else generic folder).
    Override with type = godot|web|folder|tiled. `target` = optional saved name."""
    return T.deliver(cfg(), assets, target, project_path, type, options)


@mcp.tool()
def export_to_folder(assets: list[str], dest_dir: str, format: str = "generic") -> dict:
    """One-off export to any folder. format: generic (PNG + isoforge_assets.json) or tiled (.tsx)."""
    return export_assets(cfg(), assets, dest_dir, format)


# ---------------------------------------------------------------- Godot specifics
@mcp.tool()
def sync_to_godot(assets: list[str], godot_project: str | None = None, target: str | None = None) -> dict:
    """Copy assets into <project>/assets/generated (never overwrites; version suffix on conflict) and import."""
    c = cfg()
    return G.sync_to_godot(c, _proj(c, godot_project, target), assets)


@mcp.tool()
def build_tileset(set: str, assets: list[str], godot_project: str | None = None, target: str | None = None) -> dict:
    """Pack floor/wall tiles into atlases + an isometric (diamond-down) Godot 4 TileSet .tres. Assets must be synced."""
    c = cfg()
    return G.build_tileset(c, _proj(c, godot_project, target), set, assets)


@mcp.tool()
def place_in_scene(scene: str, asset: str, x: float, y: float, parent: str = ".", node_name: str | None = None,
                   godot_project: str | None = None, target: str | None = None) -> dict:
    """Add/move a Sprite2D in a .tscn so (x,y) is the sprite's bottom-centre (Y-sort friendly). Writes a one-time .bak.
    Reload the scene in the Godot editor afterwards."""
    c = cfg()
    return G.place_in_scene(c, _proj(c, godot_project, target), scene, asset, x, y, parent, node_name)


@mcp.tool()
def build_spriteframes(character: str, godot_project: str | None = None, target: str | None = None) -> dict:
    """Godot SpriteFrames .tres for a character (animations named walk_S, attack_NE, ...). Sync the character first."""
    c = cfg()
    return G.build_spriteframes(c, _proj(c, godot_project, target), character)


@mcp.tool()
def make_scene(asset: str, footprint: bool = False, godot_project: str | None = None, target: str | None = None) -> dict:
    """Reusable res://scenes/generated/<asset>.tscn (Node2D > Sprite2D, optional diamond collision footprint)."""
    c = cfg()
    return G.make_scene(c, _proj(c, godot_project, target), asset, footprint)


TRIPOSR_HELP = ("Pipeline B (image -> 3D) needs TripoSR, which is not installed. It is optional: props, structures and "
                "models work without it. Install: git clone https://github.com/VAST-AI-Research/TripoSR into "
                "isoforge/vendor/TripoSR, then `.venv/bin/pip install torch torchvision` and the repo's requirements.txt "
                "(torchmcubes must be built CPU-only on macOS). See README > Optional: TripoSR.")


@mcp.tool()
def generate_from_mesh(subject: str, directions: int = 1) -> dict:
    """Image -> 3D -> sprite for unique objects (needs optional TripoSR; returns install steps if missing)."""
    raise RuntimeError(TRIPOSR_HELP)


@mcp.tool()
def render_mesh(glb_path: str, directions: int = 1) -> dict:
    """Render a .glb through the shared iso rig into sprites (part of optional Pipeline B)."""
    raise RuntimeError(TRIPOSR_HELP)


if __name__ == "__main__":
    mcp.run()
