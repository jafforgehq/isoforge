import json
import pytest
from PIL import Image
from isoforge import blender as B
from isoforge.config import Config

cfg0 = Config()
pytestmark = pytest.mark.skipif(not __import__("pathlib").Path(cfg0.blender).exists(), reason="Blender missing")


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    c = Config(output_dir=str(tmp_path_factory.mktemp("out")))
    return c


def test_calibration_and_set(cfg):
    cal = B.calibrate(cfg)
    assert cal["ok"] and abs(cal["measured"][0] - 128) < 0.5 and abs(cal["measured"][1] - 64) < 0.5
    res = B.render_pieces(cfg, [
        {"name": "f", "kind": "floor", "params": {"mat": "asphalt"}},
        {"name": "w", "kind": "wall_nw", "params": {"mat": "concrete"}}])
    f, w = [Image.open(cfg.out / r["file"]) for r in res]
    assert f.size == (128, 64)                       # floor == diamond exactly
    assert res[0]["pivot"] == {"x": 64, "y": 64}     # bottom vertex of diamond
    assert res[1]["pivot"]["y"] == w.height and res[1]["pivot"]["x"] == w.width // 2
    assert w.height > 64 + 80                        # wall has real height (~96px)


def test_recalibrate_on_tile_change(cfg):
    from isoforge.config import with_layout
    small = with_layout(cfg, {"tile_w": 64})
    assert B.ensure_calibrated(small) > 0
    prof = json.loads(B.calibration_path(cfg).read_text())["profiles"]
    assert prof["64x32_dimetric_2_1"]["tile_w"] == 64 and "128x64_dimetric_2_1" in prof   # sizes coexist


def test_model_decimation_and_texture(cfg):
    from PIL import Image
    tex = cfg.out / "t.png"
    Image.new("RGB", (64, 64), (90, 90, 90)).save(tex)
    job = {"kind": "wall_corner", "params": {"mat": "concrete", "tex": str(tex)}}
    full = B.build_models(cfg, [{**job, "name": "m_full"}])[0]
    low = B.build_models(cfg, [{**job, "name": "m_low"}], lods=[600])[0]
    assert low["tris"] <= 600 < full["tris"]
    assert (cfg.out / low["file"]).read_bytes()[:4] == b"glTF"
    cfg.tile_w, cfg.tile_h = 128, 64
    r = B.render_pieces(cfg, [{"name": "ft", "kind": "floor", "params": {"mat": "asphalt", "tex": str(tex)}}])[0]
    assert r["size"] == [128, 64]                     # texture must not change the diamond


def test_structures_and_shadow(cfg):
    cfg.tile_w, cfg.tile_h = 128, 64
    kinds = [("door", {"side": "nw", "variant": "open"}), ("door", {"side": "ne", "variant": "closed"}),
             ("window", {"side": "ne", "variant": "closed"}), ("fence", {"side": "nw"}), ("stairs", {}),
             ("roof", {}), ("crate", {}), ("barricade", {}), ("tower", {})]
    jobs = [{"name": f"s{i}", "kind": k, "params": p, "shadow": k == "crate"} for i, (k, p) in enumerate(kinds)]
    res = B.render_pieces(cfg, jobs)
    assert len(res) == len(kinds)
    for r in res:                                        # shared footprint convention for every piece
        assert r["pivot"]["y"] == r["size"][1] and r["pivot"]["x"] == r["size"][0] // 2 and r["size"][0] >= 128
    crate = next(r for r in res if r["piece"] == "crate")
    sh = Image.open(cfg.out / crate["shadow"])
    assert sh.size == tuple(crate["size"]) and sh.getchannel("A").getextrema()[1] > 60   # aligned, has real shadow
    with pytest.raises(B.BlenderError, match="unknown piece kind"):
        B.render_pieces(cfg, [{"name": "bad", "kind": "teapot"}])


def test_model_export_formats_lods_orientation(cfg):
    import struct
    r = B.build_models(cfg, [{"name": "bar", "kind": "prop_barrel", "params": {}}], engine="unity",
                       formats=["glb", "fbx", "obj"], lods=[1200, 300])[0]
    assert [l["lod"] for l in r["lods"]] == [0, 1] and r["lods"][1]["tris"] <= 300 < r["lods"][0]["tris"]
    for f in ("glb", "fbx", "obj"):
        assert (cfg.out / r["files"][f]).stat().st_size > 1000
    g = (cfg.out / r["files"]["glb"]).read_bytes()
    assert g[:4] == b"glTF" and struct.unpack("<I", g[8:12])[0] == len(g)
    assert any(f.endswith("_albedo.png") for f in r["all_files"])            # baked texture shipped
    with pytest.raises(B.BlenderError, match="engine must be"):
        B.build_models(cfg, [{"name": "x", "kind": "prop_barrel"}], engine="bogus")
    with pytest.raises(B.BlenderError):                                       # forward cannot be the up axis
        B.build_models(cfg, [{"name": "x", "kind": "prop_barrel"}], up="y", forward="+y")


def test_character_sheets_and_model(cfg):
    from isoforge import characters as Ch
    sheets = Ch.render_character(cfg, "hero", "survivor", anims=["walk", "death"], directions=4)
    fw, fh = sheets[0]["size"]
    assert {s["anim"] for s in sheets} == {"walk", "death"} and fw >= 128
    sh = Image.open(cfg.out / sheets[0]["file"])
    assert sh.size == (fw * sheets[0]["sheet"]["frames"], fh * 4)             # rows = directions, cols = frames
    assert sheets[0]["pivot"] == {"x": fw // 2, "y": fh}
    from isoforge.manifest import Manifest
    assert Manifest(cfg.out).expand(["hero"]) == ["hero_walk", "hero_death"]
    m = Ch.export_character_model(cfg, "hero", "survivor", anims=["walk", "death"])
    assert sorted(m["animations"]) == ["Rig_death", "Rig_walk"] and m["tris"] > 100
    with pytest.raises(ValueError):
        Ch.render_character(cfg, "bad", "dragon")
