import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

from isoforge import godot as G
from isoforge.config import Config
from isoforge.manifest import Manifest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path):
    proj = tmp_path / "game"
    (proj / "scenes").mkdir(parents=True)
    (proj / "project.godot").write_text("config_version=5\n")
    shutil.copy(FIX / "main_godot47.tscn", proj / "scenes/main.tscn")
    shutil.copy(FIX / "main_legacy.tscn", proj / "scenes/legacy.tscn")
    cfg = Config(output_dir=str(tmp_path / "out"))
    man = Manifest(cfg.out)
    for name, kind, piece, size, color in [("barrel", "prop", "prop", (40, 60), (150, 60, 20, 255)),
                                           ("floor_a", "tile", "floor", (128, 64), (60, 60, 60, 255)),
                                           ("wall_a", "tile", "wall_nw", (130, 156), (160, 150, 130, 255))]:
        d = cfg.sub("sprites" if kind == "prop" else "tiles")
        Image.new("RGBA", size, color).save(d / f"{name}.png")
        man.upsert(name, kind=kind, piece=piece, file=f"{d.name}/{name}.png", size=list(size),
                   pivot={"x": size[0] // 2, "y": size[1]})
    return cfg, proj


def test_sync_never_overwrites(env):
    cfg, proj = env
    r = G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)
    assert r["barrel"]["status"] == "copied"
    assert G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)["barrel"]["status"] == "unchanged"
    Image.new("RGBA", (40, 60), (1, 2, 3, 255)).save(cfg.out / "sprites/barrel.png")  # changed source
    r = G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)
    assert r["barrel"]["status"] == "versioned" and r["barrel"]["res"].endswith("barrel_v2.png")
    assert (proj / "assets/generated/sprites/barrel.png").read_bytes() != (proj / "assets/generated/sprites/barrel_v2.png").read_bytes()


def test_sync_rejects_unknown_and_bad_project(env, tmp_path):
    cfg, proj = env
    with pytest.raises(G.GodotError):
        G.sync_to_godot(cfg, str(proj), ["nope"], import_assets=False)
    with pytest.raises(G.GodotError):
        G.sync_to_godot(cfg, str(tmp_path), ["barrel"], import_assets=False)


@pytest.mark.parametrize("scene", ["main_godot47", "legacy"])
def test_place_in_scene(env, scene):
    cfg, proj = env
    name = "main" if scene == "main_godot47" else "legacy"
    G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)
    sc = f"scenes/{name}.tscn"
    r = G.place_in_scene(cfg, str(proj), sc, "barrel", 400, 300, "Props", "Barrel")
    txt = (proj / sc).read_text()
    assert r["status"] == "placed" and (proj / (sc + ".bak")).exists()
    assert 'name="Barrel" type="Sprite2D" parent="Props"' in txt
    assert "position = Vector2(400, 300)" in txt and "offset = Vector2(0, -30)" in txt  # bottom-centre
    rid = re.search(r'\[ext_resource type="Texture2D" path="res://assets/generated/sprites/barrel.png" id="([^"]+)"', txt).group(1)
    assert f'texture = ExtResource("{rid}")' in txt
    if scene == "legacy":
        assert "load_steps=3" in txt and txt.index('name="Barrel"') < txt.index("[connection")
        assert 'id="1_abc"' in txt and rid != "1_abc"
    else:
        assert "load_steps" not in txt
    # idempotent move + .bak keeps original
    assert G.place_in_scene(cfg, str(proj), sc, "barrel", 10, 20, "Props", "Barrel")["status"] == "updated"
    assert txt.count('name="Barrel"') == 1 and "position = Vector2(10, 20)" in (proj / sc).read_text()
    assert "Barrel" not in (proj / (sc + ".bak")).read_text()


def test_place_errors(env):
    cfg, proj = env
    with pytest.raises(G.GodotError, match="not synced"):
        G.place_in_scene(cfg, str(proj), "scenes/main.tscn", "barrel", 0, 0)
    G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)
    with pytest.raises(G.GodotError, match="parent"):
        G.place_in_scene(cfg, str(proj), "scenes/main.tscn", "barrel", 0, 0, "Nope")
    with pytest.raises(Exception):
        G.place_in_scene(cfg, str(proj), "../../etc/passwd.tscn", "barrel", 0, 0)


