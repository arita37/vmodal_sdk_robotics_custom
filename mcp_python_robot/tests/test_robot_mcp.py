"""Exercise robot tools through handlers and an actual MCP stdio session, offline."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.main_mcp import build_server, _build_handler
from src.mcp_server.registry import TOOL_REGISTRY, tool_schema
from src.mcp_server.config import McpConfig
from utils_datafake import robot_fake_case
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio
import json
from pathlib import Path

dirtest="ztmp/ztests"


def test1():
    cfg,_,_,_ = robot_fake_case("robotmcp1",False)
    app = McpConfig.from_env(resolve_identity=False)
    app.robot_dir = cfg.robot_dir
    build_server(app)
    for name,spec in TOOL_REGISTRY.items():
        if not spec.get("robot_func"):
            continue
        schema = tool_schema(spec)
        assert not set(schema["properties"]) & {"cfg","client","find","image_download"}
        handler = _build_handler(name,spec)
        assert handler.__name__ == name+"_handler"
    assert "collection_name" in tool_schema(TOOL_REGISTRY["robot_episode_upload"])["required"]
    assert tool_schema(TOOL_REGISTRY["robot_episode_upload"])["properties"]["dry_run"]["default"] is False


def test2():
    cfg,_,_,root = robot_fake_case("robotmcp2",False)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("VMODAL_","TEST_CLIENT_")) or key == "api_key":
            del env[key]
    env.update(MCP_ROBOT_DIR=cfg.robot_dir,PYTHONPATH=os.getcwd())
    async def run():
        params = StdioServerParameters(command=sys.executable,args=["-m","src.mcp_server.main_mcp","run","--transport","stdio"],env=env,cwd=os.getcwd())
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {t.name for t in listed.tools} == set(TOOL_REGISTRY)
                result = await session.call_tool("update_json_format_specs_from_file",{
                    "path":str((root/"input"/"xarm6_gripper_100hz.format.json").resolve()),"collection_name":"demo"})
                assert not result.isError, result.content
                assert json.loads(result.content[0].text)["status"] == "created"
                result = await session.call_tool("telemetry_format_check",{
                    "telemetry_path":str((root/"input"/"ep_demo1"/"telemetry.jsonl").resolve()),"collection_name":"demo"})
                assert not result.isError, result.content
                assert json.loads(result.content[0].text)["verdict"] == "pass"
                missing = await session.call_tool("telemetry_format_check",{"telemetry_path":"unused.jsonl","collection_name":"missing"})
                assert missing.isError and "register a telemetry format" in missing.content[0].text
                live = await session.call_tool("robot_find",{"collection_name":"demo","query_text":"empty gripper"})
                assert live.isError and "401" in live.content[0].text
    asyncio.run(run())


def test_all():
    os_makedirs(dirtest)
    test1(); test2()
    log_info("test_robot_mcp: all passed")


if __name__ == "__main__":
    fire.Fire()
