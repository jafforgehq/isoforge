"""Godot 4 integration: sync, tileset, scene editing. Formats verified against Godot 4.7.2 output:
 .tscn header is `[gd_scene format=3]` (load_steps only bumped if a file still has it);
 TileSet .tres uses tile_shape=1 (isometric), tile_layout=5 (diamond down)."""
import hashlib
import json
import math
import random
import re
import shutil
import string
import subprocess
from pathlib import Path

from PIL import Image

from .config import Config
from .manifest import Manifest
from .util import get_logger, safe_join

GODOT_BIN = "/Applications/Godot.app/Contents/MacOS/Godot"
EDITOR_WARNING = "Reload the scene in the Godot editor (Scene > Reload Saved Scene) or the edits may be overwritten."


class GodotError(RuntimeError):
    pass


def _project(godot_project: str) -> Path:
    p = Path(godot_project).expanduser().resolve()
    if not (p / "project.godot").exists():
        raise GodotError(f"not a Godot project (no project.godot): {p}")
    return p


def _gen_dir(proj: Path) -> Path:
    d = proj / "assets" / "generated"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _unique_dest(dest: Path, src: Path) -> tuple[Path, str]:
    """Never overwrite: identical -> reuse, different -> _v2, _v3..."""
    if not dest.exists():
        return dest, "copied"
    if _sha(dest) == _sha(src):
        return dest, "unchanged"
    n = 2
    while True:
        cand = dest.with_name(f"{dest.stem}_v{n}{dest.suffix}")
        if not cand.exists():
            return cand, "versioned"
        if _sha(cand) == _sha(src):
            return cand, "unchanged"
        n += 1


def res_path(proj: Path, p: Path) -> str:
    return "res://" + p.resolve().relative_to(proj).as_posix()


def godot_import(proj: Path, timeout: int = 180):
    if not Path(GODOT_BIN).exists():
        return "skipped (Godot binary not found)"
    try:
        subprocess.run([GODOT_BIN, "--headless", "--path", str(proj), "--import"],
                       capture_output=True, timeout=timeout)
        return "imported"
    except subprocess.TimeoutExpired:
        return "import timed out"


