"""Failure candidates, named signatures, fusion, and review export contracts."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.robot_similar import (telemetry_detect, scan, signature_distances, fuse,
    candidate_tags, review_tags, DETECTOR_VERSION)
from src.mcp_server.robot import robot_episode_upload
from src.mcp_server.utils import os_rows_read, os_json_write, os_json_read
from utils_datafake import robot_fake_case, robot_fake_rows, robot_error
import asyncio
import copy
from pathlib import Path

dirtest="ztmp/ztests"


def test1():
    _,spec,_,_ = robot_fake_case("similar1")
    rows = robot_fake_rows()
    grasp = telemetry_detect(rows,spec,"grasp_miss")["candidates"]
    drop = telemetry_detect(rows,spec,"object_drop")["candidates"]
    assert len(grasp) == 1 and abs(grasp[0]["t_ns"]-rows[15]["t_ns"]) <= 50_000_000
    assert len(drop) == 1 and abs(drop[0]["t_ns"]-rows[80]["t_ns"]) <= 50_000_000
    clean = os_rows_read("data/robot/ep_demo2/telemetry.jsonl")[1]
    assert telemetry_detect(clean,spec,"grasp_miss")["candidates"] == []
    assert telemetry_detect(clean,spec,"object_drop")["candidates"] == []


def test2():
    _,spec,_,_ = robot_fake_case("similar2")
    rows = robot_fake_rows()
    original = telemetry_detect(rows,spec,"object_drop")
    reordered = copy.deepcopy(spec)
    reordered["fields"].reverse()
    assert telemetry_detect(rows,reordered,"object_drop") == original
    # Command role and units are mandatory; do not interpret raw 0..850 as normalized.
    spec["fields"][-1]["role"] = "state"
    assert telemetry_detect(rows,spec,"grasp_miss")["skipped"]
    spec["fields"][-1]["role"] = "command"
    spec["fields"][2]["unit"] = "raw"
    assert telemetry_detect(rows,spec,"grasp_miss")["skipped"]


def test3():
    cfg,spec,args,root = robot_fake_case("similar3")
    asyncio.run(robot_episode_upload(cfg,**args))
    result = scan("demo","grasp_miss",robot_dir=cfg.robot_dir)
    assert result["n_scanned"] == 1 and result["candidates"][0]["dataset_rev"] == "r1"
    assert result["detector_version"] == DETECTOR_VERSION
    rows = robot_fake_rows()
    gap = [{"t_start_ns":rows[9]["t_ns"],"t_end_ns":rows[16]["t_ns"]}]
    assert telemetry_detect(rows,spec,"grasp_miss",gap)["candidates"] == []
    assert telemetry_detect(rows,spec,"occlusion_wrist")["skipped"]
    custom = telemetry_detect(rows,spec,"grasp_miss",thresholds={"close":0.96})["candidates"]
    assert custom[0]["tagger_version"].startswith(DETECTOR_VERSION+".")


def test4():
    _,spec,_,_ = robot_fake_case("similar4")
    rows = robot_fake_rows()
    similar = copy.deepcopy(rows)
    clean = copy.deepcopy(rows)
    for row in similar:
        row["gripper"] += 0.005
    for row in clean:
        row["gripper"] = 0.5
    distances = signature_distances(rows,[rows,similar,clean],spec,["gripper","current.j2"])
    assert distances[0] == 0 and 0 < distances[1] < distances[2]
    # Reorder vector sub-names with their values; named signatures are unchanged.
    other = copy.deepcopy(spec)
    other["fields"][1]["names"].reverse()
    changed = copy.deepcopy(rows)
    for row in changed:
        row["current"].reverse()
    assert signature_distances(changed,[changed],other,["current.j2"]) == [0]
    robot_error(lambda:signature_distances(rows[:10]+rows[20:],[rows],spec,["gripper"]),"gap")


def test5():
    _,_,_,root = robot_fake_case("similar5")
    base = {"episode_uid":"ep_demo1","dataset_rev":"r1","index_version":2,"t_start_ns":1761130004001200000,"t_end_ns":1761130004101200000,"relevance":0.8}
    candidates = [{**base,"verdict":"PASS"},{**base,"verdict":"PARTIAL","detector":"grasp_miss","confidence":0.8},
                  {**base,"verdict":"FAIL"}]
    out = candidate_tags(candidates,"grasp_miss",2,"testtags",str(root/"tags"))
    rows = os_rows_read(out["jsonl"])[1]
    assert out["n_tags"] == 2 and rows[0]["confidence"] is None and rows[1]["confidence"] == 0.8
    assert all(r["source"] == "auto" and r["review_status"] == "unreviewed" and r["supersedes"] is None for r in rows)
    assert os_rows_read(out["parquet"])[1] == rows
    assert type(rows[0]["t_start_ns"]) is int
    robot_error(lambda:candidate_tags(candidates,"grasp_miss",2,"testtags",str(root/"tags")),"already exists",409)
    robot_error(lambda:candidate_tags(candidates,"grasp_miss",None,"next",str(root/"tags")),"index_version")
    decisions = os_json_write(root/"decisions.json",[{"tag_id":rows[0]["tag_id"],"review_status":"accepted"},
                                                   {"tag_id":rows[1]["tag_id"],"review_status":"corrected","tag":"slip"}])
    reviewed = review_tags(out["jsonl"],decisions,"reviewer",str(root/"tags"),"review1")
    human = os_rows_read(reviewed["jsonl"])[1]
    assert human[0]["source"] == "human" and human[0]["supersedes"] == rows[0]["tag_id"]
    assert human[1]["tag"] == "slip" and os_rows_read(out["jsonl"])[1] == rows


def test6():
    base = {"episode_uid":"ep_demo1","dataset_rev":"r1","index_version":2,"t_start_ns":0,"t_end_ns":1_000_000_000,"relevance":0.8}
    telemetry = [{**base,"t_start_ns":2_000_000_000,"t_end_ns":3_000_000_000,"detector":"grasp_miss","confidence":0.8}]
    result = fuse([[base],[base]],telemetry,[0])
    assert len(result) == 1 and result[0]["confidence"] == 0.8
    assert result[0]["relevance"] == 3/61
    robot_error(lambda:fuse([[base],[{**base,"index_version":3}]],[]),"index versions")
    far = [{**base,"t_start_ns":i*3_000_000_000,"t_end_ns":i*3_000_000_000+1_000_000_000} for i in range(10)]
    result = fuse([far],[])
    assert all(r["t_end_ns"]-r["t_start_ns"] <= 15_000_000_000 for r in result)


def test_all():
    os_makedirs(dirtest)
    test1(); test2(); test3(); test4(); test5(); test6()
    log_info("test_robot_similar: all passed")


if __name__ == "__main__":
    fire.Fire()
