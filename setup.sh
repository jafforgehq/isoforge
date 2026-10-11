#!/usr/bin/env bash
# IsoForge setup: venv, deps, rembg models, checks, calibration, prints the MCP registration command.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
say() { printf '\n== %s\n' "$*"; }

say "Python venv (3.11+)"
if ! command -v uv >/dev/null; then echo "uv not found. Install: brew install uv  (or use python3.11 -m venv .venv)"; exit 1; fi
[ -d .venv ] || uv venv --python 3.11 .venv
uv pip install -q --python .venv/bin/python -r requirements.txt
echo "deps ok"

say "rembg models (downloaded once, ~1 GB total)"
.venv/bin/python - <<'PY'
from isoforge.config import load
from rembg import new_session
for m in load().rembg_models:
    new_session(m); print("ready:", m)
PY

say "Blender"
BL=$(.venv/bin/python -c "from isoforge.config import load; print(load().blender)")
if [ -x "$BL" ]; then "$BL" --version | head -1; else echo "MISSING: Blender not found at $BL. Install from https://www.blender.org/download/ or set blender_path in isoforge.toml"; fi

say "Draw Things API"
URL=$(.venv/bin/python -c "from isoforge.config import load; print(load().drawthings_url)")
if curl -s -m 4 "$URL/sdapi/v1/options" -o /dev/null; then
  .venv/bin/python -c "from isoforge.config import load; from isoforge.backends.drawthings import DrawThings; print(DrawThings(load().drawthings_url).check()['detail'])"
else
  echo "NOT REACHABLE at $URL. In Draw Things: Settings > Advanced > API Server: ON, protocol HTTP, port 7860, IP 127.0.0.1, TLS off. Load a FLUX.1 [schnell] (or other fast) model."
fi

say "Calibrate camera (tile diamond must equal tile size)"
if [ -x "$BL" ]; then .venv/bin/python -c "from isoforge.config import load; from isoforge import blender as B; print(B.calibrate(load()))"; fi

say "Tests"
.venv/bin/python -m pytest -q tests

say "Register with Claude Code (user scope = every project). Then run /mcp to reconnect or restart Claude Code."
echo "claude mcp add isoforge --scope user -- $ROOT/.venv/bin/python $ROOT/server.py"
