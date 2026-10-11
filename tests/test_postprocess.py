import numpy as np
from PIL import Image, ImageDraw
from isoforge import postprocess as pp
from isoforge.manifest import Manifest


def blob(box=(200, 200, 700, 700), size=1024, soft=False):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse(box, fill=(120, 80, 40, 255))
    if soft:
        from PIL import ImageFilter
        im.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(6)))
    return im


def test_gate_pass():
    ok, m, why = pp.quality_gate(pp.defringe(blob()))
    assert ok, why


def test_gate_rejects_border_and_coverage():
    assert not pp.quality_gate(blob((0, 0, 1000, 1000)))[0]
    assert not pp.quality_gate(blob((500, 500, 520, 520)))[0]


def test_gate_rejects_two_blobs():
    im = blob((100, 100, 350, 350))
    ImageDraw.Draw(im).ellipse((500, 500, 900, 900), fill=(1, 1, 1, 255))
    ok, m, why = pp.quality_gate(im)
    assert not ok and m["blob_share"] < 0.9


def test_defringe_reduces_halo():
    soft = blob(soft=True)
    assert pp.alpha_metrics(pp.defringe(soft))["halo"] < pp.alpha_metrics(soft)["halo"]


def test_finalize_even_and_pivot():
    out, _ = pp.finalize_sprite(blob(), 101)
    assert max(out.size) <= 102 and out.width % 2 == 0 and out.height % 2 == 0
    assert pp.pivot_of(out) == {"x": out.width // 2, "y": out.height}


def test_pixel_mode_palette():
    out, _ = pp.finalize_sprite(blob(), 64, "pixel", 8)
    assert len({tuple(p) for p in np.asarray(out)[..., :3].reshape(-1, 3)}) <= 9


def test_tileability():
    x = np.linspace(0, 255, 256, dtype=np.uint8)
    ramp = Image.fromarray(np.tile(x, (256, 1))[..., None].repeat(3, 2))     # hard wrap seam
    assert pp.seam_ratio(ramp) > 5 and not pp.is_tileable(ramp)
    fixed = pp.make_seamless(ramp)
    assert pp.seam_ratio(fixed) < pp.seam_ratio(ramp) / 4 and pp.is_tileable(fixed)


def test_manifest(tmp_path):
    m = Manifest(tmp_path)
    m.upsert("a", seed=1)
    m.upsert("a", prompt="x")
    assert m.get("a")["seed"] == 1 and m.get("a")["prompt"] == "x"
    assert m.delete("a") and m.get("a") is None
