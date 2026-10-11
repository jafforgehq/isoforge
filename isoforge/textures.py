"""Seamless AI textures: generate -> make tileable -> validate -> store (output/textures)."""
import json

from PIL import Image
from datetime import datetime, timezone

from . import postprocess as pp
from .backends.base import Backend
from .config import Config, load_style
from .manifest import Manifest
from .util import get_logger, heavy_job, slug

DEFAULT_PREFIX = ("A seamless tileable top-down material texture, flat orthographic view filling the whole frame, "
                  "even diffuse lighting, no shadows, no perspective, no border, no objects, muted desaturated "
                  "worn grimy hand-painted look. The material: ")


def generate_texture(cfg: Config, backend: Backend, subject: str, name: str | None = None, size: int = 512,
                     seed: int | None = None, style: str | None = None, gen_size: int | None = None) -> dict:
    log, man = get_logger(cfg.out), Manifest(cfg.out)
    st = load_style(style or cfg.active_style)
    if gen_size:
        st = {**st, "size": gen_size}
    n = slug(name or subject)
    s = cfg.base_seed if seed is None else seed
    prompt = st.get("texture_prefix", DEFAULT_PREFIX) + subject
    with heavy_job(cfg.out):
        raw = backend.txt2img(prompt, st.get("negative", ""), s, st)
    raw.save(cfg.sub("raw") / f"tex_{n}_{s}.png")
    before = pp.seam_ratio(raw)
    fixed = raw if pp.is_tileable(raw, cfg.quality) else pp.make_seamless(raw)  # only fix real seams
    img = pp.grade(fixed.resize((size, size), Image.LANCZOS), st.get("texture_saturation", 0.55))
    after = pp.seam_ratio(img)
    ok = pp.is_tileable(img, cfg.quality)
    out = cfg.sub("textures") / f"{n}.png"
    img.save(out)
    meta = dict(kind="texture", prompt=prompt, subject=subject, seed=s, style=style or cfg.active_style, backend=backend.name,
                file=str(out.relative_to(cfg.out)), size=[size, size], tileable=ok,
                seam_ratio_before=round(before, 2), seam_ratio_after=round(after, 2),
                generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    log.info("texture %s tileable=%s %.1f->%.1f", n, ok, before, after)
    return man.upsert(n, **meta)
