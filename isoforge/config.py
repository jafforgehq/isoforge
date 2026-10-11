"""Config loader: isoforge.toml + ISOFORGE_* env overrides."""
import dataclasses
import json
import math
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLENDER_DEFAULT = "/Applications/Blender.app/Contents/MacOS/Blender"


@dataclass
class Config:
    godot_project: str = ""
    output_dir: str = "output"
    blender_path: str = ""
    default_backend: str = "drawthings"
    drawthings_url: str = "http://127.0.0.1:7860"
    comfyui_url: str = "http://127.0.0.1:8188"
    active_style: str = "grim_iso_painted"
    tile_w: int = 128
    tile_h: int = 64
    camera_mode: str = "dimetric_2_1"
    wall_height_px: int = 96
    sprite_max_px: int = 96
    base_seed: int = 1000
    rembg_models: list = field(default_factory=lambda: ["isnet-general-use", "birefnet-general"])
    quality: dict = field(default_factory=dict)

    @property
    def out(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else ROOT / p

    def sub(self, name: str) -> Path:
        d = self.out / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def blender(self) -> str:
        return self.blender_path or BLENDER_DEFAULT

    def q(self, key: str):
        return {**QUALITY_DEFAULTS, **self.quality}[key]


STATE_KEYS = {"active_style", "tile_w", "tile_h", "camera_mode", "wall_height_px", "sprite_max_px"}
QUALITY_DEFAULTS = dict(alpha_min=0.08, alpha_max=0.85, border_margin_px=2,
                        dominant_blob_min=0.9, halo_max=0.02, max_retries=3,
                        tile_seam_ratio_max=1.6)


def load(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("ISOFORGE_CONFIG", ROOT / "isoforge.toml"))
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    cfg = Config(**{k: v for k, v in data.items() if k in {f.name for f in fields(Config)}})
    for f in fields(Config):
        env = os.environ.get("ISOFORGE_" + f.name.upper())
        if env is not None and f.name not in ("rembg_models", "quality"):
            setattr(cfg, f.name, type(getattr(cfg, f.name))(env))
    st = cfg.out / "state.json"
    if st.exists():
        for k, v in json.loads(st.read_text()).items():
            if k in STATE_KEYS:
                setattr(cfg, k, v)
    return cfg


LAYOUT_KEYS = {"tile_w", "tile_h", "camera_mode", "wall_height_px", "sprite_max_px"}
ISO_RATIO = math.sin(math.radians(35.264))   # true isometric diamond height / width


def with_layout(cfg: Config, layout: dict | None) -> Config:
    """Copy of cfg with per-call size overrides: tile_w, tile_h, camera_mode, wall_height_px, sprite_max_px.
    Nothing is persisted. Sizes that were not given follow tile_w (tile_h from the camera, wall/sprite px proportionally)."""
    if not layout:
        return cfg
    bad = set(layout) - LAYOUT_KEYS
    if bad:
        raise ValueError(f"unknown layout keys {sorted(bad)}; allowed: {sorted(LAYOUT_KEYS)}")
    c = dataclasses.replace(cfg, **{k: v for k, v in layout.items() if k in ("tile_w", "tile_h", "camera_mode", "wall_height_px", "sprite_max_px")})
    if c.camera_mode not in ("dimetric_2_1", "isometric"):
        raise ValueError("camera_mode must be dimetric_2_1 or isometric")
    if not 16 <= c.tile_w <= 1024 or c.tile_w % 2:
        raise ValueError("tile_w must be an even number between 16 and 1024")
    s = c.tile_w / cfg.tile_w
    if "wall_height_px" not in layout:
        c.wall_height_px = max(4, round(cfg.wall_height_px * s))
    if "sprite_max_px" not in layout:
        c.sprite_max_px = max(8, round(cfg.sprite_max_px * s))
    want = c.tile_w // 2 if c.camera_mode == "dimetric_2_1" else round(c.tile_w * ISO_RATIO)
    if "tile_h" not in layout:
        c.tile_h = want
    elif abs(c.tile_h - want) > 1:
        raise ValueError(f"tile_h={c.tile_h} does not match {c.camera_mode} for tile_w={c.tile_w} (expected {want}); omit tile_h to derive it")
    return c


def save_state(cfg: Config, **kw) -> dict:
    """Persist locked choices (style, tile size, camera) in output/state.json; overrides isoforge.toml."""
    st = cfg.out / "state.json"
    cur = json.loads(st.read_text()) if st.exists() else {}
    cur.update({k: v for k, v in kw.items() if k in STATE_KEYS and v is not None})
    cfg.out.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(cur, indent=2))
    return cur


def load_style(name: str) -> dict:
    p = ROOT / "styles" / f"{name}.toml"
    if not p.exists() or "/" in name or ".." in name:
        raise FileNotFoundError(f"style '{name}' not found in styles/")
    return tomllib.loads(p.read_text())
