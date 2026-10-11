"""Host-side Blender driver: calibrate, render pieces, crop/pivot/manifest."""
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import postprocess as pp
from .config import ROOT, Config
from .manifest import Manifest
from .util import get_logger, heavy_job

BLENDER_DIR = ROOT / "blender"
ELEV = {"dimetric_2_1": 30.0, "isometric": 35.264}


class BlenderError(RuntimeError):
    pass


def _canvas(cfg: Config) -> list:
    return [cfg.tile_w * 3, cfg.tile_w * 4]


def _cfg_payload(cfg: Config, ppu: float | None = None) -> dict:
    W, H = _canvas(cfg)
    return {"tile_w": cfg.tile_w, "tile_h": cfg.tile_h, "camera_mode": cfg.camera_mode,
            "wall_height_px": cfg.wall_height_px, "canvas": [W, H],
            "origin_y": H - 16 - cfg.tile_h / 2, "ppu": ppu or cfg.tile_w / math.sqrt(2), "meters_per_tile": 2.0}


def run(cfg: Config, script: str, payload: dict, timeout: int = 600) -> list | dict:
    if not Path(cfg.blender).exists():
        raise BlenderError(f"Blender not found at {cfg.blender}. Install from https://www.blender.org/download/ "
                           "or set blender_path in isoforge.toml.")
    payload = {**payload, "blender_dir": str(BLENDER_DIR)}
    with tempfile.TemporaryDirectory() as td:
        pj = Path(td) / "payload.json"
        pj.write_text(json.dumps(payload))
        cmd = [cfg.blender, "-b", "--factory-startup", "--python", str(BLENDER_DIR / script), "--", str(pj)]
        with heavy_job(cfg.out):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise BlenderError(f"Blender {script} timed out after {timeout}s")
        rj = Path(td) / "payload.result.json"
        if p.returncode != 0 or not rj.exists():
            tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-25:])
            raise BlenderError(f"Blender {script} failed (exit {p.returncode}):\n{tail}")
        return json.loads(rj.read_text())


def calibration_path(cfg: Config) -> Path:
    return cfg.out / "calibration.json"


def _key(cfg: Config) -> str:
    return f"{cfg.tile_w}x{cfg.tile_h}_{cfg.camera_mode}"


def _profiles(cfg: Config) -> dict:
    p = calibration_path(cfg)
    d = json.loads(p.read_text()) if p.exists() else {}
    if "profiles" not in d:  # migrate the old single-profile file
        d = {"profiles": {f"{d['tile_w']}x{d['tile_h']}_{d['camera_mode']}": d}} if d.get("ppu") else {"profiles": {}}
    return d


def calibrate(cfg: Config) -> dict:
    """Tune and cache the camera for this tile size + camera mode (several sizes can coexist)."""
    res = run(cfg, "calibrate.py", {"cfg": _cfg_payload(cfg), "out_dir": str(cfg.sub("renders"))})
    rec = {**res, "tile_w": cfg.tile_w, "tile_h": cfg.tile_h, "camera_mode": cfg.camera_mode}
    if res["ok"]:
        d = _profiles(cfg)
        d["profiles"][_key(cfg)] = rec
        calibration_path(cfg).write_text(json.dumps(d, indent=2))
    get_logger(cfg.out).info("calibrate %s", rec)
    return rec


def ensure_calibrated(cfg: Config) -> float:
    c = _profiles(cfg)["profiles"].get(_key(cfg))
    if not c or c.get("method") != "area":      # older profiles used a pixel-bbox method that drifts on big footprints
        c = calibrate(cfg)
        if not c["ok"]:
            raise BlenderError(f"calibration failed: {c}")
    return c["ppu"]


def crop_piece(canvas: Path, pivot: list, diamond: list, footprint: list, cfg: Config) -> tuple[Image.Image, dict, tuple]:
    """Crop to the piece's bbox unioned with its footprint diamond, symmetric about the pivot column, bottom edge = the
    footprint diamond's bottom vertex. So pivot is always (w/2, h) and same-footprint pieces share it exactly."""
    img = Image.open(canvas).convert("RGBA")
    px, py = pivot
    x0, y0, x1, y1 = img.getchannel("A").point(lambda v: 255 if v > 127 else 0).getbbox()
    y0 = min(y0, round(diamond[1]))       # the diamond's top vertex is a thin tip; keep it in the frame
    bottom = max(y1, round(py))
    if footprint[0] == footprint[1]:      # square: symmetric crop, pivot exactly at w/2 (shared by the whole family)
        half = max(round(px - x0), round(x1 - px), round(px - diamond[0]), round(diamond[2] - px))
        left, right = round(px) - half, round(px) + half
    else:                                 # rectangle: bottom vertex is off-centre, so crop tight and record the real pivot
        left, right = min(x0, round(diamond[0])), max(x1, round(diamond[2]))
    if (bottom - y0) % 2:                 # even sizes: pad above (the bottom edge is the pivot) and to the right
        y0 -= 1
    if (right - left) % 2:
        right += 1
    out = img.crop((left, y0, right, bottom))
    return out, {"x": round(px) - left, "y": out.height}, (left, y0, right, bottom)


