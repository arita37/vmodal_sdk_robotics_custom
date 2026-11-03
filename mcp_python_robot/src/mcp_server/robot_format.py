"""User-owned telemetry specifications and frame alignment checks (C2/C2c)."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
import bisect
import math
import re
import statistics
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock
from src.mcp_server.utils import (RobotError, os_robot_root, os_json_read, os_json_write,
    os_rows_read, str_json_sha, str_robot_key, os_video_probe)


def spec_validate(spec):
    if not isinstance(spec,dict):
        raise RobotError("spec must be a JSON object")
    for key in ("file","time","sampling","video_align"):
        if not isinstance(spec.get(key),dict):
            raise RobotError(f"{key}: object required")
    def walk(obj, path=""):
        if obj == "?":
            raise RobotError(f"{path}: fill and check this value")
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, f"{path}.{key}".strip("."))
        if isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")
    walk(spec)
    if not isinstance(spec.get("format_id"),str) or not re.fullmatch(r"[a-z0-9_]+", spec["format_id"]):
        raise RobotError("format_id: expected [a-z0-9_]+")
    if type(spec.get("format_version")) is not int or spec["format_version"] < 1:
        raise RobotError("format_version: positive integer required")
    if not str(spec.get("checked_by", "")).strip() or not spec.get("checked_at"):
        raise RobotError("checked_by and checked_at required")
    if spec.get("sampling", {}).get("mode") not in ("time", "frame"):
        raise RobotError("sampling.mode: expected time or frame")
    if spec.get("time", {}).get("dtype") != "int64" or spec["time"].get("unit") != "ns" or not spec["time"].get("field"):
        raise RobotError("time: int64 nanoseconds and field required")
    if spec["time"].get("order") != "strictly_increasing":
        raise RobotError("time.order: expected strictly_increasing")
    if not isinstance(spec["time"].get("time_base"),str) or not spec["time"]["time_base"]:
        raise RobotError("time.time_base required")
    if spec.get("file", {}).get("header_line") not in ("optional", "required", "none"):
        raise RobotError("file.header_line: expected optional, required or none")
    if spec.get("extra_fields") not in ("reject", "allow") or spec.get("nan_policy") != "reject":
        raise RobotError("extra_fields must be reject/allow; nan_policy must be reject")
    fields = spec.get("fields", [])
    if not isinstance(fields,list) or any(not isinstance(f,dict) for f in fields):
        raise RobotError("fields: list of objects required")
    names = [f.get("name") for f in fields]
    if not names or any(not isinstance(n,str) or not n for n in names) or len(set(names)) != len(names):
        raise RobotError("fields: nonempty unique names required")
    if spec["time"]["field"] in names or "frame_index" in names:
        raise RobotError("fields: time and frame_index are reserved")
    for i, field in enumerate(fields):
        shape = field.get("shape")
        if not isinstance(shape, list) or any(type(n) is not int or n < 1 for n in shape):
            raise RobotError(f"fields[{i}].shape: positive dimensions required")
        if "names" in field and (not isinstance(field["names"],list) or any(not isinstance(n,str) or not n for n in field["names"])
                                 or len(field["names"]) != math.prod(shape) or len(set(field["names"])) != len(field["names"])):
            raise RobotError(f"fields[{i}].names: must match shape with unique names")
        if field.get("dtype") not in ("float", "int64", "int", "bool", "string") or not field.get("unit"):
            raise RobotError(f"fields[{i}]: dtype and unit required")
        if type(field.get("required")) is not bool or field.get("role", "state") not in ("state", "command"):
            raise RobotError(f"fields[{i}]: required boolean and supported role needed")
        if "range" in field and (not isinstance(field["range"],list) or len(field["range"]) != 2
                                 or any(type(v) not in (int,float) or not math.isfinite(v) for v in field["range"])
                                 or field["range"][0] > field["range"][1]):
            raise RobotError(f"fields[{i}].range: ordered pair required")
        if field.get("check") not in (None, "unit_norm"):
            raise RobotError(f"fields[{i}].check: unsupported check")
        if field.get("check") == "unit_norm" and field["dtype"] not in ("float","int","int64"):
            raise RobotError(f"fields[{i}].check: numeric values required")
    align = spec.get("video_align", {})
    if align.get("on_fail") not in ("reject", "flag") or align.get("coverage") != "full" or align.get("ref_camera") != "cam_scene":
        raise RobotError("video_align: cam_scene, full coverage, reject/flag required")
    for section, keys in [(align, ["frame_tol_ms", "cmd_max_age_ms", "max_frames_no_telemetry", "max_frames_cmd_stale"]),
                          (spec["sampling"], ["rate_hz", "rate_tol_pct", "max_gap_ms"])]:
        for key in keys:
            val = section.get(key)
            if type(val) not in (int, float) or not math.isfinite(val) or val < 0 or (key == "rate_hz" and val == 0):
                raise RobotError(f"{key}: finite nonnegative value required")
    return spec


def spec_load(cfg, format_id=None, collection_name=None):
    root = os_robot_root(cfg)
    if not format_id and collection_name:
        path = root / str_robot_key(collection_name) / "collection.json"
        format_id = os_json_read(path).get("telemetry_format") if path.exists() else None
    if not format_id or not re.fullmatch(r"[a-z0-9_]+@[1-9][0-9]*", format_id):
        raise RobotError("register a telemetry format first (update_json_format_specs_from_file); use format_id@version")
    name, version = format_id.split("@")
    path = root / "formats" / name / f"v{version}.json"
    if not path.exists():
        raise RobotError(f"unregistered format: {format_id}")
    return spec_validate(os_json_read(path))


def telemetry_format_draft_from_file(cfg, path: str, output_path: Optional[str] = None):
    header, rows = os_rows_read(path)
    if not rows:
        raise RobotError("empty telemetry")
    fields = []
    source = {f["name"]: f for f in header.get("fields", [])}
    def shape_of(val):
        return [len(val)] + shape_of(val[0]) if isinstance(val, list) and val else []
    for name, val in rows[0].items():
        if name in ("t_ns", "frame_index"):
            continue
        leaf = val
        while isinstance(leaf, list) and leaf:
            leaf = leaf[0]
        dtype = "bool" if type(leaf) is bool else "int64" if type(leaf) is int else "float" if type(leaf) is float else "string"
        item = {"name": name, "dtype": dtype, "shape": shape_of(val), "unit": "?", "required": True, "range": "?"}
        item.update({k: v for k, v in source.get(name, {}).items() if k in ("names", "unit")})
        fields.append(item)
    times = [r["t_ns"] for r in rows if "t_ns" in r]
    rate = 1e9 / statistics.median([b-a for a,b in zip(times, times[1:])]) if len(times) > 1 else "?"
    spec = {"format_id": "?", "format_version": 1, "checked_by": "?", "checked_at": "?",
            "file": {"type": "jsonl", "header_line": "optional", "compression": ["none", "gzip"]},
            "time": {"field": "t_ns", "dtype": "int64", "unit": "ns", "time_base": header.get("time_base", "?"), "order": "strictly_increasing"},
            "sampling": {"mode": "frame" if "frame_index" in rows[0] else "time", "rate_hz": rate, "rate_tol_pct": "?", "max_gap_ms": "?"},
            "fields": fields, "extra_fields": "reject", "nan_policy": "reject",
            "video_align": {"ref_camera": "cam_scene", "frame_tol_ms": "?", "cmd_max_age_ms": "?", "coverage": "full",
                            "max_frames_no_telemetry": "?", "max_frames_cmd_stale": "?", "on_fail": "?"}}
    if output_path:
        os_json_write(output_path, spec)
    return {"spec": spec, "output_path": output_path}


def telemetry_rows_check(spec, header, rows):
    if not isinstance(header,dict) or not isinstance(rows,list):
        raise RobotError("telemetry requires an object header and array of rows")
    errors, bad = [], set()
    def err(msg, idx=None):
        errors.append(msg)
        if idx is not None:
            bad.add(idx)
    if not rows:
        err("empty telemetry")
    if spec["file"]["header_line"] == "required" and not header:
        err("header required")
    if spec["file"]["header_line"] == "none" and header:
        err("header forbidden")
    for key in ("format_id", "format_version", "time_base"):
        expected = spec["time"]["time_base"] if key == "time_base" else spec[key]
        actual = header.get(key, header.get("schema") if key == "format_id" else None)
        if actual is not None and actual != expected:
            err(f"header.{key}: differs from spec")
    if "format_sha256" in header and header["format_sha256"] != str_json_sha(spec):
        err("header.format_sha256: differs from spec")
    fields = {f["name"]: f for f in spec["fields"]}
    if "fields" in header:
        declared = header["fields"]
        if not isinstance(declared,list) or any(not isinstance(f,dict) or not isinstance(f.get("name"),str) for f in declared):
            err("header.fields: list of named objects required")
            declared = []
        if len(declared) != len(fields) or {f["name"] for f in declared} != set(fields):
            err("header.fields: field names differ")
        for field in declared:
            for key in ("names", "unit", "shape", "dtype"):
                if key in field and field.get(key) != fields.get(field["name"], {}).get(key):
                    err(f"header.{field['name']}.{key}: differs from spec")
    key = spec["time"]["field"]
    allowed = set(fields) | {key} | ({"frame_index"} if spec["sampling"]["mode"] == "frame" else set())
    def values(val, shape):
        if not shape:
            if isinstance(val, (list, dict)):
                raise ValueError("scalar required")
            return [val]
        if not isinstance(val, list) or len(val) != shape[0]:
            raise ValueError(f"shape {shape} required")
        return [x for child in val for x in values(child, shape[1:])]
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            err(f"row {idx}: object required", idx)
            continue
        t = row.get(key)
        frame_mode = spec["sampling"]["mode"] == "frame"
        if not (frame_mode and key not in row) and (type(t) is not int or not -(2**63) <= t < 2**63):
            err(f"row {idx} {key}: int64 required", idx)
        if frame_mode and (type(row.get("frame_index")) is not int or row["frame_index"] < 0):
            err(f"row {idx} frame_index: nonnegative integer required",idx)
        if spec["extra_fields"] == "reject" and set(row) - allowed:
            err(f"row {idx}: extra fields {sorted(set(row)-allowed)}", idx)
        for name, field in fields.items():
            if name not in row:
                if field["required"]:
                    err(f"row {idx} {name}: required", idx)
                continue
            try:
                vals = values(row[name], field["shape"])
                for val in vals:
                    dtype = field["dtype"]
                    valid = (type(val) in (int, float) if dtype == "float" else type(val) is int if dtype in ("int", "int64") else type(val) is bool if dtype == "bool" else isinstance(val, str))
                    if not valid or (type(val) in (int, float) and (not math.isfinite(val) or (dtype == "int64" and not -(2**63) <= val < 2**63))):
                        raise ValueError(f"finite {dtype} required")
                    if "range" in field and not field["range"][0] <= val <= field["range"][1]:
                        raise ValueError("outside range")
                if field.get("check") == "unit_norm" and abs(sum(v*v for v in vals)**0.5 - 1) > 1e-3:
                    raise ValueError("unit_norm")
            except ValueError as exc:
                err(f"row {idx} {name}: {exc}", idx)
    return {"n_rows": len(rows), "header": "mismatch" if any(e.startswith("header") for e in errors) else "match" if header else "absent", "n_bad_rows": len(bad), "errors": errors}


def frames_validate(frames):
    if not frames:
        raise RobotError("empty frame map")
    for i, row in enumerate(frames):
        if not isinstance(row,dict):
            raise RobotError(f"frame {i}: object required")
        if type(row.get("frame_index")) is not int or row["frame_index"] != i:
            raise RobotError("frame_index must be contiguous from 0")
        for key in ("t_scene_ns", "t_wrist_ns"):
            if type(row.get(key)) is not int or not -(2**63) <= row[key] < 2**63:
                raise RobotError(f"frame {i} {key}: int64 required")
        if i and row["t_scene_ns"] <= frames[i-1]["t_scene_ns"]:
            raise RobotError("frame map scene time must increase")
        if type(row.get("wrist_repeated")) is not bool or type(row.get("wrist_dt_ms")) not in (int, float):
            raise RobotError("frame map wrist_repeated/wrist_dt_ms required")
        if not math.isfinite(row["wrist_dt_ms"]) or abs((row["t_wrist_ns"]-row["t_scene_ns"])/1e6-row["wrist_dt_ms"]) > 0.001:
            raise RobotError("frame map wrist_dt_ms disagrees with timestamps")
    return frames


def telemetry_check(spec, header, rows, frames=None, video_paths=None, length=None):
    frame_mode = spec["sampling"]["mode"] == "frame"
    key = spec["time"]["field"]
    if frame_mode and frames is not None:
        frames_validate(frames)
        for row in rows:
            idx = row.get("frame_index") if isinstance(row,dict) else None
            if type(idx) is int and 0 <= idx < len(frames):
                # Frame-mode exports may omit time; only the customer map may supply it.
                row.setdefault(key,frames[idx]["t_scene_ns"])
    file = telemetry_rows_check(spec, header, rows)
    if frame_mode and [r.get("frame_index") for r in rows if isinstance(r,dict)] != list(range(len(frames) if frames is not None else len(rows))):
        file["errors"].append("frame_index: expected one row per frame, contiguous from 0")
    report = {"format_id": spec["format_id"], "format_version": spec["format_version"], "format_sha256": str_json_sha(spec),
              "file": file, "time": {}, "video": {}, "align": {}, "errors": list(file["errors"]), "warnings": [], "frame_index": []}
    fatal = bool(file["errors"])
    if frame_mode and not fatal and any(key not in r for r in rows):
        report.update(verdict="pass",time={"mode":"frame","requires_frame_map":True},warnings=["time alignment requires a frame map"])
        return report
    if not fatal:
        times = [r[spec["time"]["field"]] for r in rows]
        dt = [b-a for a,b in zip(times, times[1:])]
        if any(d <= 0 for d in dt):
            report["errors"].append("time: strictly increasing timestamps required")
            fatal = True
        else:
            gaps = [{"t_start_ns": a, "t_end_ns": b} for a,b in zip(times,times[1:]) if (b-a)/1e6 > spec["sampling"]["max_gap_ms"]]
            rate = 1e9/statistics.median(dt) if dt else None
            report["time"] = {"t_first_ns": times[0], "t_last_ns": times[-1], "rate_hz_median": rate,
                              "n_gaps": len(gaps), "gap_ms_max": max(dt, default=0)/1e6, "gaps": gaps}
            if gaps:
                report["errors"].append("time: gaps exceed max_gap_ms")
            if rate is not None and abs(rate/spec["sampling"]["rate_hz"]-1)*100 > spec["sampling"]["rate_tol_pct"]:
                report["errors"].append("time: median rate outside tolerance")
            if frames is not None:
                frames_validate(frames)
                report["video"]["n_frames_frame_map"] = len(frames)
                if length is not None and length != len(frames):
                    report["errors"].append("video: episode length differs from frame map")
                    fatal = True
                for cam, path in (video_paths or {}).items():
                    probe = os_video_probe(path)
                    report["video"][cam] = probe
                    if not probe["cfr"] or probe["n_frames_decoded"] != len(frames):
                        report["errors"].append(f"video {cam}: expected 30/1 CFR and frame map length")
                        fatal = True
                align = spec["video_align"]
                frame_mode = spec["sampling"]["mode"] == "frame"
                if frame_mode and [r.get("frame_index") for r in rows] != list(range(len(frames))):
                    report["errors"].append("frame_index: expected one row per frame, contiguous from 0")
                    fatal = True
                commands = [f for f in spec["fields"] if f.get("role") == "command"]
                misses, stale, deltas, ages = 0, 0, [], []
                for frame in frames:
                    t = frame["t_scene_ns"]
                    pos = bisect.bisect_left(times, t)
                    near = min(range(max(0,pos-1), min(len(times),pos+1)), key=lambda j: abs(times[j]-t))
                    cmd = bisect.bisect_right(times,t)-1
                    delta = (times[near]-t)/1e6
                    age = (t-times[cmd])/1e6 if cmd >= 0 else None
                    # A gap is missing data even if a boundary row is within frame tolerance.
                    in_gap = 0 < pos < len(times) and times[pos]-times[pos-1] > spec["sampling"]["max_gap_ms"]*1e6 and times[pos] != t
                    good = abs(delta) <= align["frame_tol_ms"] and not in_gap
                    cmd_good = cmd >= 0 and age <= align["cmd_max_age_ms"] and all(f["name"] in rows[cmd] for f in commands) and not in_gap
                    misses += not good
                    stale += bool(commands) and not cmd_good
                    deltas.append(abs(delta))
                    if age is not None:
                        ages.append(age)
                    report["frame_index"].append({"frame_index": frame["frame_index"], "t_scene_ns": t,
                        "tel_row": near if good else None, "tel_dt_ms": delta, "cmd_row": cmd if cmd_good else None, "cmd_age_ms": age})
                tol_ns = round(align["frame_tol_ms"]*1_000_000)
                coverage = times[0] <= frames[0]["t_scene_ns"] + tol_ns and times[-1] >= frames[-1]["t_scene_ns"] - tol_ns
                report["align"] = {"coverage_ok": coverage, "lead_ms": (frames[0]["t_scene_ns"]-times[0])/1e6,
                    "tail_ms": (times[-1]-frames[-1]["t_scene_ns"])/1e6, "n_frames_no_telemetry": misses,
                    "dt_ms_max": max(deltas), "dt_ms_mean": statistics.mean(deltas),
                    "rows_per_frame_mean": len(rows)/len(frames), "n_frames_cmd_stale": stale, "cmd_age_ms_max": max(ages, default=0)}
                if not coverage or misses > align["max_frames_no_telemetry"] or stale > align["max_frames_cmd_stale"]:
                    report["errors"].append("align: coverage, telemetry or command limits exceeded")
    report["verdict"] = "reject" if fatal else spec["video_align"]["on_fail"] if report["errors"] else "pass"
    return report


def telemetry_format_check(cfg, telemetry_path: str, format_id: Optional[str] = None, collection_name: Optional[str] = None,
                           frame_map_path: Optional[str] = None, video_paths: Optional[Dict[str,str]] = None):
    if video_paths and not frame_map_path:
        raise RobotError("frame_map_path required to check video_paths")
    spec = spec_load(cfg, format_id, collection_name)
    header, rows = os_rows_read(telemetry_path)
    frames = os_rows_read(frame_map_path)[1] if frame_map_path else None
    return telemetry_check(spec, header, rows, frames, video_paths)


def update_json_format_specs_from_file(cfg, path: str, collection_name: Optional[str] = None,
                                      sample_path: Optional[str] = None, dry_run: bool = False):
    spec = spec_validate(os_json_read(path))
    sha = str_json_sha(spec)
    root = os_robot_root(cfg)
    if collection_name:
        str_robot_key(collection_name)
    sample = telemetry_check(spec, *os_rows_read(sample_path)) if sample_path else None
    if sample and sample["verdict"] != "pass":
        raise RobotError(sample)
    folder = root / "formats"
    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)
    with (nullcontext() if dry_run else FileLock(str(folder / ".lock"), timeout=10)):
        dst = folder / spec["format_id"] / f"v{spec['format_version']}.json"
        if dst.exists() and str_json_sha(os_json_read(dst)) != sha:
            raise RobotError("immutable format version conflict; bump format_version", 409)
        previous = sorted((folder/spec["format_id"]).glob("v*.json"), key=lambda p: int(p.stem[1:]))
        prior = os_json_read(previous[-1]) if previous else {}
        diffs = []
        def diff(a,b,path=""):
            if isinstance(a,dict) and isinstance(b,dict):
                for k in sorted(a.keys() | b.keys()):
                    diff(a.get(k), b.get(k), f"{path}.{k}".strip("."))
            elif a != b:
                diffs.append(path)
        diff(prior,spec)
        status = "unchanged" if dst.exists() else "created"
        if not dry_run:
            os_json_write(dst,spec)
            idx_path = folder/"index.json"
            idx = os_json_read(idx_path) if idx_path.exists() else {}
            idx.setdefault(spec["format_id"], {})[str(spec["format_version"])] = {
                "sha256": sha, "checked_by": spec["checked_by"], "checked_at": spec["checked_at"],
                "registered_at": idx.get(spec["format_id"], {}).get(str(spec["format_version"]), {}).get("registered_at", datetime.now(timezone.utc).isoformat())}
            os_json_write(idx_path,idx)
            if collection_name:
                binding = root/collection_name/"collection.json"
                old = os_json_read(binding) if binding.exists() else {}
                os_json_write(binding, {**old, "telemetry_format": f"{spec['format_id']}@{spec['format_version']}", "fps": 30,
                                        "cameras": old.get("cameras", ["cam_scene", "cam_wrist"])})
    return {"format_id": spec["format_id"], "format_version": spec["format_version"], "format_sha256": sha,
            "status": status, "bound_collection": collection_name, "diff_vs_previous_version": diffs, "sample_report": sample}


def telemetry_format_list(cfg, format_id: Optional[str] = None):
    root = os_robot_root(cfg)
    if format_id and not re.fullmatch(r"[a-z0-9_]+", format_id):
        raise RobotError("invalid format_id")
    path = root/"formats"/"index.json"
    index = os_json_read(path) if path.exists() else {}
    return {"formats": {k:v for k,v in index.items() if not format_id or k == format_id},
            "bindings": {p.parent.name: os_json_read(p) for p in root.glob("*/collection.json")}}
