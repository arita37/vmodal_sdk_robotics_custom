from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
import base64
import io
import json
import re
import gzip
import hashlib
import subprocess
import tempfile
from pathlib import Path
from PIL import Image
from src.utils.util_log import log_info, log_error, log_trace, log_warning


def str_frame_component(value: Any) -> str:
    text = re.sub(r"[^\w.-]", "_", str(value or "").strip()).strip("._")
    if not text:
        raise ValueError("empty_path_component")
    return text


def os_frame_path(root: str, row: Dict[str, Any]) -> str:
    root = Path(root).expanduser().resolve()
    ts = str(row.get("ts_unix_13digits") or "")
    if not re.fullmatch(r"[0-9]{13}", ts):
        raise ValueError("invalid_timestamp")
    filename = str(row.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = str_frame_component(os.path.splitext(filename)[0])
    path = root / str_frame_component(row.get("group_name")) / str_frame_component(row.get("stream_name")) / f"{stem}_{ts}.jpg"
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("path_outside_root")
    return str(path)


def image_bytes(payload: Any) -> bytes:
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    data = obj_dict(payload)
    return base64.b64decode(data.get("img_base64") or data.get("content_base64") or "", validate=True)


def image_validate(raw: bytes) -> None:
    if not raw:
        raise ValueError("empty_image")
    with Image.open(io.BytesIO(raw)) as img:
        img.load()


def os_read_image(path: str) -> bytes:
    with open(os.path.expanduser(path), "rb") as fh:
        return fh.read()


def os_save_frame(payload: Any, path: str, record: Dict[str, Any]) -> Dict[str, Any]:
    raw = image_bytes(payload)
    with Image.open(io.BytesIO(raw)) as img:
        img.load()
        if img.format == "JPEG" and img.mode == "RGB":
            jpeg = raw
        else:
            rgb = Image.new("RGB", img.size, "white")
            rgba = img.convert("RGBA")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG")
            jpeg = buf.getvalue()
    if not jpeg.startswith(b"\xff\xd8\xff"):
        raise ValueError("invalid_jpeg")
    # Exclusive creation also prevents overwriting a frame saved in an earlier call.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # A sidecar distinguishes selectors that sanitize to the same deterministic name.
    owner_path = path + ".json"
    try:
        with open(owner_path, "x", encoding="utf-8") as fh:
            json.dump(record, fh, sort_keys=True)
    except FileExistsError:
        with open(owner_path, encoding="utf-8") as fh:
            if json.load(fh) != record:
                raise ValueError("path_conflict")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            if fh.read() != jpeg:
                raise ValueError("path_conflict")
    else:
        try:
            with open(path, "xb") as fh:
                fh.write(jpeg)
        except FileExistsError:
            with open(path, "rb") as fh:
                if fh.read() != jpeg:
                    raise ValueError("path_conflict")
    return {"saved_path": path, "n_bytes": len(jpeg)}


def obj_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return dict(value) if isinstance(value, dict) else {}


def int_version_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("v"):
        text = text[1:]
    if not text.isascii() or not text.isdigit():
        raise ValueError("version must be a non-negative integer or vN")
    return int(text)


def list_versions(group: Dict[str, Any]) -> List[int]:
    out = set()
    for value in group.get("lancedb_versions") or []:
        try:
            version = int_version_id(value)
        except ValueError:
            continue
        if version is not None:
            out.add(version)
    return sorted(out, reverse=True)


def md_table(rows: List[Dict[str, Any]], columns: Dict[str, str]) -> str:
    def str_cell(value):
        if isinstance(value, list):
            value = ", ".join(str(x) for x in value)
        return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = ["| " + " | ".join(columns.values()) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(str_cell(row.get(key)) for key in columns) + " |" for row in rows)
    return "\n".join(lines)


def collection_listing(resp: Any, subcollections: bool = False, collection_name: str = "", mode: Optional[str] = None) -> Dict[str, Any]:
    payload = obj_dict(resp)
    source = payload.get("rows", payload.get("data", [])) if subcollections else payload.get("data", [])
    rows = {}
    for raw in source or []:
        item = obj_dict(raw)
        group = str(item.get("group_name") or "").strip()
        item_mode = str(item.get("mode") or "").strip()
        stream = str(item.get("stream_name") or "").strip()
        if not group or (collection_name and group != collection_name) or (mode and item_mode != mode):
            continue
        if subcollections and not stream:
            continue
        row = {"collection_name": group, "mode": item_mode}
        if subcollections:
            row["sub_collection_name"] = stream
        else:
            row["lancedb_versions"] = [f"v{x}" for x in list_versions(item)]
        rows[(item_mode, group, stream if subcollections else "")] = row
    data = [rows[key] for key in sorted(rows)]
    columns = {"collection_name": "Collection"}
    if subcollections:
        columns["sub_collection_name"] = "Sub-collection"
    columns["mode"] = "Mode"
    if not subcollections:
        columns["lancedb_versions"] = "Index versions"
    return {"data": data, "total": len(data), "table": md_table(data, columns)}


def bool_missing_index(exc: Any) -> bool:
    text = str(exc.details or exc.body or exc).lower()
    index = any(x in text for x in ("lancedb", "image index", "img_emb"))
    missing = any(x in text for x in ("missing", "not found", "does not exist", "no such file", "no tablename resolved", "unable to resolve query embedding model"))
    return exc.status_code in (404, 500) and index and missing


class RobotError(ValueError):
    def __init__(self, detail, status_code=422):
        super().__init__(str(detail))
        self.status_code = status_code


def str_robot_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]+", value) or "__" in value:
        raise RobotError("key must contain letters, digits, single underscores only")
    return value


