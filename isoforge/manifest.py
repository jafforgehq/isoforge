"""manifest.json = source of truth. Atomic, file-locked writes."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Manifest:
    def __init__(self, out_dir: Path):
        self.path = Path(out_dir) / "manifest.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self):
        with open(self.path.with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            yield

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {"assets": {}}

    def _write(self, data: dict):
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def all(self) -> dict:
        return self._read()["assets"]

    def get(self, name: str) -> dict | None:
        return self.all().get(name)

    def expand(self, names: list[str]) -> list[str]:
        """Replace character entries with their sprite-sheet children (so delivery copies real files)."""
        out, a = [], self.all()
        for n in names:
            r = a.get(n)
            out += r["children"] if r and r.get("kind") == "character" else [n]
        return out

    def upsert(self, name: str, **fields) -> dict:
        with self._lock():
            data = self._read()
            rec = data["assets"].setdefault(name, {"created": _now()})
            rec.update(fields, updated=_now())
            self._write(data)
            return rec

    def delete(self, name: str) -> bool:
        with self._lock():
            data = self._read()
            gone = data["assets"].pop(name, None) is not None
            self._write(data)
            return gone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
