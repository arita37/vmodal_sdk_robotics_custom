"""Explicit live robot MCP handoff, index, search and retrieval integration test."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.config import McpConfig
from src.mcp_server.cli import OK_STATUS, FAIL_STATUS
from src.mcp_server.utils import os_json_write
from utils_datafake import dict_fake_robot_live
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pathlib import Path
from datetime import datetime, timezone, timedelta
import asyncio
import json
import time

dirtest="ztmp/ztests"


def test1(timeout_sec=900, poll_sec=5):
    cfg = McpConfig.from_env()
    assert not cfg.cfg_error, cfg.cfg_error
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    collection = "mcp_robot_live_"+run_id
    root = Path(dirtest,"robot_live",run_id).resolve()
    env = {**os.environ,"MCP_ROBOT_DIR":str(root/"store"),"MCP_IMAGE_DIR":str(root/"images")}
    args = dict_fake_robot_live(collection)

    async def run():
        params = StdioServerParameters(command=sys.executable,args=["-m","src.mcp_server.main_mcp","run","--transport","stdio"],
                                       env=env,cwd=os.getcwd())
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=timeout_sec)) as session:
                await session.initialize()
                async def call(name, arguments):
                    reply = await session.call_tool(name,arguments)
                    assert not reply.isError, f"{name}: {reply.content}"
                    return json.loads(reply.content[0].text)
                spec = await call("update_json_format_specs_from_file",{
                    "path":str(Path("data/robot/xarm6_gripper_100hz.format.json").resolve()),"collection_name":collection})
                assert spec["status"] == "created"
                checked = await call("robot_episode_upload",{**args,"dry_run":True})
                assert checked["status"] == "validated" and checked["check_report"]["verdict"] == "pass"
                uploaded = await call("robot_episode_upload",{**args,"dry_run":False})
                assert uploaded["status"] == "uploaded"
                log_info("robot live upload complete",collection)
                job = await call("index_create",{"mode":"vid_file","group_name":collection,"stream_name":"cam_scene",
                    "index_type":"vid_img_emb","modality":"vid_img_emb","insert_mode":"append","create_index":True,
                    "version":"new_version","re_process":True,"dry_run":False})
                assert job.get("job_id"),job
                deadline = time.monotonic()+timeout_sec
                while time.monotonic() < deadline:
                    status = await call("index_status",{"job_id":job["job_id"]})
                    state = str(status.get("status","")).lower()
                    log_info("robot live index status",job["job_id"],state)
                    assert state not in FAIL_STATUS,status
                    if state in OK_STATUS:
                        break
                    await asyncio.sleep(poll_sec)
                else:
                    raise AssertionError(f"robot index timed out: {job['job_id']}")
                found = await call("robot_find",{"collection_name":collection,"query_text":"colorful test pattern",
                    "camera":"cam_scene","limit":5,"max_pages":2,"dataset_rev":"live_r1"})
                assert found["n_kept"] > 0,found
                assert all(r["episode_uid"] == "ep_demo1" and r["dataset_rev"] == "live_r1" for r in found["data"])
                retrieved = await call("robot_retrieve",{"collection_name":collection,"records":found["data"][:1],"image_source":"auto"})
                result = retrieved["results"][0]
                assert result["errors"] == [],result
                assert set(result["images"]) == {"cam_scene","cam_wrist"},result
                assert result["index_version"] == found["index_version"]
                assert result["telemetry"]["rows"] and type(result["t_ns"]) is int
                assert result["image_sources"]["cam_scene"] == "vmodal_index",result["image_sources"]
                assert all(Path(p).is_file() for p in result["images"].values())
                out = {"ok":True,"collection":collection,"job_id":job["job_id"],"index_version":found["index_version"],
                       "n_hits":found["n_kept"],"frame_index":result["frame_index"],"t_ns":result["t_ns"],"images":result["images"]}
                os_json_write(root/"report.json",out)
                return out
    out = asyncio.run(run())
    log_info("robot live integration passed",out["collection"])
    return out


def test_all():
    return test1()


if __name__ == "__main__":
    fire.Fire()
