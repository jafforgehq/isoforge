"""Multi-tile footprints: size, pivot (bottom vertex of the footprint diamond), validation, Godot guard."""
from pathlib import Path

import pytest
from PIL import Image

from isoforge import blender as B, godot as G
from isoforge.config import Config
from isoforge.manifest import Manifest

needs_blender = pytest.mark.skipif(not Path(Config().blender).exists(), reason="Blender missing")


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return Config(output_dir=str(tmp_path_factory.mktemp("fp")))


@needs_blender
def test_footprint_sizes_and_pivots(cfg):
    J = lambda n, k, p: {"name": n, "kind": k, "params": p}  # noqa: E731
    r = {x["file"].split("/")[-1][:-4]: x for x in B.render_pieces(cfg, [
        J("f11", "floor", {}), J("f22", "floor", {"footprint": [2, 2]}), J("f31", "floor", {"footprint": [3, 1]}),
        J("wall3", "wall_ne", {"footprint": [3, 1]}), J("door2", "door", {"side": "ne", "variant": "closed", "footprint": [3, 1], "count": 2}),
        J("win3", "window", {"side": "nw", "footprint": [1, 3], "count": 3}), J("stairs", "stairs", {"footprint": [2, 1]}),
        J("container", "prop_container", {}), J("barrel", "prop_barrel", {})])}
    assert r["f11"]["size"] == [128, 64] and r["f11"]["pivot"] == {"x": 64, "y": 64}            # unchanged for 1x1
    assert r["f22"]["size"] == [256, 128] and r["f22"]["pivot"] == {"x": 128, "y": 128}        # bottom vertex, centred
    assert r["f31"]["size"] == [256, 128] and r["f31"]["pivot"]["y"] == 128                     # rectangle: same diamond size...
    assert abs(r["f31"]["pivot"]["x"] - 192) <= 1 and r["f31"]["footprint"] == [3, 1]          # ...but off-centre bottom vertex
    assert r["wall3"]["size"][0] >= 256 and r["door2"]["size"][0] >= 256 and r["win3"]["size"][0] >= 256
    assert r["container"]["footprint"] == [2, 3] and r["barrel"]["footprint"] == [1, 1]        # props size themselves
    im = Image.open(cfg.out / r["f22"]["file"])
    assert im.getchannel("A").getbbox() == (0, 0, 256, 128)                                     # diamond fills the sprite
    for k in ("f22", "wall3", "stairs", "container"):                                           # pivot always at the bottom edge
        assert r[k]["pivot"]["y"] == r[k]["size"][1]


@needs_blender
def test_footprint_validation(cfg):
    for params, kind in (({"footprint": [0, 1]}, "floor"), ({"footprint": [13, 1]}, "floor"), ({"footprint": [2]}, "floor"),
                         ({"footprint": [2, 2]}, "prop_barrel"), ({"footprint": [2, 2]}, "crate"), ({"footprint": [1.5, 1]}, "floor")):
        with pytest.raises(B.BlenderError, match="footprint|single-tile|size themselves"):
            B.render_pieces(cfg, [{"name": "bad", "kind": kind, "params": params}])


def test_tileset_rejects_multitile(tmp_path):
    cfg = Config(output_dir=str(tmp_path / "out"))
    proj = tmp_path / "game"
    proj.mkdir()
    (proj / "project.godot").write_text("config_version=5\n")
    Image.new("RGBA", (256, 128)).save(cfg.sub("tiles") / "big.png")
    Manifest(cfg.out).upsert("big", kind="tile", piece="floor", file="tiles/big.png", size=[256, 128], pivot={"x": 128, "y": 128}, footprint=[2, 2])
    with pytest.raises(G.GodotError, match="one tile"):
        G.build_tileset(cfg, str(proj), "t", ["big"])
