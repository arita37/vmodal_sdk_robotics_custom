"""Versioned local failure candidates, signature ranking and append-only review exports."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
import math
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock
from src.mcp_server.config import McpConfig
from src.mcp_server.robot import manifest_read, telemetry_named, windows_merge
from src.mcp_server.robot_format import spec_load
from src.mcp_server.utils import RobotError, os_rows_read, os_json_read, os_json_write, str_robot_key, str_json_sha

DETECTOR_VERSION = "xarm_demo_v1"
REQUIRES = {
    "grasp_miss": {"gripper":"0_open_1_closed","cmd_gripper":"0_open_1_closed"},
    "object_drop": {"gripper":"0_open_1_closed","cmd_gripper":"0_open_1_closed","ee_pos":"m"},
    "slip": {"gripper":"0_open_1_closed","cmd_gripper":"0_open_1_closed"},
    "collision_contact": {"current":"A","ee_pos":"m"},
    "joint_limit": {"q":"rad"}, "hesitation_idle": {"ee_pos":"m"},
}


def detector_check(spec, detector):
    if detector not in REQUIRES:
        return "visual-only or unknown detector"
    fields = {f["name"]:f for f in spec["fields"]}
    for name,unit in REQUIRES[detector].items():
        field = fields.get(name,{})
        if field.get("unit") != unit or (name.startswith("cmd_") and field.get("role") != "command"):
            return f"requires {name} in {unit} with command role where applicable"
        if name in ("q","current","ee_pos") and not field.get("names"):
            return f"requires named {name} components"
    if detector == "joint_limit" and not fields["q"].get("range"):
        return "joint_limit requires spec range"
    return None


def telemetry_detect(rows, spec, detector, gaps=None, thresholds=None):
    reason = detector_check(spec,detector)
    if reason:
        return {"candidates":[],"skipped":reason}
    thresholds = thresholds or {}
    version = DETECTOR_VERSION + ("."+str_json_sha(thresholds)[:12] if thresholds else "")
    key = spec["time"]["field"]
    fields = {f["name"]:f for f in spec["fields"]}
    segments,segment = [],[]
    for row in rows:
        t = row[key]
        valid = all(name in row for name in REQUIRES[detector]) and not any(g["t_start_ns"] < t < g["t_end_ns"] for g in gaps or [])
        if segment and (not valid or t-segment[-1][key] > spec["sampling"]["max_gap_ms"]*1e6):
            segments.append(segment)
            segment = []
        if valid:
            segment.append(row)
    if segment:
        segments.append(segment)
    events = []
    def event(t):
        if not events or t-events[-1]["t_ns"] > 300_000_000:
            events.append({"t_ns":t,"t_start_ns":t-100_000_000,"t_end_ns":t+100_000_000,
                           "detector":detector,"confidence":0.8,"tagger_version":version})
    for seg in segments:
        named = [telemetry_named(r,spec) for r in seg]
        speed = [0.0]
        if "ee_pos" in REQUIRES[detector]:
            for i in range(1,len(seg)):
                a,b = named[i-1]["ee_pos"],named[i]["ee_pos"]
                speed.append(math.sqrt(sum((b[n]-a[n])**2 for n in a))/((seg[i][key]-seg[i-1][key])/1e9))
        idle = None
        for i in range(1,len(seg)):
            a,b,t = named[i-1],named[i],seg[i][key]
            if detector == "grasp_miss" and a["cmd_gripper"] < 0.5 <= b["cmd_gripper"]:
                future = next((j for j in range(i,len(seg)) if seg[j][key]-t <= 500_000_000 and named[j]["gripper"] > thresholds.get("close",0.95)),None)
                if future is not None:
                    event(seg[future][key])
            elif detector == "object_drop" and a["cmd_gripper"] >= 0.95 and b["cmd_gripper"] >= 0.95:
                if b["gripper"]-a["gripper"] < -thresholds.get("opening",0.1) or (0.1 < a["gripper"] < 0.95 <= b["gripper"] and speed[i] > thresholds.get("transport_mps",0.02)):
                    event(t)
            elif detector == "slip" and b["cmd_gripper"] >= 0.95:
                if any(0 < t-seg[j][key] < 300_000_000 and named[j]["cmd_gripper"] >= 0.95 and 0.05 < b["gripper"]-named[j]["gripper"] < 0.5 for j in range(max(0,i-100),i)):
                    event(t)
            elif detector == "collision_contact":
                limits = thresholds.get("current_A",{})
                if any(abs(v) > limits.get(n,5.0) for n,v in b["current"].items()) and speed[i] < speed[i-1]*0.5:
                    event(t)
            elif detector == "joint_limit":
                low,high = fields["q"]["range"]
                if any(min(v-low,high-v) < thresholds.get("margin_rad",0.05) for v in b["q"].values()):
                    event(t)
            elif detector == "hesitation_idle":
                if speed[i] < thresholds.get("idle_mps",0.005):
                    idle = t if idle is None else idle
                    if t-idle >= 3_000_000_000 and idle > rows[0][key]+1_000_000_000 and t < rows[-1][key]-1_000_000_000:
                        event(t)
                else:
                    idle = None
    return {"candidates":events,"skipped":None}


def scan(collection_name: str, detector: str, robot_dir: Optional[str] = None, thresholds_path: Optional[str] = None):
    cfg = McpConfig.from_env(resolve_identity=False)
    if robot_dir:
        cfg.robot_dir = robot_dir
    thresholds = os_json_read(thresholds_path) if thresholds_path else {}
    out,skipped = [],[]
    scanned = 0
    for episode in manifest_read(cfg,collection_name):
        if episode.get("status") == "partial":
            skipped.append({"episode_uid":episode["episode_uid"],"reason":"partial upload"})
            continue
        spec = spec_load(cfg,f"{episode['format_id']}@{episode['format_version']}")
        if str_json_sha(spec) != episode["format_sha256"]:
            raise RobotError("episode format hash mismatch")
        report = os_json_read(episode["check_report_path"])
        result = telemetry_detect(os_rows_read(episode["telemetry_ref"])[1],spec,detector,report["time"].get("gaps"),thresholds)
        if result["skipped"]:
            skipped.append({"episode_uid":episode["episode_uid"],"reason":result["skipped"]})
        else:
            scanned += 1
        out.extend({**r,"episode_uid":episode["episode_uid"],"dataset_rev":episode["dataset_rev"]} for r in result["candidates"])
    version = DETECTOR_VERSION + ("."+str_json_sha(thresholds)[:12] if thresholds else "")
    return {"candidates":out,"n_scanned":scanned,"skipped":skipped,"detector_version":version,"thresholds":thresholds}


def signature_distances(anchor, candidates, spec, fields, steps=32):
    """Nearest-sample fixed-length signatures, z-scored using the scanned set."""
    if not fields or type(steps) is not int or steps < 2:
        raise RobotError("named fields and at least two steps required")
    key = spec["time"]["field"]
    def vectors(rows):
        if not rows:
            raise RobotError("empty signature window")
        if any(b[key]-a[key] > spec["sampling"]["max_gap_ms"]*1e6 for a,b in zip(rows,rows[1:])):
            raise RobotError("signature window crosses a telemetry gap")
        named = [telemetry_named(r,spec) for r in rows]
        columns = []
        for path in fields:
            parts = path.split(".")
            vals = []
            for row in named:
                val = row
                for part in parts:
                    if not isinstance(val,dict) or part not in val:
                        raise RobotError(f"signature requires named field {path}")
                    val = val[part]
                if type(val) not in (int,float) or not math.isfinite(val):
                    raise RobotError(f"signature requires numeric scalar {path}")
                vals.append(val)
            columns.append(vals)
        # Work in offsets to preserve ns precision.
        dt = rows[-1][key]-rows[0][key]
        indices = [min(range(len(rows)),key=lambda j:abs((rows[j][key]-rows[0][key])-round(i*dt/(steps-1)))) for i in range(steps)]
        return [[col[j] for j in indices] for col in columns]
    av = vectors(anchor)
    cv = [vectors(c) for c in candidates]
    pool = cv or [av]
    scales = [statistics.pstdev([v for sig in pool for v in sig[i]]) or 1.0 for i in range(len(fields))]
    return [math.sqrt(sum(((a-b)/scales[i])**2 for i,(aa,bb) in enumerate(zip(av,sig)) for a,b in zip(aa,bb))/(steps*len(fields))) for sig in cv]


def fuse(searches, telemetry, distances=None):
    """Fuse ranks within an index version; detector confidence remains a separate value."""
    versions = {h["index_version"] for group in searches for h in group}
    if len(versions) > 1 or None in versions:
        raise RobotError("cannot fuse across index versions")
    rows = []
    for group in searches:
        rows.extend({**h,"relevance":1/(60+rank),"confidence":None} for rank,h in enumerate(group,1))
    order = sorted(range(len(telemetry)),key=lambda j:distances[j]) if distances is not None else list(range(len(telemetry)))
    rows.extend({**telemetry[j],"relevance":1/(60+rank),"telemetry_distance":distances[j] if distances is not None else None} for rank,j in enumerate(order,1))
    out = []
    for uid in dict.fromkeys(r["episode_uid"] for r in rows):
        group = [r for r in rows if r["episode_uid"] == uid]
        if len({r["dataset_rev"] for r in group}) != 1:
            raise RobotError("cannot fuse different dataset revisions of an episode")
        for window in windows_merge(group):
            included = [r for r in group if r["t_start_ns"] < window["t_end_ns"] and r["t_end_ns"] > window["t_start_ns"]]
            detector = max((r for r in included if r.get("detector") and r.get("confidence") is not None),key=lambda r:r["confidence"],default={})
            out.append({**included[0],**window,"relevance":sum(r["relevance"] for r in included),
                "detector":detector.get("detector"),"tagger_version":detector.get("tagger_version",DETECTOR_VERSION),
                "confidence":detector.get("confidence")})
    return sorted(out,key=lambda r:r["relevance"],reverse=True)


def candidate_tags(candidates, tag, index_version, query_id, out, tagger_version=DETECTOR_VERSION, min_relevance=0):
    str_robot_key(query_id)
    if index_version is None:
        raise RobotError("index_version required for reproducible tags")
    rows = []
    for hit in candidates:
        if hit.get("verdict") not in ("PASS","PARTIAL") or hit.get("relevance",0) < min_relevance:
            continue
        if not hit.get("dataset_rev") or hit.get("index_version",index_version) != index_version:
            raise RobotError("dataset_rev required and index_version must match")
        if type(hit.get("t_start_ns")) is not int or type(hit.get("t_end_ns")) is not int or hit["t_start_ns"] >= hit["t_end_ns"]:
            raise RobotError("tag requires int64 half-open time window")
        confidence = hit.get("confidence") if hit.get("detector") else None
        version = hit.get("tagger_version",tagger_version)
        if confidence is not None and (hit["detector"] not in REQUIRES or not version.startswith(DETECTOR_VERSION)):
            raise RobotError("confidence requires a versioned telemetry detector")
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise RobotError("invalid detector confidence")
        rows.append({"tag_id":uuid.uuid4().hex,"episode_uid":hit["episode_uid"],"t_start_ns":hit["t_start_ns"],"t_end_ns":hit["t_end_ns"],
            "tag":tag,"source":"auto","tagger":"vmodal-robot-similar","tagger_version":f"{version}+idx{index_version}",
            "relevance":hit.get("relevance"),"confidence":confidence,"review_status":"unreviewed","supersedes":None,
            "created_at":datetime.now(timezone.utc).isoformat(),"dataset_rev":hit["dataset_rev"],"index_version":str(index_version)})
    return tags_save(rows,Path(out)/f"tags_candidates_{query_id}")


def tags_save(rows, stem):
    import pyarrow as pa
    import pyarrow.parquet as pq
    stem = Path(stem)
    stem.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(stem)+".lock",timeout=10):
        if stem.with_suffix(".jsonl").exists() or stem.with_suffix(".parquet").exists():
            raise RobotError("tag export already exists; choose a new query_id",409)
        schema = pa.schema([(k,pa.int64() if k in ("t_start_ns","t_end_ns") else pa.float64() if k in ("relevance","confidence") else pa.string())
            for k in ("tag_id","episode_uid","t_start_ns","t_end_ns","tag","source","tagger","tagger_version","relevance","confidence","review_status","supersedes","created_at","dataset_rev","index_version")])
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),stem.with_suffix(".parquet"))
        os_json_write(stem.with_suffix(".jsonl"),rows,lines=True)
    return {"n_tags":len(rows),"jsonl":str(stem.with_suffix(".jsonl").resolve()),"parquet":str(stem.with_suffix(".parquet").resolve())}


def review_tags(tags_path, decisions_path, reviewer, out, query_id):
    """Apply explicit human decisions as new rows that supersede candidate ids."""
    str_robot_key(query_id)
    if not str(reviewer).strip():
        raise RobotError("reviewer required")
    originals = {r["tag_id"]:r for r in os_rows_read(tags_path)[1]}
    decisions = os_json_read(decisions_path)
    rows = []
    for decision in decisions:
        if decision["tag_id"] not in originals or decision["review_status"] not in ("accepted","rejected","corrected"):
            raise RobotError("decision must reference a candidate and an explicit human status")
        if decision["review_status"] == "corrected" and not decision.get("tag"):
            raise RobotError("corrected decision requires tag")
        original = originals[decision["tag_id"]]
        rows.append({**original,"tag_id":uuid.uuid4().hex,"tag":decision.get("tag",original["tag"]),"source":"human",
            "tagger":reviewer,"review_status":decision["review_status"],"supersedes":original["tag_id"],"created_at":datetime.now(timezone.utc).isoformat()})
    return tags_save(rows,Path(out)/f"tags_review_{query_id}")


def write_from_file(path, tag, index_version, query_id, out, min_relevance=0):
    data = os_json_read(path)
    return candidate_tags(data if isinstance(data,list) else data["candidates"],tag,index_version,query_id,out,min_relevance=min_relevance)


if __name__ == "__main__":
    fire.Fire()