def test_tileset(env):
    cfg, proj = env
    r = G.build_tileset(cfg, str(proj), "t1", ["floor_a", "wall_a"])
    tres = (proj / r["tileset"].replace("res://", "")).read_text()
    assert "tile_shape = 1" in tres and "tile_layout = 5" in tres and "tile_size = Vector2i(128, 64)" in tres
    assert tres.count("TileSetAtlasSource") >= 2 and "sources/1" in tres
    wall_atlas = Image.open(proj / "assets/generated/tilesets/t1_wall.png")
    assert wall_atlas.size[0] % 2 == 0 and wall_atlas.size[1] % 2 == 0
    # origin: pivot sits on cell bottom-centre -> origin_y = (cell_h - tile_h)/2
    ch = wall_atlas.size[1]
    assert f"texture_origin = Vector2i(0, {(ch - 64) // 2})" in tres


def test_make_scene(env):
    cfg, proj = env
    G.sync_to_godot(cfg, str(proj), ["barrel"], import_assets=False)
    r = G.make_scene(cfg, str(proj), "barrel", footprint=True)
    t = (proj / r["scene"].replace("res://", "")).read_text()
    assert "CollisionPolygon2D" in t and "Sprite2D" in t


def test_export_generic_and_tiled(env, tmp_path):
    from isoforge.export import export_assets
    cfg, _ = env
    r = export_assets(cfg, ["barrel", "floor_a", "wall_a"], str(tmp_path / "unity_proj"), "tiled")
    d = tmp_path / "unity_proj"
    j = __import__("json").loads((d / "isoforge_assets.json").read_text())
    b = j["assets"]["barrel"]
    assert b["pivot_norm_bl"] == [0.5, 0.0] and b["pivot_norm_tl"] == [0.5, 1.0]
    assert len(r["tilesets"]) == 2 and 'orientation="isometric"' in (d / r["tilesets"][0]).read_text()
    wall = (d / r["tilesets"][1]).read_text()
    assert 'tilewidth="130"' in wall and '<tileoffset x="-1"' in wall
    with pytest.raises(ValueError):
        export_assets(cfg, ["nope"], str(tmp_path / "x"))


def test_adhoc_delivery_autodetect(env, tmp_path, monkeypatch):
    from isoforge import targets as T
    cfg, godot_proj = env
    web = tmp_path / "webgame"
    web.mkdir()
    (web / "package.json").write_text("{}")
    plain = tmp_path / "other"
    plain.mkdir()
    assert T.detect(str(godot_proj))["type"] == "godot"
    assert T.detect(str(web))["type"] == "web" and T.detect(str(plain))["type"] == "folder"
    monkeypatch.chdir(web)                                  # caller's cwd, nothing registered
    r = T.deliver(cfg, ["barrel", "floor_a"], None)
    assert (web / "public/generated/sprites/barrel.png").exists() and (web / "public/generated/tiles/floor_a.png").exists()
    assert r["metadata"] == "public/generated/isoforge_assets.json"
    r = T.deliver(cfg, ["barrel"], path=str(plain), type="tiled")
    assert (plain / "isoforge/isoforge_assets.json").exists()
    with pytest.raises(ValueError):
        T.deliver(cfg, ["barrel"], path=str(tmp_path / "missing"))
    assert T.list_targets(cfg) == {}                          # nothing got registered


def test_spriteframes_and_character_delivery(env, tmp_path):
    cfg, proj = env
    man = Manifest(cfg.out)
    d = cfg.sub("sprites")
    for a, n, loop in (("walk", 3, True), ("death", 2, False)):
        Image.new("RGBA", (64 * n, 80 * 4), (9, 9, 9, 255)).save(d / f"hero_{a}.png")
        man.upsert(f"hero_{a}", kind="sheet", piece="character", character="hero", anim=a, file=f"sprites/hero_{a}.png",
                   size=[64, 80], pivot={"x": 32, "y": 80},
                   sheet={"frame": [64, 80], "frames": n, "fps": 10, "loop": loop, "directions": ["S", "SW", "W", "NW"]})
    man.upsert("hero", kind="character", children=["hero_walk", "hero_death"], file=None, size=None, pivot=None)
    r = G.sync_to_godot(cfg, str(proj), ["hero"], import_assets=False)       # character expands to its sheets
    assert r["hero_walk"]["status"] == "copied" and "hero" not in r
    sf = G.build_spriteframes(cfg, str(proj), "hero")
    txt = (proj / sf["spriteframes"].replace("res://", "")).read_text()
    assert "walk_SW" in sf["animations"] and len(sf["animations"]) == 8
    assert 'region = Rect2(128, 160, 64, 80)' in txt and '"loop": false' in txt and '&"death_NW"' in txt
    from isoforge.export import export_assets
    e = export_assets(cfg, ["hero"], str(tmp_path / "out"))
    assert len(e["assets"]) == 2 and "sheet" in __import__("json").loads((tmp_path / "out" / e["metadata"]).read_text())["assets"]["hero_walk"]
