"""3D + character acceptance through the MCP server: model export (formats/LODs), 8-direction character sheets,
animated skinned model, delivery to a fresh Godot project, SpriteFrames loaded by Godot itself."""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "smoke"))
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from acceptance import aslist, data  # noqa: E402,F401  (reuse helpers)

PROJ = ROOT / "sandbox" / "acceptance_3d"
GODOT = "/Applications/Godot.app/Contents/MacOS/Godot"


async def main():
    if PROJ.exists():
        shutil.rmtree(PROJ)
    PROJ.mkdir(parents=True)
    (PROJ / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="Accept3D"\nconfig/features=PackedStringArray("4.7")\n')
    params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"), args=[str(ROOT / "server.py")], cwd=str(PROJ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            call = lambda n, a=None: s.call_tool(n, a or {})  # noqa: E731
            kinds = data(await call("list_kinds"))
            print("kinds:", len(kinds["structures"]), "structures,", len(kinds["props3d"]), "props3d,", kinds["characters"]["presets"])
            m = aslist(data(await call("build_model", {"kind": "prop_car", "params": {"variant": "pickup"}, "name": "acc_pickup",
                                                       "engine": "unity", "formats": ["glb", "fbx"], "lods": [2500, 700, 250]})))[0]
            print("model:", m["files"], [(l["lod"], l["tris"]) for l in m["lods"]])
            job = data(await call("build_character", {"name": "acc_walker", "preset": "zombie", "anims": ["idle", "walk"],
                                                      "directions": 8, "model": True, "engine": "unity"}))
            while True:
                st = data(await call("job_status", {"job_id": job["job_id"], "wait_seconds": 90}))
                print("character job:", st["state"])
                if st["state"] != "running":
                    break
            assert st["state"] == "done", st
            print("sheets:", st["result"]["sheets"], "model:", st["result"]["model"])
            d1 = data(await call("deliver_assets", {"assets": ["acc_pickup", "acc_walker", "acc_walker_3d"]}))  # cwd = Godot project
            print("delivered:", d1.get("assets") or list(d1)[:6])
            sf = data(await call("build_spriteframes", {"character": "acc_walker"}))
            print("spriteframes:", sf["spriteframes"], len(sf["animations"]), "animations")
    (PROJ / "verify.gd").write_text('''extends SceneTree
func _init():
	var sf: SpriteFrames = load("res://assets/generated/spriteframes/acc_walker.tres")
	var n := sf.get_animation_names()
	print("VERIFY anims=", n.size(), " walk_SE frames=", sf.get_frame_count("walk_SE"), " idle_N loop=", sf.get_animation_loop("idle_N"), " speed=", sf.get_animation_speed("walk_S"))
	print("VERIFY frame_size=", sf.get_frame_texture("walk_S", 0).get_size())
	var scn = load("res://assets/generated/models/acc_pickup_lod0.glb")
	print("VERIFY model=", scn != null)
	quit()
''')
    subprocess.run([GODOT, "--headless", "--path", str(PROJ), "--import"], capture_output=True, timeout=300)
    out = subprocess.run([GODOT, "--headless", "--path", str(PROJ), "--script", "verify.gd"], capture_output=True, text=True, timeout=120)
    ver = [l for l in out.stdout.splitlines() if l.startswith("VERIFY")]
    print("\n".join(ver))
    assert "anims=16" in ver[0] and "walk_SE frames=8" in ver[0] and "model=true" in ver[2], out.stdout + out.stderr
    print("ACCEPTANCE 3D OK")


asyncio.run(main())
