"""Format registration, malformed input and telemetry/frame alignment regression tests."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.robot_format import (spec_validate, spec_load, telemetry_rows_check, telemetry_check,
    telemetry_format_draft_from_file, update_json_format_specs_from_file, telemetry_format_list, telemetry_format_check)
from src.mcp_server.utils import os_json_read, os_json_write, os_rows_read
from utils_datafake import robot_fake_case, robot_fake_rows, robot_error
import copy
from pathlib import Path

dirtest="ztmp/ztests"


def test1():
    cfg,_,_,root = robot_fake_case("format1",False)
    draft = telemetry_format_draft_from_file(cfg,"data/v1/telemetry.jsonl",str(root/"draft.json"))["spec"]
    assert len(draft["fields"]) == 7
    assert draft["fields"][0]["shape"] == [6]
    assert draft["sampling"]["rate_hz"] == 100
    assert draft["fields"][4]["unit"] == "?"
    assert draft["checked_by"] == "?"


def test2():
    cfg,spec,_,root = robot_fake_case("format2",False)
    spec["fields"][4]["unit"] = "?"
    path = os_json_write(root/"bad.json",spec)
    robot_error(lambda:update_json_format_specs_from_file(cfg,path),"fields[4].unit")
    assert not Path(cfg.robot_dir).exists()


def test3():
    cfg,spec,_,root = robot_fake_case("format3",False)
    path = str(root/"input"/"xarm6_gripper_100hz.format.json")
    first = update_json_format_specs_from_file(cfg,path)
    assert first["status"] == "created"
    assert update_json_format_specs_from_file(cfg,path)["status"] == "unchanged"
    spec["fields"][0]["range"] = [-6.2,6.2]
    os_json_write(path,spec)
    robot_error(lambda:update_json_format_specs_from_file(cfg,path),"immutable",409)
    spec["format_version"] = 2
    os_json_write(path,spec)
    result = update_json_format_specs_from_file(cfg,path)
    assert result["status"] == "created" and "fields" in result["diff_vs_previous_version"]
    assert spec_load(cfg,"xarm6_gripper_100hz@1")["fields"][0]["range"] == [-6.3,6.3]
    assert len(telemetry_format_list(cfg)["formats"]["xarm6_gripper_100hz"]) == 2


def test4():
    cfg,_,_,root = robot_fake_case("format4",False)
    path = str(root/"input"/"xarm6_gripper_100hz.format.json")
    result = update_json_format_specs_from_file(cfg,path,"demo",dry_run=True)
    assert result["status"] == "created" and not Path(cfg.robot_dir).exists()
    update_json_format_specs_from_file(cfg,path,"demo")
    binding = os_json_read(Path(cfg.robot_dir)/"demo"/"collection.json")
    assert binding["telemetry_format"] == "xarm6_gripper_100hz@1"
    assert spec_load(cfg,collection_name="demo")["format_version"] == 1


def test5():
    cfg,_,args,root = robot_fake_case("format5",False)
    result = update_json_format_specs_from_file(cfg,str(root/"input"/"xarm6_gripper_100hz.format.json"),sample_path=args["telemetry_path"])
    assert result["sample_report"]["verdict"] == "pass"
    assert result["sample_report"]["file"]["n_rows"] == 201
    spec = spec_load(cfg,"xarm6_gripper_100hz@1")
    header,rows = os_rows_read("data/v1/telemetry.jsonl")
    # The draft's legacy schema is a different id, not an alias for xarm6_gripper_100hz.
    assert "header.format_id" in telemetry_rows_check(spec,header,rows)["errors"][0]
    header["schema"] = spec["format_id"]
    assert telemetry_check(spec,header,rows)["verdict"] == "pass"


def test6():
    _,spec,_,_ = robot_fake_case("format6")
    cases = [(lambda s:s["fields"].append(copy.deepcopy(s["fields"][0])),"unique"),
             (lambda s:s["fields"][0].update(names=["j1"]),"names"),
             (lambda s:s["sampling"].update(mode="guess"),"sampling.mode"),
             (lambda s:s["time"].update(dtype="float"),"time"),
             (lambda s:s["fields"][0].update(shape=[-1]),"shape"),
             (lambda s:s["sampling"].update(rate_hz=0),"rate_hz")]
    for mutate,text in cases:
        bad = copy.deepcopy(spec)
        mutate(bad)
        robot_error(lambda:spec_validate(bad),text)
    rows = robot_fake_rows()
    for key,val in [("t_ns",float(rows[0]["t_ns"])),("q",[0.0]),("gripper",850),("gripper",float("nan"))]:
        bad = copy.deepcopy(rows)
        bad[0][key] = val
        report = telemetry_check(spec,{},bad)
        assert report["verdict"] == "reject" and key in report["file"]["errors"][0]
        assert "row 0" in report["file"]["errors"][0]
    rows[1]["t_ns"] = rows[0]["t_ns"]
    assert telemetry_check(spec,{},rows)["verdict"] == "reject"


def test7():
    _,spec,args,_ = robot_fake_case("format7")
    frames = os_json_read(args["frame_map_path"])
    rows = robot_fake_rows()[5:]
    result = telemetry_check(spec,{},rows,frames)
    assert result["verdict"] == "reject" and result["align"]["coverage_ok"] is False
    assert result["align"]["n_frames_no_telemetry"] > 0
    # Tolerance boundaries at epoch scale must not be rounded through float(t_ns).
    rows = robot_fake_rows()
    rows[0]["t_ns"] = frames[0]["t_scene_ns"]+16_700_001
    rows = rows[:1]+rows[2:]
    assert telemetry_check(spec,{},rows,frames)["align"]["coverage_ok"] is False


def test8():
    _,spec,args,_ = robot_fake_case("format8")
    frames = os_json_read(args["frame_map_path"])
    rows = robot_fake_rows()
    rows = rows[:99]+rows[102:]
    spec["video_align"]["on_fail"] = "flag"
    result = telemetry_check(spec,{},rows,frames)
    assert result["verdict"] == "flag" and result["time"]["n_gaps"] == 1
    assert result["align"]["n_frames_no_telemetry"] > 0
    assert result["align"]["n_frames_cmd_stale"] > 0
    assert any(r["tel_row"] is None for r in result["frame_index"])
    # A malformed row remains rejected even when alignment failures may be flagged.
    rows[0]["gripper"] = 850
    assert telemetry_check(spec,{},rows,frames)["verdict"] == "reject"


def test9():
    cfg,spec,args,root = robot_fake_case("format9",False)
    robot_error(lambda:spec_load(cfg,collection_name="demo"),"register a telemetry format first")
    frames = os_json_read(args["frame_map_path"])
    spec["sampling"].update(mode="frame",rate_hz=29.95,max_gap_ms=40)
    rows = [{**robot_fake_rows()[0],"frame_index":i,"t_ns":f["t_scene_ns"]} for i,f in enumerate(frames)]
    assert telemetry_check(spec,{},rows,frames)["verdict"] == "pass"
    assert telemetry_check(spec,{},rows[:7]+rows[8:],frames)["verdict"] == "reject"
    # Missing optional command rows must count as stale, not reuse a future command.
    spec["fields"][-1]["required"] = False
    rows[3].pop("cmd_gripper")
    result = telemetry_check(spec,{},rows,frames)
    assert result["align"]["n_frames_cmd_stale"] == 1
    rows = [{k:v for k,v in row.items() if k != "t_ns"} for row in rows]
    assert telemetry_check(spec,{},copy.deepcopy(rows))["time"]["requires_frame_map"] is True
    report = telemetry_check(spec,{},rows,frames)
    assert rows[0]["t_ns"] == frames[0]["t_scene_ns"]
    assert report["align"]["coverage_ok"] is True


def test_all():
    os_makedirs(dirtest)
    test1(); test2(); test3(); test4(); test5(); test6(); test7(); test8(); test9()
    log_info("test_robot_format: all passed")


if __name__ == "__main__":
    fire.Fire()
