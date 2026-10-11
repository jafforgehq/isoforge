"""Alpha cleanup, quality gates, trim/resize/pivot, tileability."""
import numpy as np
from PIL import Image
from scipy import ndimage

from .config import QUALITY_DEFAULTS


def defringe(img: Image.Image, lo: int = 16, hi: int = 239) -> Image.Image:
    """Stretch alpha contrast and replace edge RGB with nearest solid colour (kills halos)."""
    a = np.asarray(img.convert("RGBA")).copy()
    alpha = a[..., 3].astype(np.float32)
    solid = alpha >= hi
    if solid.any():
        idx = ndimage.distance_transform_edt(~solid, return_distances=False, return_indices=True)
        a[..., :3] = a[idx[0], idx[1], :3]
    a[..., 3] = np.clip((alpha - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


def alpha_metrics(img: Image.Image, q: dict | None = None) -> dict:
    q = {**QUALITY_DEFAULTS, **(q or {})}
    al = np.asarray(img.convert("RGBA"))[..., 3]
    solid = al > 127
    n = int(solid.sum())
    h, w = al.shape
    m = {"coverage": n / al.size}
    lab, k = ndimage.label(solid)
    m["blob_share"] = float(np.bincount(lab.ravel())[1:].max() / n) if n else 0.0
    b = q["border_margin_px"]
    m["touches_border"] = bool(solid[:b].any() or solid[-b:].any() or solid[:, :b].any() or solid[:, -b:].any())
    m["halo"] = float(((al > 10) & (al < 245)).sum() / n) if n else 1.0
    m["iso_check"] = "skipped"  # no cheap reliable heuristic; flagged for manual review
    return m


def quality_gate(img: Image.Image, q: dict | None = None) -> tuple[bool, dict, list]:
    q = {**QUALITY_DEFAULTS, **(q or {})}
    m = alpha_metrics(img, q)
    why = []
    if not q["alpha_min"] <= m["coverage"] <= q["alpha_max"]:
        why.append(f"coverage {m['coverage']:.2f} outside {q['alpha_min']}-{q['alpha_max']}")
    if m["blob_share"] < q["dominant_blob_min"]:
        why.append(f"no dominant blob ({m['blob_share']:.2f})")
    if m["touches_border"]:
        why.append("subject touches border")
    if m["halo"] > q["halo_max"]:
        why.append(f"halo {m['halo']:.3f}")
    return not why, m, why


def alpha_score(img: Image.Image) -> float:
    """Higher = cleaner matte (compare rembg models): fewer semi-transparent px, one blob."""
    m = alpha_metrics(img)
    return m["blob_share"] - m["halo"] - (1.0 if m["touches_border"] else 0.0)


def finalize_sprite(img: Image.Image, max_px: int, mode: str = "smooth", palette: int = 32) -> tuple[Image.Image, dict]:
    img = img.convert("RGBA")
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        raise ValueError("empty alpha, nothing to trim")
    img = img.crop(bbox)
    s = max_px / max(img.size)
    if s < 1:
        size = (max(1, round(img.width * s)), max(1, round(img.height * s)))
        if mode == "pixel":
            img = img.resize(size, Image.NEAREST)
            a = img.getchannel("A").point(lambda v: 255 if v > 127 else 0)
            img = img.convert("RGB").quantize(palette, dither=Image.NONE).convert("RGBA")
            img.putalpha(a)
        else:
            img = img.resize(size, Image.LANCZOS)
    return pad_even(img), {}


def pad_even(img: Image.Image) -> Image.Image:
    w, h = img.size
    if w % 2 or h % 2:
        out = Image.new("RGBA", (w + w % 2, h + h % 2))
        out.paste(img, (0, 0))  # extra px on right/bottom: keeps bottom-centre ±1px
        return out
    return img


def pivot_of(img: Image.Image) -> dict:
    """Pivot = bottom-centre of the sprite, in px from top-left."""
    return {"x": img.width // 2, "y": img.height}


def tile_edge_diff(img: Image.Image) -> float:
    """Mean abs diff (0-255) between opposite edges (wrap seam)."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    return float((np.abs(a[0] - a[-1]).mean() + np.abs(a[:, 0] - a[:, -1]).mean()) / 2)


def seam_ratio(img: Image.Image) -> float:
    """Wrap-seam difference / typical neighbour-pixel difference inside the image. ~1 = invisible seam."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    inner = (np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()) / 2
    return float(tile_edge_diff(img) / max(inner, 1.0))


def is_tileable(img: Image.Image, q: dict | None = None) -> bool:
    return bool(seam_ratio(img) <= {**QUALITY_DEFAULTS, **(q or {})}["tile_seam_ratio_max"])


def make_seamless(img: Image.Image, blend: float = 0.15) -> Image.Image:
    """Offset-blend fix: cross-fade image with its half-shifted copy toward the edges."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    shifted = np.roll(a, (h // 2, w // 2), axis=(0, 1))
    ys = np.minimum(np.arange(h), np.arange(h)[::-1]) / (h * blend)
    xs = np.minimum(np.arange(w), np.arange(w)[::-1]) / (w * blend)
    wt = np.clip(np.minimum(ys[:, None], xs[None, :]), 0, 1)[..., None]  # 1 centre, 0 edge
    return Image.fromarray((a * wt + shifted * (1 - wt)).astype(np.uint8))


def grade(img: Image.Image, saturation: float = 0.55, warmth: float = 0.04) -> Image.Image:
    """Mute + slightly warm an image so every texture sits in the same desaturated palette."""
    from PIL import ImageEnhance
    out = ImageEnhance.Color(img.convert("RGB")).enhance(saturation)
    a = np.asarray(out).astype(np.float32)
    a[..., 0] *= 1 + warmth
    a[..., 2] *= 1 - warmth
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
