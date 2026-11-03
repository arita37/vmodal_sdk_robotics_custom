"""Robot episode handoff, frame-map lookup, retrieval and episode search."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
import bisect
import math
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from filelock import FileLock
from src.mcp_server.utils import (RobotError, os_json_read, os_json_write, os_rows_read,
    os_robot_root, str_robot_key, str_json_sha, os_file_sha, os_video_cut, os_video_frame)
from src.mcp_server.robot_format import spec_load, telemetry_check, frames_validate

SYNC_KEYS = ("sync_offset_ms_max", "sync_offset_ms_mean", "wrist_dt_ms_max", "wrist_dt_ms_mean",
             "n_dropped", "cmd_age_ms_max", "cmd_latency_ms")


def manifest_read(cfg, collection_name):
    path = os_robot_root(cfg)/str_robot_key(collection_name)/"episodes.jsonl"
    return os_rows_read(path)[1] if path.exists() else []


def manifest_save(cfg, collection_name, row):
    folder = os_robot_root(cfg)/str_robot_key(collection_name)
    folder.mkdir(parents=True, exist_ok=True)
    with FileLock(str(folder/".manifest.lock"), timeout=10):
        rows = [r for r in manifest_read(cfg,collection_name) if r["episode_uid"] != row["episode_uid"]]
        os_json_write(folder/"episodes.jsonl", rows+[row], lines=True)
        os_json_write(Path(row["telemetry_ref"]).parent/"episode.json", row)


async def robot_episode_upload(cfg, collection_name: str, episode_uid: str, video_scene: str,
        telemetry_path: str, frame_map_path: str, meta_path: str, dataset_rev: str,
        video_wrist: Optional[str] = None, format_id: Optional[str] = None, fps: int = 30,
        dry_run: bool = False, client=None):
    str_robot_key(collection_name)
    str_robot_key(episode_uid)
    if not dataset_rev or fps != 30:
        raise RobotError("dataset_rev and fps exactly 30 required")
    folder = os_robot_root(cfg)/collection_name
    folder.mkdir(parents=True, exist_ok=True)
    # Serialize same-episode handoffs; do not block the event loop behind a network upload.
    with FileLock(str(folder/f".{episode_uid}.lock"), timeout=0):
        return await episode_upload(cfg,collection_name,episode_uid,video_scene,telemetry_path,
            frame_map_path,meta_path,dataset_rev,video_wrist,format_id,dry_run,client)


async def episode_upload(cfg, collection_name, episode_uid, video_scene, telemetry_path,
                         frame_map_path, meta_path, dataset_rev, video_wrist, format_id, dry_run, client):
    spec = spec_load(cfg,format_id,collection_name)
    header, rows = os_rows_read(telemetry_path)
    _, frames = os_rows_read(frame_map_path)
    frames = [r for r in frames if r.get("episode_uid",episode_uid) == episode_uid]
    frames_validate(frames)
    meta = os_json_read(meta_path)
    if meta.get("episode_uid",episode_uid) != episode_uid or header.get("episode_uid",episode_uid) != episode_uid:
        raise RobotError("metadata/telemetry episode_uid mismatch")
    if meta.get("dataset_rev",dataset_rev) != dataset_rev:
        raise RobotError("metadata dataset_rev mismatch")
    videos = {"cam_scene": str(Path(video_scene).resolve())}
    if video_wrist:
        videos["cam_wrist"] = str(Path(video_wrist).resolve())
    sha = str_json_sha(spec)
    old = {r["episode_uid"]:r for r in manifest_read(cfg,collection_name)}
    for previous in old.values():
        if previous["dataset_rev"] != dataset_rev:
            raise RobotError("one collection per dataset_rev; choose a new collection",409)
    if episode_uid in old and (old[episode_uid]["t0_ns"] != frames[0]["t_scene_ns"] or old[episode_uid]["n_frames"] != len(frames)):
        raise RobotError("episode identity changed; choose a new collection",409)
    report = telemetry_check(spec,header,rows,frames,videos,meta.get("length",meta.get("n_frames")))
    report["episode_uid"] = episode_uid
    folder = os_robot_root(cfg)/collection_name
    report_path = os_json_write(folder/"checks"/f"{episode_uid}.json",report)
    if report["verdict"] == "reject":
        return {"episode_uid":episode_uid,"status":"rejected","check_report":report,"check_report_path":report_path,"planned_uploads":[]}
    for path in videos.values():
        if Path(path).stat().st_size > cfg.upload_max_mb*1024*1024:
            raise RobotError("clip exceeds MCP_UPLOAD_MAX_MB")
    input_sha = str_json_sha({"rows":rows,"frames":frames,"meta":meta,"format":sha,
                            "videos":{k:os_file_sha(v) for k,v in videos.items()}})
    artifacts = folder/"artifacts"/episode_uid/input_sha
    report_path = os_json_write(artifacts/"check.json",report)
    stored_header = {"format_id":spec["format_id"],"format_version":spec["format_version"],"format_sha256":sha,"episode_uid":episode_uid}
    tel = os_json_write(artifacts/"telemetry.jsonl.gz",[stored_header]+rows,lines=True)
    fmap = os_json_write(artifacts/"frame_map.jsonl.gz",frames,lines=True)
    idx = os_json_write(artifacts/"frame_index.jsonl.gz",report["frame_index"],lines=True)
    os_json_write(folder/"frame_index"/f"{episode_uid}.jsonl.gz",report["frame_index"],lines=True)
    wrist = [abs(r["wrist_dt_ms"]) for r in frames]
    sync = {k:meta.get(k) for k in SYNC_KEYS}
    sync.update(wrist_dt_ms_max=max(wrist),wrist_dt_ms_mean=statistics.mean(wrist),cmd_age_ms_max=report["align"]["cmd_age_ms_max"])
    metadata = {**meta,**sync,**stored_header,"video":episode_uid+".mp4","title":meta.get("task",""),
        "duration":len(frames)/30,"dataset_rev":dataset_rev,"fps":30,"n_frames":len(frames),"t0_ns":frames[0]["t_scene_ns"],
        "telemetry_ref":tel,"frame_map_ref":fmap,"check_verdict":report["verdict"],
        "n_frames_no_telemetry":report["align"]["n_frames_no_telemetry"],
        "n_frames_cmd_stale":report["align"]["n_frames_cmd_stale"],"telemetry_gap_ms_max":report["time"]["gap_ms_max"]}
    metadata["info_json_sha256"] = str_json_sha({k:v for k,v in metadata.items()
        if k not in ("video","title","description","duration","info_json_sha256")})
    record = {**metadata,"check_report_path":report_path,"frame_index_path":idx,"video_paths":videos,"status":"validated"}
    # Content identity prevents resume from skipping changed telemetry/metadata.
    record["input_sha256"] = input_sha
    planned = [{"camera":cam,"local_path":path,"filename":episode_uid+".mp4"} for cam,path in videos.items()]
    if not dry_run and episode_uid in old and old[episode_uid].get("status") == "uploaded" and old[episode_uid].get("input_sha256") == record["input_sha256"]:
        return {"episode_uid":episode_uid,"status":"skipped","check_report":report,"episode":old[episode_uid]}
    if dry_run:
        # Do not downgrade a successfully uploaded episode during a later dry run.
        if episode_uid not in old or old[episode_uid].get("status") != "uploaded":
            manifest_save(cfg,collection_name,record)
        return {"episode_uid":episode_uid,"status":"validated","check_report":report,"planned_uploads":planned,"episode":record}
    if client is None:
        raise RobotError("upload requires an authenticated SDK client")
    record["status"] = "partial"
    manifest_save(cfg,collection_name,record)
    try:
        for cam,path in videos.items():
            await client.collections.video_upload(filepath_local=path,collection_name=collection_name,
                sub_collection_name=cam,video_filename=episode_uid+".mp4",reduce_size=False)
        path = os_json_write(artifacts/"metadata.jsonl",[metadata],lines=True)
        for cam in videos:
            await client.collections.upload_metadata_jsonl(path=path,mode="vid_file",group_name=collection_name,stream_name=cam,allow_overlap=True)
    except Exception as exc:
        # Preserve partial status even on cancellation/crash (it was saved before network IO).
        record["upload_error"] = str(exc)
        manifest_save(cfg,collection_name,record)
        raise
    record["status"] = "uploaded"
    manifest_save(cfg,collection_name,record)
    return {"episode_uid":episode_uid,"status":"uploaded","check_report":report,"episode":record}


async def robot_dataset_upload(cfg, collection_name: str, dataset_dir: str, dataset_rev: str,
        frame_map_path: str, telemetry_dir: str, meta_dir: str, format_id: Optional[str] = None,
        episodes: Optional[List[str]] = None, limit: Optional[int] = None, dry_run: bool = False, client=None):
    root = Path(dataset_dir).resolve()
    info = os_json_read(root/"meta"/"info.json")
    if info.get("fps") != 30:
        raise RobotError("LeRobot dataset fps must be 30")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise RobotError("limit must be a positive integer")
    table = [r for p in sorted((root/"meta"/"episodes").rglob("*.parquet")) for r in os_rows_read(p)[1]]
    if not table:
        raise RobotError("LeRobot v3 episode parquet table required")
    _, frames = os_rows_read(frame_map_path)
    metas = {m["episode_uid"]:m for p in Path(meta_dir).glob("*.json") for m in [os_json_read(p)]}
    results = []
    for episode in table:
        mapped = [r for r in frames if r.get("episode_index") == episode["episode_index"]]
        uids = {r.get("episode_uid") for r in mapped}
        if len(uids) != 1 or None in uids:
            raise RobotError(f"episode_index {episode['episode_index']}: frame map must supply one stable episode_uid")
        uid = uids.pop()
        str_robot_key(uid)
        if episodes is not None and uid not in episodes:
            continue
        if limit is not None and len(results) >= limit:
            break
        if uid not in metas:
            raise RobotError(f"missing metadata for {uid}")
        length = episode["length"]
        if type(length) is not int or length < 1 or length != len(mapped):
            raise RobotError(f"episode {uid}: length differs from frame map")
        work = os_robot_root(cfg)/str_robot_key(collection_name)/"clips"/uid
        videos = {}
        for cam in ("cam_scene","cam_wrist"):
            key = f"observation.images.{cam}"
            prefix = f"videos/{key}/"
            if prefix+"from_timestamp" not in episode:
                if cam == "cam_scene":
                    raise RobotError("scene video offsets missing from episode table")
                continue
            template = info.get("video_path", "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4")
            src = root/template.format(video_key=key,chunk_index=episode[prefix+"chunk_index"],file_index=episode[prefix+"file_index"])
            start, end = episode[prefix+"from_timestamp"],episode[prefix+"to_timestamp"]
            if end <= start or abs((end-start)*30-length) > 1.01:
                raise RobotError("video offsets disagree with episode length")
            videos[cam] = os_video_cut(src,work/cam/(uid+".mp4"),start,length)
        tel = next((p for ext in (".jsonl.gz",".jsonl",".json",".parquet") if (p:=Path(telemetry_dir)/(uid+ext)).exists()),None)
        if tel is None:
            raise RobotError(f"missing telemetry for {uid}")
        fmap = os_json_write(work/"frame_map.json",mapped)
        meta = os_json_write(work/"meta.json",{**metas[uid],"length":length})
        out = await robot_episode_upload(cfg,collection_name,uid,videos["cam_scene"],str(tel),fmap,meta,dataset_rev,
            video_wrist=videos.get("cam_wrist"),format_id=format_id,dry_run=dry_run,client=client)
        report = out["check_report"]
        results.append({"episode_uid":uid,"status":out["status"],"verdict":report["verdict"],"first_error":next(iter(report["errors"]),"")})
    return {"episodes":results,**{f"n_{v}":sum(r["verdict"]==v for r in results) for v in ("pass","flag","reject")}}


def robot_manifest_build(cfg, collection_name: str):
    folder = os_robot_root(cfg)/str_robot_key(collection_name)
    rows = {}
    for path in sorted(folder.glob("artifacts/*/*/episode.json"),key=lambda p:p.stat().st_mtime_ns):
        row = os_json_read(path)
        spec = spec_load(cfg,f"{row['format_id']}@{row['format_version']}")
        if str_json_sha(spec) != row["format_sha256"]:
            raise RobotError("stored spec hash mismatch")
        rows[row["episode_uid"]] = row
    folder.mkdir(parents=True,exist_ok=True)
    with FileLock(str(folder/".manifest.lock"),timeout=10):
        os_json_write(folder/"episodes.jsonl",list(rows.values()),lines=True)
    return {"n_episodes":len(rows),"manifest_path":str(folder/"episodes.jsonl")}


def str_frame_ts(index, fps=30):
    return str(int((index/fps)*1000)).zfill(13)


def frame_from_ts(ts, frames, fps=30):
    if type(ts) not in (str,int) or not str(ts).isascii() or not str(ts).isdigit() or len(str(ts)) > 13 or int(ts) >= 10**12:
        raise RobotError("invalid_timestamp: expected millisecond offset, not epoch or t_ns")
    index = round(int(ts)*fps/1000)
    if not 0 <= index < len(frames):
        raise RobotError("no_frame")
    return frames[index]


def frame_from_time(t_ns, frames):
    if type(t_ns) is not int:
        raise RobotError("t_ns must be an int64 integer")
    times = [r["t_scene_ns"] for r in frames]
    pos = bisect.bisect_left(times,t_ns)
    idx = min(range(max(0,pos-1),min(len(times),pos+1)),key=lambda j:abs(times[j]-t_ns))
    if abs(times[idx]-t_ns) > 16_700_000:
        raise RobotError("no_frame")
    return frames[idx]


def telemetry_named(row, spec):
    out = {}
    def flatten(val):
        return [x for item in val for x in flatten(item)] if isinstance(val,list) else [val]
    for field in spec["fields"]:
        name = field["name"]
        if name in row:
            out[name] = dict(zip(field["names"],flatten(row[name]))) if field.get("names") and field["shape"] else row[name]
    return out


def telemetry_summary(rows, spec):
    fields = {f["name"]:f for f in spec["fields"]}
    out = {}
    if not rows:
        return out
    if fields.get("current",{}).get("unit") == "A" and fields["current"].get("names"):
        named = [telemetry_named(r,spec).get("current",{}) for r in rows]
        out["current_abs_max"] = {n:max(abs(r[n]) for r in named if n in r) for n in fields["current"]["names"] if any(n in r for r in named)}
    if fields.get("gripper",{}).get("unit") == "0_open_1_closed":
        vals = [r["gripper"] for r in rows if "gripper" in r]
        if vals:
            out.update(gripper_min=min(vals),gripper_max=max(vals))
        if fields.get("cmd_gripper",{}).get("unit") == "0_open_1_closed":
            out["cmd_vs_state_gripper_max"] = max((abs(r["cmd_gripper"]-r["gripper"]) for r in rows if "cmd_gripper" in r and "gripper" in r),default=0)
    if fields.get("ee_pos",{}).get("unit") == "m" and fields["ee_pos"].get("names"):
        key = spec["time"]["field"]
        out["tcp_speed_max_mps"] = max((math.dist(a["ee_pos"],b["ee_pos"])/((b[key]-a[key])/1e9)
            for a,b in zip(rows,rows[1:]) if "ee_pos" in a and "ee_pos" in b and 0 < b[key]-a[key] <= spec["sampling"]["max_gap_ms"]*1e6),default=0)
    return out


def telemetry_window(rows, spec, start, end, fields=None, rate=None):
    key = spec["time"]["field"]
    selected = [r for r in rows if start <= r[key] < end]
    if fields is not None and set(fields)-{f["name"] for f in spec["fields"]}:
        raise RobotError("unknown telemetry_fields")
    if rate is not None:
        if not math.isfinite(rate) or not 0 < rate <= spec["sampling"]["rate_hz"]:
            raise RobotError("telemetry_rate_hz must be positive and cannot exceed source rate")
        # Nearest existing sample per grid point, independently within continuous segments.
        segments,segment = [],[]
        for row in selected:
            if segment and row[key]-segment[-1][key] > spec["sampling"]["max_gap_ms"]*1e6:
                segments.append(segment)
                segment = []
            segment.append(row)
        if segment:
            segments.append(segment)
        selected = []
        for seg in segments:
            times = [r[key]-seg[0][key] for r in seg]
            count = int(times[-1]*rate/1e9)+1
            if count >= len(seg):
                selected.extend(seg)
                continue
            indices = []
            for i in range(count):
                target = round(i*1e9/rate)
                pos = bisect.bisect_left(times,target)
                near = min(range(max(0,pos-1),min(len(times),pos+1)),key=lambda j:abs(times[j]-target))
                if not indices or near != indices[-1]:
                    indices.append(near)
            selected.extend(seg[i] for i in indices)
    return [{k:v for k,v in r.items() if fields is None or k == key or k in fields} for r in selected]


async def robot_retrieve(cfg, collection_name: str, records: Optional[List[Dict[str,Any]]] = None,
        episode_uid: Optional[str] = None, t_ns: Optional[int] = None, cameras: Optional[List[str]] = None,
        window_before_ms: float = 1000, window_after_ms: float = 1000, telemetry_fields: Optional[List[str]] = None,
        telemetry_rate_hz: Optional[float] = None, image_source: str = "auto", root_folder: Optional[str] = None,
        index_version: Optional[int] = None, image_download=None):
    if image_source not in ("auto","local_decode","vmodal_index"):
        raise RobotError("invalid image_source")
    if any(not math.isfinite(v) or v < 0 for v in (window_before_ms,window_after_ms)):
        raise RobotError("window sizes must be finite and nonnegative")
    cameras = ["cam_scene","cam_wrist"] if cameras is None else cameras
    if not cameras or set(cameras)-{"cam_scene","cam_wrist"}:
        raise RobotError("cameras must select cam_scene/cam_wrist")
    if records is not None:
        if not 1 <= len(records) <= 20 or episode_uid is not None or t_ns is not None:
            raise RobotError("provide 1..20 records OR episode_uid and t_ns")
        inputs = records
    elif episode_uid is not None and t_ns is not None:
        inputs = [{"episode_uid":episode_uid,"t_ns":t_ns}]
    else:
        raise RobotError("provide records OR episode_uid and t_ns")
    manifest = {r["episode_uid"]:r for r in manifest_read(cfg,collection_name)}
    results = []
    for item in inputs:
        raw = dict(item.get("record",item))
        if raw.get("group_name",collection_name) != collection_name:
            raise RobotError("record belongs to another collection")
        version = item.get("index_version",raw.get("version_lancedb",index_version))
        if "ts_unix_13digits" in raw and version is None:
            raise RobotError("pass robot_find hits or index_version for raw VModal records")
        uid = item.get("episode_uid") or Path(raw.get("filename","")).stem
        episode = manifest.get(uid)
        if not episode or episode.get("status") == "partial":
            results.append({"episode_uid":uid,"errors":["episode_not_available"]})
            continue
        if item.get("dataset_rev",episode["dataset_rev"]) != episode["dataset_rev"]:
            raise RobotError("dataset_rev mismatch")
        _,frames = os_rows_read(episode["frame_map_ref"])
        try:
            frame = frame_from_ts(raw["ts_unix_13digits"],frames) if "ts_unix_13digits" in raw else frame_from_time(item["t_ns"],frames)
        except RobotError as exc:
            results.append({"episode_uid":uid,"errors":[str(exc)]})
            continue
        t = frame["t_scene_ns"]
        spec = spec_load(cfg,f"{episode['format_id']}@{episode['format_version']}")
        if str_json_sha(spec) != episode["format_sha256"]:
            raise RobotError("episode format hash mismatch")
        _,rows = os_rows_read(episode["telemetry_ref"])
        key = spec["time"]["field"]
        start,end = t-int(window_before_ms*1e6),t+int(window_after_ms*1e6)
        full_window = telemetry_window(rows,spec,start,end)
        window = telemetry_window(rows,spec,start,end,telemetry_fields,telemetry_rate_hz)
        idx = os_rows_read(episode["frame_index_path"])[1][frame["frame_index"]]
        state = rows[idx["tel_row"]] if idx["tel_row"] is not None and abs(rows[idx["tel_row"]][key]-t) <= 10_000_000 else {}
        state = telemetry_named(state,spec)
        # Commands use the zero-order-hold row, independently of nearest state.
        for field in spec["fields"]:
            if field.get("role") == "command":
                state.pop(field["name"],None)
                if idx["cmd_row"] is not None:
                    cmd = telemetry_named(rows[idx["cmd_row"]],spec)
                    if field["name"] in cmd:
                        state[field["name"]] = cmd[field["name"]]
        result = {"episode_uid":uid,"t_ns":t,**frame,"images":{},"image_source":None,"image_sources":{},
            "telemetry":{"format":{**{k:spec[k] for k in ("format_id","format_version")},"fields":[f for f in spec["fields"] if telemetry_fields is None or f["name"] in telemetry_fields]},
                "t_from_ns":start,"t_to_ns":end,"rate_hz":telemetry_rate_hz or spec["sampling"]["rate_hz"],"rows":window},
            "telemetry_summary":telemetry_summary(full_window,spec),"state_at_t":state,
            "sync":{k:episode.get(k) for k in SYNC_KEYS},"dataset_rev":episode["dataset_rev"],
            "index_version":version,"errors":[]}
        for cam in cameras:
            path = None
            selector = {"mode":"vid_file","group_name":collection_name,"stream_name":cam,"modality":"vid_img",
                        "filename":raw.get("filename") or uid,"ts_unix_13digits":str(int(raw["ts_unix_13digits"])).zfill(13) if "ts_unix_13digits" in raw else str_frame_ts(frame["frame_index"])}
            if image_source != "local_decode" and image_download is not None:
                saved = await image_download([selector],root_folder)
                paths = saved.get("saved_paths",[])
                if paths:
                    path = paths[0]
                    result["image_sources"][cam] = "vmodal_index"
            if not path and image_source != "vmodal_index" and cam in episode["video_paths"] and Path(episode["video_paths"][cam]).is_file():
                dst = Path(root_folder or cfg.image_dir).resolve()/collection_name/cam/f"{uid}_frame{frame['frame_index']}.jpg"
                path = os_video_frame(episode["video_paths"][cam],dst,frame["frame_index"])
                result["image_sources"][cam] = "local_decode"
            if path:
                result["images"][cam] = str(Path(path).resolve())
            else:
                result["errors"].append(f"{cam}: frame_not_found")
        sources = set(result["image_sources"].values())
        result["image_source"] = next(iter(sources)) if len(sources)==1 else "mixed" if sources else None
        # Keep the downloader's selector ownership sidecar intact; use a distinct result sidecar.
        for path in result["images"].values():
            os_json_write(str(Path(path).with_suffix(".json")),result)
        results.append(result)
    return {"results":results,"n_requested":len(inputs)}


def episode_filter(row, filters):
    allowed = {"robot_id","operator_id","task","success","date_from","date_to","sync_offset_ms_max"}
    if set(filters)-allowed:
        raise RobotError("unsupported filters")
    def date(value):
        try:
            dt = datetime.fromisoformat(value.replace("Z","+00:00"))
        except (TypeError,ValueError,AttributeError) as exc:
            raise RobotError("date filters and start_time must be ISO dates/times") from exc
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    for key,value in filters.items():
        if key in ("date_from","date_to"):
            boundary = date(value)
            if not row.get("start_time"):
                return False
            t = date(row["start_time"])
            if key == "date_from" and t < boundary:
                return False
            if key == "date_to" and (t >= boundary+timedelta(days=1) if len(value)==10 else t > boundary):
                return False
        if key == "sync_offset_ms_max" and (row.get(key) is None or row[key] > value):
            return False
        if key not in ("date_from","date_to","sync_offset_ms_max") and row.get(key) != value:
            return False
    return True


def windows_merge(hits, gap_ns=3_000_000_000, max_ns=15_000_000_000):
    out = []
    for hit in sorted(hits,key=lambda r:r["t_start_ns"]):
        a,b = hit["t_start_ns"],hit["t_end_ns"]
        if out and a-out[-1]["t_end_ns"] <= gap_ns and max(b,out[-1]["t_end_ns"])-out[-1]["t_start_ns"] <= max_ns:
            out[-1]["t_end_ns"] = max(b,out[-1]["t_end_ns"])
        else:
            out.append({"t_start_ns":a,"t_end_ns":b})
    return out


async def robot_find(cfg, collection_name: str, query_text: Optional[str] = None, image_path: Optional[str] = None,
        camera: str = "cam_scene", filters: Optional[Dict[str,Any]] = None, limit: int = 50,
        max_pages: int = 10, dataset_rev: Optional[str] = None, find=None):
    if camera not in ("cam_scene","cam_wrist") or type(limit) is not int or not 1 <= limit <= 1000 or type(max_pages) is not int or not 1 <= max_pages <= 1000:
        raise RobotError("invalid camera, limit or max_pages")
    if not query_text and not image_path:
        raise RobotError("query_text or image_path required")
    manifest = {r["episode_uid"]:r for r in manifest_read(cfg,collection_name) if r.get("status") != "partial"}
    episode_filter({},filters or {})
    query_id = uuid.uuid4().hex
    hits,scanned,unmapped,total,version = [],0,0,0,None
    maps = {}
    for page in range(max_pages):
        args = {"collection_name":collection_name,"sub_collection_name":camera,"limit":limit,"offset":scanned,"query_text":query_text or "","image_path":image_path or ""}
        if version is not None:
            args["version_id"] = version
        payload = await find(**args)
        current = payload.get("version_lancedb")
        if current is None or (version is not None and current != version):
            raise RobotError("missing or changed index version during pagination",409)
        version = current
        data = payload.get("data",[])
        total = payload.get("n_total",len(data))
        for raw in data:
            scanned += 1
            uid = Path(raw.get("filename","")).stem
            episode = manifest.get(uid)
            if not episode:
                unmapped += 1
                continue
            if dataset_rev and dataset_rev != episode["dataset_rev"] or not episode_filter(episode,filters or {}):
                continue
            if uid not in maps:
                maps[uid] = os_rows_read(episode["frame_map_ref"])[1]
            frame = frame_from_ts(raw["ts_unix_13digits"],maps[uid])
            t = frame["t_scene_ns"]
            hits.append({"query_id":query_id,"episode_uid":uid,"t_start_ns":t-500_000_000,"t_end_ns":t+500_000_000,
                "t_ns":t,"frame_index":frame["frame_index"],"relevance":raw.get("score"),"modality":raw.get("modality"),
                "index_version":version,"dataset_rev":episode["dataset_rev"],"camera":camera,"record":raw})
        if not data or scanned >= total:
            break
    episodes = []
    for uid in dict.fromkeys(h["episode_uid"] for h in hits):
        group = [h for h in hits if h["episode_uid"] == uid]
        episodes.append({"episode_uid":uid,"dataset_rev":manifest[uid]["dataset_rev"],"index_version":version,
            "best_relevance":max((h["relevance"] for h in group if h["relevance"] is not None),default=None),
            "hit_count":len(group),"windows":windows_merge(group)})
    return {"query_id":query_id,"data":hits,"episodes":episodes,"n_scanned":scanned,"n_total":total,
            "n_kept":len(hits),"n_unmapped":unmapped,"index_version":version,"page_cap_reached":scanned < total}
