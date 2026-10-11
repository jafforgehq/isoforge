"""Everything size-related: per-call layouts, several tile sizes/cameras side by side, resize, real-world heights."""
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from isoforge import blender as B, characters as Ch
from isoforge.config import Config, with_layout
from isoforge.manifest import Manifest
from isoforge.resize import resize_asset

needs_blender = pytest.mark.skipif(not Path(Config().blender).exists(), reason="Blender missing")


def test_layout_rules():
    base = Config()
    c = with_layout(base, {"tile_w": 64})
    assert (c.tile_w, c.tile_h, c.wall_height_px, c.sprite_max_px) == (64, 32, 48, 48)      # all follow tile_w
    iso = with_layout(base, {"camera_mode": "isometric"})
    assert (iso.tile_w, iso.tile_h) == (128, 74)                                              # 2:1 would be wrong for iso
    assert with_layout(base, {"tile_w": 256, "wall_height_px": 100}).wall_height_px == 100   # explicit wins
    assert (base.tile_w, base.tile_h) == (128, 64)                                            # caller's cfg untouched
    for bad in ({"tile_w": 63}, {"tile_w": 4096}, {"tile_h": 50}, {"camera_mode": "top"}, {"colour": 1}):
        with pytest.raises(ValueError):
            with_layout(base, bad)


def glb_height(path: Path) -> float:
    d = path.read_bytes()
    n = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + n])
    ys = [(a["min"][1], a["max"][1]) for a in j["accessors"] if a.get("type") == "VEC3" and "min" in a]
    return max(m[1] for m in ys) - min(m[0] for m in ys)


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return Config(output_dir=str(tmp_path_factory.mktemp("sizes")))


@needs_blender
def test_tile_sizes_and_cameras_coexist(cfg):
    got = {}
    for key, lay in {"s": {"tile_w": 64}, "m": {}, "l": {"tile_w": 256}, "iso": {"camera_mode": "isometric"}}.items():
        c = with_layout(cfg, lay)
        f, w = B.render_pieces(c, [{"name": f"f_{key}", "kind": "floor", "params": {}},
                                   {"name": f"w_{key}", "kind": "wall_nw", "params": {"mat": "concrete"}}])
        got[key] = (f["size"], f["pivot"], w["size"], c)
    assert got["s"][0] == [64, 32] and got["m"][0] == [128, 64] and got["l"][0] == [256, 128]
    assert got["iso"][0] == [128, 74]                                       # true isometric diamond
    for k in got:
        assert got[k][1] == {"x": got[k][0][0] // 2, "y": got[k][0][1]}   # pivot = bottom vertex at every size
    ratio = got["l"][2][1] / got["s"][2][1]
    assert 3.2 < ratio < 4.5                                                # wall height scales with tile size
    assert len(B._profiles(cfg)["profiles"]) == 4                           # four profiles cached side by side


@needs_blender
def test_character_and_model_sizes(cfg):
    big = with_layout(cfg, {"tile_w": 256})
    small = Ch.render_character(cfg, "h_small", "survivor", anims=["idle"], directions=1)[0]["size"]
    large = Ch.render_character(big, "h_large", "survivor", anims=["idle"], directions=1)[0]["size"]
    assert large[1] > small[1] * 1.6                                        # same character, bigger game scale
    tall = Ch.render_character(cfg, "h_tall", "survivor", anims=["idle"], directions=1, height_m=3.4)[0]
    assert tall["size"][1] > small[1]
    for h in (1.5, 3.0):
        m = B.build_models(cfg, [{"name": f"bar{h}", "kind": "prop_barrel"}], height_m=h)[0]
        assert abs(glb_height(cfg.out / m["file"]) - h) < 0.03 * h
    c = Ch.export_character_model(cfg, "hh", "soldier", anims=["idle"], height_m=1.0)
    assert 0.95 < glb_height(cfg.out / c["file"]) < 1.08
    s = B.build_models(cfg, [{"name": "bar_s", "kind": "prop_barrel"}], scale=2.0)[0]
    d = B.build_models(cfg, [{"name": "bar_d", "kind": "prop_barrel"}])[0]
    assert abs(glb_height(cfg.out / s["file"]) / glb_height(cfg.out / d["file"]) - 2) < 0.05


def test_resize_asset(tmp_path):
    cfg = Config(output_dir=str(tmp_path))
    man = Manifest(cfg.out)
    Image.new("RGBA", (100, 160), (200, 50, 50, 255)).save(cfg.sub("sprites") / "barrel.png")
    man.upsert("barrel", kind="prop", file="sprites/barrel.png", size=[100, 160], pivot={"x": 50, "y": 160})
    Image.new("RGBA", (64 * 3, 80 * 2), (1, 2, 3, 255)).save(cfg.sub("sprites") / "hero_walk.png")
    man.upsert("hero_walk", kind="sheet", anim="walk", file="sprites/hero_walk.png", size=[64, 80], pivot={"x": 32, "y": 80},
               sheet={"frame": [64, 80], "frames": 3, "fps": 10, "loop": True, "directions": ["S", "SW"]})
    man.upsert("hero", kind="character", children=["hero_walk"], file=None, size=None, pivot=None)
    r = resize_asset(cfg, "barrel", max_px=48)[0]
    assert r["size"] == [30, 48] and r["pivot"] == {"x": 15, "y": 48} and r["resized_from"] == "barrel"
    assert Image.open(cfg.out / r["file"]).size == (30, 48)
    k = resize_asset(cfg, "hero", scale=0.5)
    s = Manifest(cfg.out).get("hero_50pct")["children"]
    sheet = Manifest(cfg.out).get(s[0])
    assert sheet["sheet"]["frame"] == [32, 40] and Image.open(cfg.out / sheet["file"]).size == (96, 80)
    assert resize_asset(cfg, "barrel", max_px=16, mode="pixel", name="tiny")[0]["size"] == [10, 16]
    for bad in ({}, {"max_px": 10, "scale": .5}, {"scale": .5, "mode": "x"}):
        with pytest.raises(ValueError):
            resize_asset(cfg, "barrel", **bad)
