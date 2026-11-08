"""Rebuild small synthetic robot samples, including a packed LeRobot v3 dataset."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
import copy
import subprocess
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from src.mcp_server.utils import os_json_read, os_json_write


def build():
    root = Path(__file__).resolve().parent
    spec = os_json_read(root/"v1"/"input_spec.json")
    spec.update(checked_by="synthetic_fixture",checked_at="2026-11-03",description="Synthetic test fixture, not a customer-approved production format")
    current = next(f for f in spec["fields"] if f["name"] == "current")
    current.update(range=[-1, 1], note="Synthetic fixture bound only: nominal 0.1–0.3 A, planted 9 A spike must fail. Not a robot safety rating.")
    os_json_write(root/"robot"/"xarm6_gripper_100hz.format.json",spec)
    frames_all, table = [],[]
    for ep,uid in enumerate(("ep_demo1","ep_demo2")):
        t0 = 1761130004001200000 + ep*10_000_000_000
        rows = []
        for i in range(201):
            g = (0.0 if i < 15 else 0.99 if i < 80 else 0.7) if ep == 0 else 0.5
            row = {"t_ns":t0+i*10_000_000,"q":[0.1]*6,"current":[0.2,9.0 if i == 50 else 0.3,0.1,0.1,0.1,0.1],
                "gripper":g,"ee_pos":[i*0.001,0.0,0.2],"ee_quat":[0.0,0.0,0.0,1.0],"cmd_q":[0.1]*6,
                "cmd_gripper":float(i >= 10) if ep == 0 else 1.0}
            rows.append(row)
        frames = [{"episode_uid":uid,"episode_index":ep,"frame_index":i,"t_scene_ns":t0+round(i*1e9/29.95),
                   "t_wrist_ns":t0+round(i*1e9/29.95)+1_000_000,"wrist_dt_ms":1.0,"wrist_repeated":False} for i in range(60)]
        folder = root/"robot"/uid
        header = {"format_id":spec["format_id"],"format_version":1,"episode_uid":uid,"fields":copy.deepcopy(spec["fields"])}
        os_json_write(folder/"telemetry.jsonl",[header]+rows,lines=True)
        os_json_write(root/"robot"/"telemetry"/(uid+".jsonl"),[header]+rows,lines=True)
        os_json_write(folder/"telemetry.json",{"header":header,"rows":rows})
        pq.write_table(pa.Table.from_pylist(rows),folder/"telemetry.parquet")
        os_json_write(folder/"frame_map.json",frames)
        os_json_write(root/"robot"/"meta"/(uid+".json"),{"episode_uid":uid,"robot_id":"xarm_demo","operator_id":"fixture",
            "task":"put the cup in the bin","success":ep==1,"duration_s":2,"length":60,"start_time":"2026-10-22T10:00:00Z",
            "sync_offset_ms_max":1.0,"sync_offset_ms_mean":0.5,"n_dropped":0,"cmd_latency_ms":0})
        os_json_write(folder/"meta.json", os_json_read(root/"robot"/"meta"/(uid+".json")))
        frames_all.extend(frames)
        item = {"episode_index":ep,"length":60,"tasks":["put the cup in the bin"],"dataset_from_index":ep*60,"dataset_to_index":(ep+1)*60}
        for cam in ("cam_scene","cam_wrist"):
            dst = folder/(cam+".mp4")
            subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=64x48:rate=30",
                "-vf",f"drawbox=x=0:y=0:w=16:h=16:color={'red' if ep==0 else 'blue'}:t=fill",
                "-frames:v","60","-an","-c:v","libx264","-pix_fmt","yuv420p",str(dst)],check=True)
            prefix = f"videos/observation.images.{cam}/"
            item.update({prefix+"chunk_index":0,prefix+"file_index":0,prefix+"from_timestamp":ep*2.0,prefix+"to_timestamp":(ep+1)*2.0})
        table.append(item)
    packed = root/"robot"/"lerobot"
    os_json_write(packed/"meta"/"info.json",{"codebase_version":"v3.0","fps":30,"total_episodes":2,"total_frames":120,
        "video_path":"videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"})
    path = packed/"meta"/"episodes"/"chunk-000"/"file-000.parquet"
    path.parent.mkdir(parents=True,exist_ok=True)
    pq.write_table(pa.Table.from_pylist(table),path)
    for cam in ("cam_scene","cam_wrist"):
        path = packed/"videos"/f"observation.images.{cam}"/"chunk-000"/"file-000.mp4"
        path.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=64x48:rate=30",
            "-vf","drawbox=x=0:y=0:w=16:h=16:color=red:t=fill:enable='lt(t,2)',drawbox=x=0:y=0:w=16:h=16:color=blue:t=fill:enable='gte(t,2)'",
            "-frames:v","120","-an","-c:v","libx264","-pix_fmt","yuv420p",str(path)],check=True)
    pq.write_table(pa.Table.from_pylist(frames_all),root/"robot"/"frame_map.parquet")
    return {"episodes":2,"root":str(root/"robot")}


if __name__ == "__main__":
    fire.Fire()
