"""Background jobs so slow generations (minutes) never hit an MCP client timeout. State in output/jobs/<id>.json."""
import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

_threads: dict = {}


def _p(out: Path, jid: str) -> Path:
    d = out / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{jid}.json"


def submit(out: Path, label: str, fn) -> str:
    jid = uuid.uuid4().hex[:8]
    rec = {"id": jid, "label": label, "state": "running", "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _p(out, jid).write_text(json.dumps(rec))

    def run():
        try:
            rec.update(state="done", result=fn())
        except Exception as e:
            rec.update(state="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        rec["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _p(out, jid).write_text(json.dumps(rec, default=str))

    t = threading.Thread(target=run, daemon=True)
    _threads[jid] = t
    t.start()
    return jid


def status(out: Path, jid: str, wait: float = 0) -> dict:
    t = _threads.get(jid)
    if t and wait:
        t.join(timeout=wait)
    p = _p(out, jid)
    if not p.exists():
        return {"id": jid, "state": "unknown"}
    rec = json.loads(p.read_text())
    if rec["state"] == "running" and jid not in _threads:
        rec["state"] = "lost (server restarted while running; re-run the request, it is idempotent)"
    return rec