def shadow_layer(canvas: Path, box: tuple) -> Image.Image:
    """Ground-plane render -> black RGBA whose alpha is shadow strength, same crop as the sprite so layers align."""
    import numpy as np
    L = np.asarray(Image.open(canvas).convert("RGB").crop(box)).astype(np.float32).mean(axis=2)
    ref = np.percentile(L, 98) or 1.0
    a = np.clip((1 - L / ref) * 1.8, 0, 1)
    a[a < 0.04] = 0
    from PIL import ImageFilter
    al = Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.6))  # kills EEVEE shadow speckle
    out = Image.new("RGBA", al.size, (0, 0, 0, 0))
    out.putalpha(al.point(lambda v: 0 if v < 10 else v))
    return out


def render_pieces(cfg: Config, jobs: list[dict], kind_label: str = "tile", dest: str = "tiles") -> list[dict]:
    """jobs: [{name, kind, params, directions}] -> sprites in output/<dest>, manifest updated."""
    log, man = get_logger(cfg.out), Manifest(cfg.out)
    ppu = ensure_calibrated(cfg)
    res = run(cfg, "render_iso.py", {"cfg": _cfg_payload(cfg, ppu), "jobs": jobs,
                                     "out_dir": str(cfg.sub("renders"))})
    jobs_by = {j["name"]: j for j in jobs}
    out = []
    for r in res:
        if "glb" in r:
            continue
        img, pivot, box = crop_piece(Path(r["canvas"]), r["pivot"], r["diamond"], r["footprint"], cfg)
        path = cfg.sub(dest) / f"{r['name']}.png"
        img.save(path)
        base = r["name"].rsplit("_d", 1)[0] if "_d" in r["name"] else r["name"]
        job = jobs_by.get(r["name"]) or jobs_by[base]
        meta = dict(kind=kind_label, piece=job["kind"], params=job.get("params", {}), backend="blender",
                    camera_mode=cfg.camera_mode, tile=[cfg.tile_w, cfg.tile_h], footprint=r["footprint"],
                    file=str(path.relative_to(cfg.out)), size=list(img.size), pivot=pivot,
                    generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if r.get("shadow_canvas"):
            sp = path.with_name(path.stem + "_shadow.png")
            shadow_layer(Path(r["shadow_canvas"]), box).save(sp)
            meta["shadow"] = str(sp.relative_to(cfg.out))
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        out.append(man.upsert(r["name"], **meta))
        log.info("rendered %s %s pivot=%s", r["name"], img.size, pivot)
    return out


ENGINE_PRESETS = {  # file-space conventions: formats, up axis, direction the model faces
    "three": {"formats": ["glb"], "up": "y", "forward": "+z"}, "unity": {"formats": ["fbx", "glb"], "up": "y", "forward": "+z"},
    "godot": {"formats": ["glb"], "up": "y", "forward": "+z"}, "unreal": {"formats": ["fbx"], "up": "z", "forward": "+x"},
    "blender": {"formats": ["glb"], "up": "z", "forward": "-y"}, "generic": {"formats": ["glb"], "up": "y", "forward": "+z"},
}


def build_models(cfg: Config, jobs: list[dict], engine: str = "generic", formats: list | None = None, up: str | None = None,
                 forward: str | None = None, meters_per_tile: float = 2.0, bake: bool = True, texture_size: int = 512,
                 lods: list | None = None, height_m: float | None = None, scale: float = 1.0) -> list[dict]:
    """Kitbash / 3D-prop pieces -> game-ready models (baked textures, LODs, axis/scale/format per engine)."""
    if engine not in ENGINE_PRESETS:
        raise BlenderError(f"engine must be one of {sorted(ENGINE_PRESETS)}")
    pre = ENGINE_PRESETS[engine]
    ex = {"formats": formats or pre["formats"], "up": up or pre["up"], "forward": forward or pre["forward"],
          "meters_per_tile": meters_per_tile, "bake": bake, "texture_size": texture_size, "lods": lods,
          "height_m": height_m, "scale": scale}
    man, out, by = Manifest(cfg.out), [], {}
    for r in run(cfg, "export_models.py", {"cfg": _cfg_payload(cfg, ensure_calibrated(cfg)),
                                           "jobs": [{**j, "export": ex} for j in jobs], "out_dir": str(cfg.sub("meshes"))}, timeout=900):
        by.setdefault(r["name"], []).append(r)
    for name, rs in by.items():
        j = next(j for j in jobs if j["name"] == name)
        rel = lambda p: str(Path(p).relative_to(cfg.out))  # noqa: E731
        first = rs[0]
        out.append(man.upsert(name, kind="model", piece=j["kind"], params=j.get("params", {}), backend="blender",
                              file=rel(next(iter(first["files"].values()))), files={f: rel(p) for f, p in first["files"].items()},
                              all_files=[rel(p) for r in rs for p in r["all_files"]],
                              lods=[{"lod": r["lod"], "tris": r["tris"], "files": {f: rel(p) for f, p in r["files"].items()}} for r in rs],
                              tris=first["tris"], animations=first.get("animations"), export={**ex, "engine": engine}, size=None, pivot=None,
                              generated=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        get_logger(cfg.out).info("model %s lods=%s formats=%s", name, [r["tris"] for r in rs], list(ex["formats"]))
    return out
