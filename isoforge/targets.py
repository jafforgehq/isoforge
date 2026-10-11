"""Delivery targets: where assets go. One asset store, many consumers (Godot, Unity, three.js, Tiled...).
type: godot | folder | tiled | web.  Stored in output/targets.json; explicit user registration = consent to write there."""
import json
from pathlib import Path

from .config import Config
from .export import export_assets
from .godot import sync_to_godot
from .util import safe_join

TYPES = {"godot", "folder", "tiled", "web"}
WEB_DEFAULTS = {"sprites_dir": "public/generated/sprites", "tiles_dir": "public/generated/tiles",
                "models_dir": "public/models", "meta_dir": "public/generated"}


def _file(cfg: Config) -> Path:
    return cfg.out / "targets.json"


def list_targets(cfg: Config) -> dict:
    return json.loads(_file(cfg).read_text()) if _file(cfg).exists() else {}


def register_target(cfg: Config, name: str, type: str, path: str, style: str | None = None, **opts) -> dict:
    if type not in TYPES:
        raise ValueError(f"type must be one of {sorted(TYPES)}")
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"target path is not a directory: {p}")
    if type == "godot" and not (p / "project.godot").exists():
        raise ValueError(f"no project.godot in {p}")
    t = list_targets(cfg)
    t[name] = {"type": type, "path": str(p), "style": style, **opts}
    cfg.out.mkdir(parents=True, exist_ok=True)
    _file(cfg).write_text(json.dumps(t, indent=2))
    return t[name]


def resolve(cfg: Config, target: str) -> dict:
    t = list_targets(cfg).get(target)
    if not t:
        raise ValueError(f"unknown target '{target}'. Registered: {sorted(list_targets(cfg))}")
    return t


def detect(path: str) -> dict:
    """Guess the engine from a project folder: Godot (project.godot), web/three.js (package.json), else generic folder."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"project path is not a directory: {p}")
    if (p / "project.godot").exists():
        return {"type": "godot", "path": str(p)}
    if (p / "package.json").exists():
        return {"type": "web", "path": str(p)}
    return {"type": "folder", "path": str(p)}


def deliver(cfg: Config, assets: list[str], target: str | None = None, path: str | None = None,
            type: str | None = None, options: dict | None = None) -> dict:
    """Deliver to a registered target, or ad hoc: path (default = caller's working dir) + optional type."""
    if target:
        t = resolve(cfg, target)
    else:
        t = detect(path or __import__("os").getcwd())
        if type:
            if type not in TYPES:
                raise ValueError(f"type must be one of {sorted(TYPES)}")
            t["type"] = type
        t.update(options or {})
    ty, path = t["type"], t["path"]
    if ty == "godot":
        return sync_to_godot(cfg, path, assets)
    if ty == "web":
        sub = {**WEB_DEFAULTS, **{k: t[k] for k in WEB_DEFAULTS if k in t}}
        return export_assets(cfg, assets, path, "generic", subdirs={"sprites": sub["sprites_dir"], "tiles": sub["tiles_dir"],
                             "models": sub["models_dir"]}, meta_dir=sub["meta_dir"])
    sub = t.get("dir", "isoforge")
    return export_assets(cfg, assets, str(safe_join(Path(path), sub)), "tiled" if ty == "tiled" else "generic")