def os_robot_root(cfg):
    return Path(cfg.robot_dir).expanduser().resolve()


def os_json_read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def os_json_write(path, data, lines=False):
    """Atomically replace JSON/JSONL, preserving nanosecond integers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    os.close(fd)
    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(tmp, "wt", encoding="utf-8") as fh:
            if lines:
                for row in data:
                    fh.write(json.dumps(row, allow_nan=False) + "\n")
            else:
                json.dump(data, fh, indent=2, sort_keys=True, allow_nan=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(path.resolve())


def os_rows_read(path):
    """Read Arrow directly: pandas nullable floats would lose int64 timestamps."""
    path = Path(path)
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq
        return {}, pq.read_table(path).to_pylist()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        if path.suffix == ".json":
            data = json.load(fh)
            return ({}, data) if isinstance(data, list) else (data.get("header", {}), data["rows"])
        data = [json.loads(line) for line in fh if line.strip()]
    header = {}
    header_keys = {"format_id", "format_version", "format_sha256", "episode_uid", "time_base", "rate_hz"}
    if data and (any(k in data[0] for k in ("schema", "fields"))
                 or ("format_id" in data[0] and set(data[0]) <= header_keys)):
        header = data.pop(0)
    return header, data


def str_json_sha(data):
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def os_file_sha(path):
    sha = hashlib.sha256()
    with open(path,"rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):
            sha.update(chunk)
    return sha.hexdigest()


def os_video_probe(path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
           "-show_entries", "stream=avg_frame_rate,r_frame_rate,nb_read_frames:frame=best_effort_timestamp_time",
           "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)
    stream = data["streams"][0]
    pts = [float(row["best_effort_timestamp_time"]) for row in data.get("frames", [])]
    cfr = (stream["avg_frame_rate"] == "30/1" and stream["r_frame_rate"] == "30/1"
           and len(pts) == int(stream["nb_read_frames"])
           and all(abs(b - a - 1 / 30) < 0.00001 for a, b in zip(pts, pts[1:])))
    return {"n_frames_decoded": int(stream["nb_read_frames"]), "fps": 30.0 if cfr else stream["avg_frame_rate"], "cfr": cfr}


def os_video_cut(src, dst, start, length):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ss", str(start),
                    "-frames:v", str(length), "-an", "-vf", "fps=30,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)], check=True)
    return str(Path(dst).resolve())


def os_video_frame(src, dst, index):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                    f"select=eq(n\\,{index})", "-frames:v", "1", str(dst)], check=True)
    if not Path(dst).is_file():
        raise RobotError("local frame not found")
    return str(Path(dst).resolve())