def sync_to_godot(cfg: Config, godot_project: str, assets: list[str], import_assets: bool = True) -> dict:
    proj, man, log = _project(godot_project), Manifest(cfg.out), get_logger(cfg.out)
    gen = _gen_dir(proj)
    out = {}
    for name in man.expand(assets):
        rec = man.get(name)
        if not rec:
            raise GodotError(f"unknown asset '{name}' (not in manifest)")
        src = safe_join(cfg.out, rec["file"])
        sub = {"tile": "tiles", "model": "models"}.get(rec["kind"], "sprites")
        files = [src] + [safe_join(cfg.out, f) for f in rec.get("all_files", [])] if rec["kind"] == "model" else [src]
        dest, status = _unique_dest(safe_join(gen, sub, src.name), src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if status != "unchanged":
            shutil.copy2(src, dest)
        if rec["kind"] == "model":  # companions (textures, other formats, LODs) next to the main file
            for f in files[1:]:
                if not (dest.parent / f.name).exists():
                    shutil.copy2(f, dest.parent / f.name)
        r = res_path(proj, dest)
        out[name] = {"res": r, "status": status}
        synced = dict(rec.get("synced", {}))
        synced[str(proj)] = r
        man.upsert(name, synced=synced)
        log.info("sync %s -> %s (%s)", name, r, status)
    if import_assets:
        out["_import"] = godot_import(proj)
    out["_warning"] = EDITOR_WARNING
    return out


# ------------------------------------------------------------------ tileset
def _pack(imgs: list[tuple[str, Image.Image, dict]], cell: tuple[int, int]) -> tuple[Image.Image, dict]:
    """Paste every sprite with its pivot on the bottom-centre of a uniform cell."""
    cols = math.ceil(math.sqrt(len(imgs)))
    rows = math.ceil(len(imgs) / cols)
    atlas = Image.new("RGBA", (cols * cell[0], rows * cell[1]))
    coords = {}
    for i, (name, im, pv) in enumerate(imgs):
        c, r = i % cols, i // cols
        atlas.alpha_composite(im, (c * cell[0] + cell[0] // 2 - pv["x"], r * cell[1] + cell[1] - pv["y"]))
        coords[name] = (c, r)
    return atlas, coords


def build_tileset(cfg: Config, godot_project: str, set_name: str, assets: list[str]) -> dict:
    """Pack tile assets into atlases (floors: 1 source, walls: 1 source) + isometric TileSet .tres."""
    proj, man = _project(godot_project), Manifest(cfg.out)
    tw, th = cfg.tile_w, cfg.tile_h
    groups = {"floor": [], "wall": []}
    for n in assets:
        rec = man.get(n)
        if not rec or rec.get("kind") != "tile":
            raise GodotError(f"'{n}' is not a tile asset")
        if rec.get("footprint", [1, 1]) != [1, 1]:
            raise GodotError(f"'{n}' covers {rec['footprint']} tiles; a TileMap cell holds one tile. Place multi-tile pieces as "
                             "Sprite2D (place_in_scene / make_scene) instead.")
        im = Image.open(safe_join(cfg.out, rec["file"])).convert("RGBA")
        groups["floor" if rec["piece"] == "floor" else "wall"].append((n, im, rec["pivot"]))
    td = _gen_dir(proj) / "tilesets"
    td.mkdir(parents=True, exist_ok=True)
    ext, subs, srcs, mapping = [], [], [], {}
    for sid, kind in enumerate([k for k in groups if groups[k]]):
        items = groups[kind]
        cw = 2 * max(max(p["x"] for _, _, p in items), tw // 2)
        ch = max(max(im.height for _, im, _ in items), th)
        ch += ch % 2
        atlas, coords = _pack(items, (cw, ch))
        tmp = td / f"_{set_name}_{kind}.png"
        atlas.save(tmp)
        dest, st = _unique_dest(td / f"{set_name}_{kind}.png", tmp)
        if st != "unchanged":
            shutil.move(tmp, dest)
        else:
            tmp.unlink()
        rid = f"{sid + 1}_{kind}"
        ext.append(f'[ext_resource type="Texture2D" path="{res_path(proj, dest)}" id="{rid}"]')
        body = [f'[sub_resource type="TileSetAtlasSource" id="Atlas_{kind}"]', f'texture = ExtResource("{rid}")',
                f"texture_region_size = Vector2i({cw}, {ch})"]
        for n, (c, r) in coords.items():
            # texture_origin puts the sprite's pivot on the cell's diamond bottom vertex
            oy = (ch - th) // 2
            body.append(f"{c}:{r}/0 = 0")
            if oy:
                body.append(f"{c}:{r}/0/texture_origin = Vector2i(0, {oy})")
            mapping[n] = {"source": sid, "atlas_coords": [c, r]}
        subs.append("\n".join(body))
        srcs.append(f'sources/{sid} = SubResource("Atlas_{kind}")')
    tres = ('[gd_resource type="TileSet" format=3]\n\n' + "\n".join(ext) + "\n\n" + "\n\n".join(subs) +
            f"\n\n[resource]\ntile_shape = 1\ntile_layout = 5\ntile_size = Vector2i({tw}, {th})\n" + "\n".join(srcs) + "\n")
    tmp = td / f"_{set_name}.tres"
    tmp.write_text(tres)
    dest, st = _unique_dest(td / f"{set_name}.tres", tmp)
    if st != "unchanged":
        shutil.move(tmp, dest)
    else:
        tmp.unlink()
    (td / f"{set_name}.tiles.json").write_text(json.dumps(mapping, indent=2))
    godot_import(proj)
    return {"tileset": res_path(proj, dest), "tiles": mapping, "warning": EDITOR_WARNING}


# ------------------------------------------------------------- scene editing
def _sprite_info(cfg: Config, godot_project: str, asset: str) -> tuple[str, int, int, dict]:
    proj, rec = _project(godot_project), Manifest(cfg.out).get(asset)
    if not rec:
        raise GodotError(f"unknown asset '{asset}'")
    r = rec.get("synced", {}).get(str(proj))
    if not r:
        raise GodotError(f"asset '{asset}' not synced to {proj}; run sync_to_godot first")
    return r, rec["size"][0], rec["size"][1], rec["pivot"]


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def place_in_scene(cfg: Config, godot_project: str, scene: str, asset: str, x: float, y: float,
                   parent: str = ".", node_name: str | None = None) -> dict:
    """Insert (or update) a Sprite2D whose position is the sprite's bottom-centre pivot (Y-sort friendly)."""
    proj = _project(godot_project)
    sp = Path(scene) if Path(scene).is_absolute() else proj / scene.replace("res://", "")
    sp = safe_join(proj, str(sp.relative_to(proj)))
    if sp.suffix != ".tscn" or not sp.exists():
        raise GodotError(f"scene must be an existing .tscn inside the project: {sp}")
    rpath, w, h, pv = _sprite_info(cfg, godot_project, asset)
    text = sp.read_text()
    bak = sp.with_suffix(".tscn.bak")
    if not bak.exists():
        bak.write_text(text)
    name = node_name or re.sub(r"[^A-Za-z0-9_]", "", asset.title().replace("_", "")) or "Sprite"
    offset = f"Vector2({_fmt(w / 2 - pv['x'])}, {_fmt(h / 2 - pv['y'])})"
    pos = f"Vector2({_fmt(x)}, {_fmt(y)})"

    nodes = re.findall(r'^\[node name="([^"]+)"(?: type="[^"]*")?(?: parent="([^"]*)")?', text, re.M)
    paths = set()
    for i, (n, p) in enumerate(nodes):
        paths.add("." if i == 0 else (n if p == "." else f"{p}/{n}"))
    if parent not in paths:
        raise GodotError(f"parent '{parent}' not found in scene (have: {sorted(paths)})")

    hdr = rf'^\[node name="{re.escape(name)}" type="Sprite2D" parent="{re.escape(parent)}"[^\]]*\]\n'
    m = re.search(hdr, text, re.M)
    if m:  # idempotent: move the existing node
        end = re.search(r"^\[", text[m.end():], re.M)
        stop = m.end() + (end.start() if end else len(text) - m.end())
        block = text[m.end():stop]
        block = re.sub(r"^position = .*$", f"position = {pos}", block, flags=re.M)
        sp.write_text(text[:m.end()] + block + text[stop:])
        return {"status": "updated", "node": name, "warning": EDITOR_WARNING}

    ids = set(re.findall(r'\bid="([^"]+)"', text))
    rid = next(i for i in (f"{len(ids) + 1}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=5))}"
                           for _ in range(50)) if i not in ids)
    ext = f'[ext_resource type="Texture2D" path="{rpath}" id="{rid}"]\n'
    ms = list(re.finditer(r'^\[ext_resource [^\n]*\n', text, re.M))
    if ms:
        text = text[:ms[-1].end()] + ext + text[ms[-1].end():]
    else:
        hm = re.match(r"\[gd_scene[^\n]*\n", text)
        text = text[:hm.end()] + "\n" + ext + text[hm.end():]
    text = re.sub(r"(^\[gd_scene[^\]]*load_steps=)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", text, flags=re.M)

    if name in {n for n, p in nodes if (p or ".") == parent}:
        raise GodotError(f"node name '{name}' already used under '{parent}' by another type")
    node = (f'[node name="{name}" type="Sprite2D" parent="{parent}"]\nposition = {pos}\n'
            f'texture = ExtResource("{rid}")\noffset = {offset}\n\n')
    tail = re.search(r"^\[(connection|editable)", text, re.M)
    if tail:
        text = text[:tail.start()] + node + text[tail.start():]
    else:
        text = text.rstrip("\n") + "\n\n" + node.rstrip("\n") + "\n"
    sp.write_text(text)
    return {"status": "placed", "node": name, "parent": parent, "position": [x, y], "warning": EDITOR_WARNING}


def make_scene(cfg: Config, godot_project: str, asset: str, footprint: bool = False) -> dict:
    """res://scenes/generated/<asset>.tscn : Node2D > Sprite2D (+ optional diamond collision)."""
    proj = _project(godot_project)
    rpath, w, h, pv = _sprite_info(cfg, godot_project, asset)
    name = re.sub(r"[^A-Za-z0-9_]", "", asset.title().replace("_", "")) or "Asset"
    off = f"Vector2({_fmt(w / 2 - pv['x'])}, {_fmt(h / 2 - pv['y'])})"
    t = (f'[gd_scene format=3]\n\n[ext_resource type="Texture2D" path="{rpath}" id="1_tex"]\n\n'
         f'[node name="{name}" type="Node2D"]\ny_sort_enabled = true\n\n'
         f'[node name="Sprite2D" type="Sprite2D" parent="."]\ntexture = ExtResource("1_tex")\noffset = {off}\n')
    if footprint:
        tw, th = cfg.tile_w, cfg.tile_h  # diamond footprint, origin = bottom vertex
        poly = f"Vector2(0, 0), Vector2({-tw // 2}, {-th // 2}), Vector2(0, {-th}), Vector2({tw // 2}, {-th // 2})"
        t += (f'\n[node name="Body" type="StaticBody2D" parent="."]\n\n'
              f'[node name="Footprint" type="CollisionPolygon2D" parent="Body"]\npolygon = PackedVector2Array({poly})\n')
    d = safe_join(proj, "scenes", "generated")
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{asset}.tscn"
    if dest.exists() and dest.read_text() != t:
        n = 2
        while (d / f"{asset}_v{n}.tscn").exists():
            n += 1
        dest = d / f"{asset}_v{n}.tscn"
    dest.write_text(t)
    return {"scene": res_path(proj, dest), "warning": EDITOR_WARNING}


def build_spriteframes(cfg: Config, godot_project: str, character: str) -> dict:
    """SpriteFrames .tres for a character: one animation per <anim>_<DIR> (e.g. walk_SW), AtlasTexture per frame.
    Sheets must be synced first (sync_to_godot(character))."""
    proj, man = _project(godot_project), Manifest(cfg.out)
    rec = man.get(character)
    if not rec or rec.get("kind") != "character":
        raise GodotError(f"'{character}' is not a character asset")
    ext, subs, anims, n = [], [], [], 0
    for i, child in enumerate(rec["children"]):
        c = man.get(child)
        r = c.get("synced", {}).get(str(proj))
        if not r:
            raise GodotError(f"'{child}' not synced to {proj}; run sync_to_godot first")
        ext.append(f'[ext_resource type="Texture2D" path="{r}" id="{i + 1}_sheet"]')
        fw, fh = c["sheet"]["frame"]
        for row, d in enumerate(c["sheet"]["directions"]):
            frames = []
            for col in range(c["sheet"]["frames"]):
                sid = f"AtlasTexture_{n}"
                n += 1
                subs.append(f'[sub_resource type="AtlasTexture" id="{sid}"]\natlas = ExtResource("{i + 1}_sheet")\n'
                            f"region = Rect2({col * fw}, {row * fh}, {fw}, {fh})")
                frames.append(f'{{\n"duration": 1.0,\n"texture": SubResource("{sid}")\n}}')
            anims.append(f'{{\n"frames": [{", ".join(frames)}],\n"loop": {"true" if c["sheet"]["loop"] else "false"},\n'
                         f'"name": &"{c["anim"]}_{d}",\n"speed": {float(c["sheet"]["fps"])}\n}}')
    text = ('[gd_resource type="SpriteFrames" format=3]\n\n' + "\n".join(ext) + "\n\n" + "\n\n".join(subs) +
            "\n\n[resource]\nanimations = [" + ", ".join(anims) + "]\n")
    d = _gen_dir(proj) / "spriteframes"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"_{character}.tres"
    tmp.write_text(text)
    dest, st = _unique_dest(d / f"{character}.tres", tmp)
    if st != "unchanged":
        shutil.move(tmp, dest)
    else:
        tmp.unlink()
    return {"spriteframes": res_path(proj, dest), "animations": [a.split('&"')[1].split('"')[0] for a in anims],
            "origin_hint": "Sprite2D/AnimatedSprite2D: set offset so the sprite's bottom-centre is the node position "
                           f"(frame {fw}x{fh}, pivot {fw // 2},{fh})", "warning": EDITOR_WARNING}
