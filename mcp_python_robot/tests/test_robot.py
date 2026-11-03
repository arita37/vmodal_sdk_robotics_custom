"""Robot handoff and retrieval regression tests using committed synthetic samples."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.robot import (robot_episode_upload, robot_dataset_upload, robot_retrieve, robot_find,
    robot_manifest_build, manifest_read, frame_from_ts, frame_from_time, str_frame_ts, telemetry_window, telemetry_summary, episode_filter)
from src.mcp_server.robot_format import update_json_format_specs_from_file
from src.mcp_server.utils import os_json_read, os_json_write, os_rows_read, os_video_probe, os_video_frame, str_json_sha, RobotError
from utils_datafake import robot_fake_case, robot_fake_rows, robot_error
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from pathlib import Path
import asyncio
import copy
import json
from PIL import Image

dirtest="ztmp/ztests"


def test1():
    cfg,_,args,root = robot_fake_case("robot1")
    _,expected = os_rows_read(args["telemetry_path"])
    for suffix in ("telemetry.json","telemetry.jsonl","telemetry.parquet"):
        path = root/"input"/"ep_demo1"/suffix
        assert os_rows_read(path)[1] == expected
        assert type(os_rows_read(path)[1][0]["t_ns"]) is int
    out = asyncio.run(robot_episode_upload(cfg,**args))
    assert out["status"] == "validated"
    assert os_rows_read(out["episode"]["telemetry_ref"])[1] == expected
    assert os_rows_read(out["episode"]["telemetry_ref"])[0]["format_sha256"] == out["episode"]["format_sha256"]
    row = out["episode"]
    custom = {k:v for k,v in row.items() if k not in ("video","title","description","duration","info_json_sha256",
        "check_report_path","frame_index_path","video_paths","status","input_sha256")}
    assert str_json_sha(custom) == row["info_json_sha256"]


def test2():
    cfg,_,args,root = robot_fake_case("robot2")
    for uid in ("bad-uuid","a__b","a.b","a/b"):
        robot_error(lambda:asyncio.run(robot_episode_upload(cfg,**{**args,"episode_uid":uid})),"key")
    client = SimpleNamespace(collections=SimpleNamespace(video_upload=AsyncMock(),upload_metadata_jsonl=AsyncMock()))
    frames = os_json_read(args["frame_map_path"])
    os_json_write(args["frame_map_path"],frames[:-1])
    out = asyncio.run(robot_episode_upload(cfg,client=client,**{**args,"dry_run":False}))
    assert out["status"] == "rejected"
    client.collections.video_upload.assert_not_awaited()
    client.collections.upload_metadata_jsonl.assert_not_awaited()
    assert manifest_read(cfg,"demo") == []


def test3():
    cfg,_,args,root = robot_fake_case("robot3")
    for uid in ("ep_demo1","ep_demo2"):
        kw = {**args,"episode_uid":uid,"video_scene":str(root/"input"/uid/"cam_scene.mp4"),"video_wrist":str(root/"input"/uid/"cam_wrist.mp4"),
              "telemetry_path":str(root/"input"/uid/"telemetry.jsonl"),"frame_map_path":str(root/"input"/uid/"frame_map.json"),"meta_path":str(root/"input"/"meta"/(uid+".json"))}
        out = asyncio.run(robot_episode_upload(cfg,**kw))
        assert out["check_report"]["verdict"] == "pass"
    manifest = manifest_read(cfg,"demo")
    assert len(manifest) == 2
    assert all(type(r["t0_ns"]) is int and r["n_frames"] == 60 and r["format_version"] == 1 and len(r["format_sha256"]) == 64 for r in manifest)
    assert manifest[0]["wrist_dt_ms_max"] == 1.0
    assert robot_manifest_build(cfg,"demo")["n_episodes"] == 2
    # A revision or shifted frame map must never silently replace an episode.
    robot_error(lambda:asyncio.run(robot_episode_upload(cfg,**{**args,"dataset_rev":"r2"})),"dataset_rev",409)
    frames = os_json_read(args["frame_map_path"])
    frames[0]["t_scene_ns"] += 1000
    frames[0]["t_wrist_ns"] += 1000
    os_json_write(args["frame_map_path"],frames)
    robot_error(lambda:asyncio.run(robot_episode_upload(cfg,**args)),"identity",409)


def test4():
    cfg,_,args,root = robot_fake_case("robot4")
    failed = AsyncMock(side_effect=RobotError("planned upload failure"))
    client = SimpleNamespace(collections=SimpleNamespace(video_upload=AsyncMock(),upload_metadata_jsonl=failed))
    live = {**args,"dry_run":False,"client":client}
    robot_error(lambda:asyncio.run(robot_episode_upload(cfg,**live)),"planned upload failure")
    assert manifest_read(cfg,"demo")[0]["status"] == "partial"
    client.collections.upload_metadata_jsonl = AsyncMock()
    out = asyncio.run(robot_episode_upload(cfg,**live))
    assert out["status"] == "uploaded" and client.collections.video_upload.await_count == 4
    assert asyncio.run(robot_episode_upload(cfg,**live))["status"] == "skipped"
    assert client.collections.video_upload.await_count == 4
    call = client.collections.video_upload.call_args.kwargs
    assert call["video_filename"] == "ep_demo1.mp4" and "start_datetime_user" not in call
    assert call["reduce_size"] is False
    assert client.collections.upload_metadata_jsonl.call_args.kwargs["mode"] == "vid_file"
    # A new dry run cannot downgrade or mutate the uploaded episode's telemetry.
    saved = manifest_read(cfg,"demo")[0]
    old_rows = os_rows_read(saved["telemetry_ref"])[1]
    header,rows = os_rows_read(args["telemetry_path"])
    rows[0]["current"][0] = 3.0
    os_json_write(args["telemetry_path"],[header]+rows,lines=True)
    asyncio.run(robot_episode_upload(cfg,**args))
    assert manifest_read(cfg,"demo")[0] == saved
    assert os_rows_read(saved["telemetry_ref"])[1] == old_rows


def test5():
    cfg,_,_,root = robot_fake_case("robot5")
    out = asyncio.run(robot_dataset_upload(cfg,"demo",str(root/"input"/"lerobot"),"r1",str(root/"input"/"frame_map.parquet"),
        str(root/"input"/"telemetry"),str(root/"input"/"meta"),dry_run=True))
    assert out["n_pass"] == 2 and out["n_flag"] == 0 and out["n_reject"] == 0
    assert len(manifest_read(cfg,"demo")) == 2
    assert all(os_video_probe(r["video_paths"]["cam_scene"])["n_frames_decoded"] == 60 for r in manifest_read(cfg,"demo"))
    for row in manifest_read(cfg,"demo"):
        for index in (0,59):
            path = os_video_frame(row["video_paths"]["cam_scene"],root/f"{row['episode_uid']}_{index}.jpg",index)
            with Image.open(path) as img:
                red,_,blue = img.convert("RGB").getpixel((8,8))
            assert red > blue+100 if row["episode_uid"] == "ep_demo1" else blue > red+100


def test6():
    cfg,_,args,root = robot_fake_case("robot6")
    asyncio.run(robot_episode_upload(cfg,**args))
    frames = os_json_read(args["frame_map_path"])
    assert frame_from_ts(1000,frames)["t_scene_ns"] == frames[30]["t_scene_ns"]
    assert frames[30]["t_scene_ns"] != frames[0]["t_scene_ns"]+1_000_000_000
    all_frames = [{"frame_index":i} for i in range(4569)]
    assert all(frame_from_ts(str_frame_ts(i),all_frames)["frame_index"] == i for i in range(4569))
    assert str_frame_ts(969) == "0000000032299"
    assert 1761130004001999999//1_000_000 == 1761130004001
    robot_error(lambda:frame_from_ts(1761130004001999999,frames),"invalid_timestamp")
    robot_error(lambda:frame_from_ts(True,frames),"invalid_timestamp")
    missing = frames[:1]+frames[2:]
    robot_error(lambda:frame_from_time(frames[0]["t_scene_ns"]+20_000_000,missing),"no_frame")


def test7():
    cfg,_,args,root = robot_fake_case("robot7")
    asyncio.run(robot_episode_upload(cfg,**args))
    row = manifest_read(cfg,"demo")[0]
    raw = {"filename":"ep_demo1","ts_unix_13digits":1000}
    download = AsyncMock(return_value={"saved_paths":[]})
    out = asyncio.run(robot_retrieve(cfg,"demo",records=[{"record":raw,"dataset_rev":"r1","index_version":2}],image_download=download))
    result = out["results"][0]
    assert result["frame_index"] == 30 and result["t_ns"] != row["t0_ns"]+1_000_000_000
    assert result["dataset_rev"] == "r1" and result["index_version"] == 2
    assert result["image_source"] == "local_decode" and len(result["images"]) == 2
    assert download.call_args.args[0][0]["ts_unix_13digits"] == "0000000001000"
    assert download.call_args.args[0][0]["filename"] == raw["filename"]
    for path in result["images"].values():
        assert Path(path).is_absolute() and Path(path).exists()
        assert os_json_read(Path(path).with_suffix(".json"))["t_ns"] == result["t_ns"]
    noframe = asyncio.run(robot_retrieve(cfg,"demo",episode_uid="ep_demo1",t_ns=row["t0_ns"]-20_000_000,image_source="local_decode"))
    assert noframe["results"][0]["errors"] == ["no_frame"]


def test8():
    cfg,spec,args,root = robot_fake_case("robot8")
    asyncio.run(robot_episode_upload(cfg,**args))
    frames = os_json_read(args["frame_map_path"])
    out = asyncio.run(robot_retrieve(cfg,"demo",episode_uid="ep_demo1",t_ns=frames[15]["t_scene_ns"],
        image_source="local_decode",telemetry_fields=["q","current"],telemetry_rate_hz=20,window_before_ms=100,window_after_ms=100))
    result = out["results"][0]
    tel = result["telemetry"]
    assert all(tel["t_from_ns"] <= r["t_ns"] < tel["t_to_ns"] for r in tel["rows"])
    assert all(set(r) == {"t_ns","q","current"} for r in tel["rows"])
    assert tel["format"]["fields"][1]["names"][1] == "j2" and tel["format"]["fields"][1]["unit"] == "A"
    assert result["telemetry_summary"]["current_abs_max"]["j2"] == 9.0
    rows = robot_fake_rows()
    down = telemetry_window(rows[:50]+rows[60:],spec,rows[0]["t_ns"],rows[-1]["t_ns"]+1,rate=10)
    assert not any(rows[50]["t_ns"] <= r["t_ns"] < rows[60]["t_ns"] for r in down)
    assert rows[60] in down


def test9():
    cfg,_,args,root = robot_fake_case("robot9")
    asyncio.run(robot_episode_upload(cfg,**args))
    def raw(ts,filename="ep_demo1.mp4",score=0.8):
        return {"filename":filename,"ts_unix_13digits":str(ts).zfill(13),"score":score,"modality":"vid_img"}
    find = AsyncMock(side_effect=[{"version_lancedb":3,"n_total":4,"data":[raw(0),raw(1000)]},
                                 {"version_lancedb":3,"n_total":4,"data":[raw(1500),raw(0,"unmapped.mp4")]}])
    out = asyncio.run(robot_find(cfg,"demo",query_text="empty gripper",limit=2,find=find,filters={"success":False}))
    assert out["n_scanned"] == 4 and out["n_total"] == 4 and out["n_unmapped"] == 1 and out["n_kept"] == 3
    assert out["episodes"][0]["hit_count"] == 3 and len(out["episodes"][0]["windows"]) == 1
    assert find.call_args_list[1].kwargs["version_id"] == 3 and find.call_args_list[1].kwargs["offset"] == 2
    assert all(h["index_version"] == 3 and h["dataset_rev"] == "r1" for h in out["data"])
    drift = AsyncMock(side_effect=[{"version_lancedb":3,"n_total":4,"data":[raw(0)]},{"version_lancedb":4,"n_total":4,"data":[raw(0)]}])
    robot_error(lambda:asyncio.run(robot_find(cfg,"demo",query_text="x",find=drift)),"changed index version",409)
    limited = AsyncMock(return_value={"version_lancedb":3,"n_total":4,"data":[raw(0)]})
    out = asyncio.run(robot_find(cfg,"demo",query_text="x",find=limited,max_pages=1,filters={"success":True}))
    assert out["n_kept"] == 0 and out["page_cap_reached"] is True
    assert episode_filter({"start_time":"2026-10-22T23:59:00Z"},{"date_to":"2026-10-22"})
    assert episode_filter({"start_time":"2026-10-23T02:00:00+09:00"},{"date_to":"2026-10-22"})
    assert not episode_filter({"start_time":"2026-10-23T00:00:00Z"},{"date_to":"2026-10-22"})


def test_all():
    os_makedirs(dirtest)
    test1(); test2(); test3(); test4(); test5(); test6(); test7(); test8(); test9()
    log_info("test_robot: all passed")


if __name__ == "__main__":
    fire.Fire()
