"""Server smoke: launch over real stdio, list tools, call cheap ones."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def _run():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            chk = await s.call_tool("check_setup", {})
            lst = await s.call_tool("list_assets", {})
            dele = await s.call_tool("delete_asset", {"asset": "x"})
            return tools, chk, lst, dele


def test_server_stdio():
    tools, chk, lst, dele = asyncio.run(_run())
    assert {"generate_asset", "build_wall_set", "deliver_assets", "register_target", "place_in_scene",
            "build_tileset", "delete_asset", "job_status", "build_model", "build_character", "build_spriteframes", "list_kinds", "generate_texture"} <= tools
    assert "blender" in json.dumps(chk.model_dump(), default=str)
    assert "deleted" in json.dumps(dele.model_dump(), default=str)
