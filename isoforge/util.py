import fcntl
import logging
import re
from contextlib import contextmanager
from pathlib import Path


def slug(s: str, maxlen: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:maxlen] or "asset"


def safe_join(base: Path, *parts: str) -> Path:
    """Join and refuse anything resolving outside base (traversal guard)."""
    p = (base / Path(*parts)).resolve()
    if base.resolve() not in (p, *p.parents):
        raise ValueError(f"path escapes {base}: {p}")
    return p


def get_logger(out_dir: Path) -> logging.Logger:
    log = logging.getLogger("isoforge")
    if not log.handlers:
        out_dir.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(out_dir / "isoforge.log")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


@contextmanager
def heavy_job(out_dir: Path):
    """Cross-process queue: image gen and Blender never run together (16 GB)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "jobs.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
