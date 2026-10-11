"""Acceptance: via the MCP server, build a dilapidated concrete wall set + cracked asphalt floor, generate a rusty oil
barrel, sync to a brand-new Godot project, build the iso TileSet, place the barrel at 400,300 in scenes/main.tscn.
Then Godot itself loads everything and reports. Needs Draw Things API up (barrel may be served from cache)."""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

PROJ = ROOT / "sandbox" / "acceptance_game"
GODOT = "/Applications/Godot.app/Contents/MacOS/Godot"


def data(res):
    if res.is_error:
        raise RuntimeError(res.content[0].text)
    if res.structured_content:
        return res.structured_content.get("result", res.structured_content)
    out = [json.loads(c.text) for c in res.content]   # list results arrive as one JSON block per item
    return out if len(out) > 1 else out[0]


def aslist(x):
    return x if isinstance(x, list) else [x]


async def main():
    if PROJ.exists():
        shutil.rmtree(PROJ)
    (PROJ / "scenes").mkdir(parents=True)
    (PROJ / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="Acceptance"\nconfig/features=PackedStringArray("4.7")\n')
    shutil.copy(ROOT / "tests/fixtures/main_godot47.tscn", PROJ / "scenes/main.tscn")

    params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"), args=[str(ROOT / "server.py")], cwd=str(PROJ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            call = lambda n, a=None: s.call_tool(n, a or {})  # noqa: E731
            print("tools:", len((await s.list_tools()).tools))
            chk = data(await call("check_setup"))
            print("setup:", chk["blender"]["ok"], chk["image_backend"], "targets:", chk["targets"])

            job = data(await call("generate_asset", {"subject": "a rusty oil barrel", "name": "oil_barrel", "seed": 11007}))
            walls = aslist(data(await call("build_wall_set", {"material": "concrete", "texture": "tex_concrete_worn"})))
            floor = aslist(data(await call("build_floor_tile", {"variant": "cracked", "material": "asphalt",
                                                         "texture": "tex_asphalt_cracked", "name": "floor_asphalt_cracked_acc"})))
            while True:
                st = data(await call("job_status", {"job_id": job["job_id"], "wait_seconds": 60}))
                print("barrel job:", st["state"])
                if st["state"] != "running":
                    break
            assert st["state"] == "done", st
            barrel = st["result"][0]
            print("barrel:", barrel["size"], barrel["pivot"], "gate", barrel["gate_passed"])

            tiles = [a["file"].split("/")[-1][:-4] for a in walls + floor]
            print("tiles:", tiles)
            names = tiles + ["oil_barrel"]
            sync = data(await call("sync_to_godot", {"assets": names, "godot_project": str(PROJ)}))
            ts = data(await call("build_tileset", {"set": "ruins", "assets": tiles, "godot_project": str(PROJ)}))
            pl = data(await call("place_in_scene", {"scene": "scenes/main.tscn", "asset": "oil_barrel", "x": 400, "y": 300,
                                                    "parent": "Props", "node_name": "OilBarrel", "godot_project": str(PROJ)}))
            print("tileset:", ts["tileset"], "| placed:", pl["status"])

            # cwd-based auto-detect delivery (no project_path, nothing registered)
            dl = data(await call("deliver_assets", {"assets": ["oil_barrel"], "type": "folder"}))
            print("auto-detect folder delivery ->", dl["dest"])
            assert data(await call("list_targets")) == {}, "targets must stay empty"

    # Godot verifies for real
    (PROJ / "verify.gd").write_text('''extends SceneTree
func _init():
	var ts: TileSet = load("res://assets/generated/tilesets/ruins.tres")
	print("VERIFY tileset shape=", ts.tile_shape, " layout=", ts.tile_layout, " size=", ts.tile_size, " sources=", ts.get_source_count())
	var main: Node = load("res://scenes/main.tscn").instantiate()
	var b = main.get_node("Props/OilBarrel")
	print("VERIFY barrel pos=", b.position, " offset=", b.offset, " tex=", b.texture.get_size())
	quit()
''')
    subprocess.run([GODOT, "--headless", "--path", str(PROJ), "--import"], capture_output=True, timeout=180)
    out = subprocess.run([GODOT, "--headless", "--path", str(PROJ), "--script", "verify.gd"], capture_output=True, text=True, timeout=120)
    ver = [l for l in out.stdout.splitlines() if l.startswith("VERIFY")]
    print("\n".join(ver))
    assert len(ver) == 2 and "pos=(400.0, 300.0)" in ver[1] and "shape=1 layout=5" in ver[0], out.stdout + out.stderr
    print("ACCEPTANCE OK")


if __name__ == "__main__":
    asyncio.run(main())
