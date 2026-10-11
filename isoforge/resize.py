"""Resize an existing sprite / tile / character without regenerating: same asset, different game scale."""
import json
from datetime import datetime, timezone

from PIL import Image

from .config import Config
from .manifest import Manifest
from .util import safe_join, slug


def _even(v: float) -> int:
    return max(2, round(v / 2) * 2)


def _resample(im: Image.Image, size: tuple, mode: str) -> Image.Image:
    if mode == "pixel":
        a = im.getchannel("A").resize(size, Image.NEAREST).point(lambda v: 255 if v > 127 else 0)
        out = im.convert("RGB").resize(size, Image.NEAREST).convert("RGBA")
        out.putalpha(a)
        return out
    return im.convert("RGBA").resize(size, Image.LANCZOS)


def resize_asset(cfg: Config, asset: str, max_px: int | None = None, scale: float | None = None,
                 name: str | None = None, mode: str = "smooth") -> list[dict]:
    """New asset `name` (default <asset>_<N>px) at max_px (longest edge, frame edge for sheets) or `scale`x.
    mode: smooth (LANCZOS) | pixel (nearest). Pivots stay bottom-centre. Blender pieces look crisper if re-rendered at the
    target tile size via layout={'tile_w': ...} instead."""
    if bool(max_px) == bool(scale):
        raise ValueError("pass exactly one of max_px or scale")
    if mode not in ("smooth", "pixel"):
        raise ValueError("mode must be smooth or pixel")
    man = Manifest(cfg.out)
    tag = f"{max_px}px" if max_px else f"{round(scale * 100)}pct"
    rec = man.get(asset)
    if not rec:
        raise ValueError(f"unknown asset '{asset}'")
    if rec["kind"] == "character":
        new = slug(name or f"{asset}_{tag}")
        kids = [resize_asset(cfg, c, max_px, scale, f"{new}_{man.get(c)['anim']}", mode)[0] for c in rec["children"]]
        man.upsert(new, kind="character", preset=rec.get("preset"), params=rec.get("params"), children=[k["file"].split("/")[-1][:-4] for k in kids],
                   file=None, size=None, pivot=None, resized_from=asset)
        return kids
    if rec["kind"] not in ("prop", "tile", "sheet"):
        raise ValueError(f"cannot resize kind '{rec['kind']}' (models are exported at any size via build_model scale/height_m)")
    src = safe_join(cfg.out, rec["file"])
    im = Image.open(src).convert("RGBA")
    fw, fh = rec["size"]  # frame size for sheets, image size otherwise
    f = scale or max_px / max(fw, fh)
    nw, nh = _even(fw * f), _even(fh * f)
    out_name = slug(name or f"{asset}_{tag}")
    dest = cfg.sub("sprites" if rec["kind"] != "tile" else "tiles") / f"{out_name}.png"
    if rec["kind"] == "sheet":
        cols, rows = im.width // fw, im.height // fh
        sheet = Image.new("RGBA", (nw * cols, nh * rows))
        for r in range(rows):
            for c in range(cols):
                sheet.alpha_composite(_resample(im.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)), (nw, nh), mode), (c * nw, r * nh))
        sheet.save(dest)
        extra = {"sheet": {**rec["sheet"], "frame": [nw, nh]}}
    else:
        _resample(im, (nw, nh), mode).save(dest)
        extra = {}
    meta = {**{k: v for k, v in rec.items() if k not in ("created", "updated", "synced", "shadow")}, **extra,
            "file": str(dest.relative_to(cfg.out)), "size": [nw, nh], "pivot": {"x": nw // 2, "y": nh},
            "resized_from": asset, "scale_factor": round(nw / fw, 4), "resize_mode": mode,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return [man.upsert(out_name, **meta)]
