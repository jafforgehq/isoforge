"""Pipeline A: AI prop sprites. prompt -> gen -> rembg(best of N) -> gate/retry -> finalize."""
import json
from datetime import datetime, timezone

from PIL import Image

from . import postprocess as pp
from .backends.base import Backend
from .config import Config, load_style
from .manifest import Manifest
from .util import get_logger, heavy_job, slug

_sessions: dict = {}


def remove_bg(img: Image.Image, models: list[str]) -> tuple[Image.Image, str]:
    """Run each rembg model, keep the matte with the best alpha score."""
    from rembg import new_session, remove
    best = None
    for m in models:
        if m not in _sessions:
            _sessions[m] = new_session(m)
        out = pp.defringe(remove(img, session=_sessions[m]))
        score = pp.alpha_score(out)
        if best is None or score > best[0]:
            best = (score, out, m)
    return best[1], best[2]


def generate_asset(cfg: Config, backend: Backend, subject: str, name: str | None = None,
                   count: int = 1, seed: int | None = None, max_px: int | None = None,
                   style: str | None = None, gen_size: int | None = None) -> list[dict]:
    log, man = get_logger(cfg.out), Manifest(cfg.out)
    style_name = style or cfg.active_style
    st = load_style(style_name)
    if gen_size:
        st = {**st, "size": gen_size}   # 512/768 = faster draft, 1024 = default quality
    base = slug(name or subject)
    seed0 = cfg.base_seed if seed is None else seed
    max_px = max_px or cfg.sprite_max_px
    results = []
    for i in range(count):
        aname = base if count == 1 else f"{base}_{i + 1:02d}"
        prompt = st["prompt_prefix"] + subject
        prev = man.get(aname)
        if prev and prev.get("prompt") == prompt and prev.get("seed_base") == seed0 + i \
                and prev.get("style") == style_name and prev.get("max_px") == max_px and (cfg.out / prev["file"]).exists():
            results.append(prev)  # idempotent: identical request already done
            continue
        rec = None
        for attempt in range(cfg.q("max_retries") + 1):
            s = seed0 + i + attempt * 10007
            raw_path = cfg.sub("raw") / f"{aname}_{s}.png"
            if raw_path.exists() and prev and prev.get("prompt") == prompt and prev.get("style") == style_name:
                raw = Image.open(raw_path).convert("RGB")  # same request already generated: skip the GPU
            else:
                with heavy_job(cfg.out):
                    raw = backend.txt2img(prompt, st.get("negative", ""), s, st)
                raw.save(raw_path)
            with heavy_job(cfg.out):
                cut, model = remove_bg(raw, cfg.rembg_models)
            ok, metrics, why = pp.quality_gate(cut, cfg.quality)
            log.info("%s seed=%s attempt=%s ok=%s %s", aname, s, attempt, ok, why)
            rec = dict(attempt=attempt, seed=s, raw=raw_path, cut=cut, model=model, metrics=metrics, why=why)
            if ok:
                break
        final, _ = pp.finalize_sprite(rec["cut"], max_px, st.get("post_mode", "smooth"), st.get("palette_size", 32))
        out = cfg.sub("sprites") / f"{aname}.png"
        final.save(out)
        meta = dict(kind="prop", prompt=prompt, subject=subject, seed=rec["seed"], seed_base=seed0 + i,
                    style=style_name, max_px=max_px, backend=backend.name, rembg_model=rec["model"],
                    file=str(out.relative_to(cfg.out)), raw=str(rec["raw"].relative_to(cfg.out)),
                    size=list(final.size), pivot=pp.pivot_of(final), metrics=rec["metrics"],
                    gate_passed=not rec["why"], gate_failures=rec["why"], attempts=rec["attempt"] + 1,
                    generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        results.append(man.upsert(aname, **meta))
    (cfg.sub("raw") / ".gdignore").touch()
    return results
