from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
import io
import copy
import shutil
from pathlib import Path
from types import SimpleNamespace
from src.mcp_server.utils import os_json_read, os_rows_read, RobotError
from PIL import Image
from src.utils.util_log import log_info, log_error, log_trace, log_warning


def image_fake_bytes(fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA" if fmt == "PNG" else "RGB", (4, 3), (255, 0, 0)).save(buf, format=fmt)
    return buf.getvalue()


def robot_fake_case(name, register=True):
    from src.mcp_server.robot_format import update_json_format_specs_from_file
    root = Path("ztmp/ztests")/name
    shutil.rmtree(root,ignore_errors=True)
    shutil.copytree("data/robot",root/"input")
    cfg = SimpleNamespace(robot_dir=str((root/"store").resolve()),image_dir=str((root/"images").resolve()),upload_max_mb=5120)
    spec_path = root/"input"/"xarm6_gripper_100hz.format.json"
    if register:
        update_json_format_specs_from_file(cfg,str(spec_path),"demo")
    uid = "ep_demo1"
    folder = root/"input"/uid
    args = {"collection_name":"demo","episode_uid":uid,"video_scene":str(folder/"cam_scene.mp4"),
        "video_wrist":str(folder/"cam_wrist.mp4"),"telemetry_path":str(folder/"telemetry.jsonl"),
        "frame_map_path":str(folder/"frame_map.json"),"meta_path":str(root/"input"/"meta"/(uid+".json")),"dataset_rev":"r1","dry_run":True}
    return cfg,os_json_read(spec_path),args,root


def robot_fake_rows():
    return copy.deepcopy(os_rows_read("data/robot/ep_demo1/telemetry.jsonl")[1])


def dict_fake_robot_live(collection):
    root = Path("data/robot").resolve()
    folder = root/"ep_demo1"
    return {"collection_name":collection,"episode_uid":"ep_demo1","video_scene":str(folder/"cam_scene.mp4"),
        "video_wrist":str(folder/"cam_wrist.mp4"),"telemetry_path":str(folder/"telemetry.jsonl"),
        "frame_map_path":str(folder/"frame_map.json"),"meta_path":str(root/"meta"/"ep_demo1.json"),"dataset_rev":"live_r1"}


def robot_error(call, contains, status=422):
    """Assert an expected contract failure; unexpected exception types propagate."""
    try:
        call()
    except RobotError as exc:
        assert exc.status_code == status, str(exc)
        assert contains in str(exc), str(exc)
        return
    raise AssertionError("expected RobotError: "+contains)


def dict_fake_frame(**kw) -> Dict[str, Any]:
    return {"mode": "vid_file", "group_name": "fashion_milan", "stream_name": "runway",
            "modality": "vid_img", "filename": "Look 01.mp4", "ts_unix_13digits": "1735689600123", **kw}


def dict_fake_catalog() -> Dict[str, Any]:
    return {"data": [
        {"mode": "vid_file", "group_name": "city", "lancedb_versions": ["v0", "v2", "v10", "bad"]},
        {"mode": "vid_file", "group_name": "japan", "lancedb_versions": ["v3"]},
        {"mode": "img_file", "group_name": "photos", "lancedb_versions": []},
    ], "total": 3}


def dict_fake_stats() -> Dict[str, Any]:
    return {"rows": [
        {"mode": "vid_file", "group_name": "city", "stream_name": "rome"},
        {"mode": "vid_file", "group_name": "city", "stream_name": "tokyo"},
        {"mode": "vid_file", "group_name": "city", "stream_name": "rome"},
        {"mode": "img_file", "group_name": "photos", "stream_name": "trip|2026"},
    ]}


def str_fake_sdk_init(version: str = "1.2.3") -> str:
    return f'__version__ = "{version}"\n'


def str_fake_mcp_pyproject(version: str = "1.0.0") -> str:
    return f'''[project]
name = "vmodal_mcp"
dependencies = [
  "vmodal>={version},<2.0.0",
  "mcp>=1.2.0",
]
'''


if __name__ == "__main__":
    fire.Fire()
