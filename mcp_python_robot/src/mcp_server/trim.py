from typing import Any, Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
import os,sys
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from vmodal.models import SearchResponse_frontui, IndexationJobsListResponse
from src.mcp_server.utils import obj_dict as _item_dict


def _text_snippet(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw)
    return text[:200]


def _first_value(item: Dict[str, Any], keys: List[str], default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return default


def _str_filename(item: Dict[str, Any]) -> str:
    value = _first_value(
        item,
        ["filename", "file_name", "filename_sanitized", "video_filename", "source_asset_file"],
    )
    return str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]


def _str_timestamp(item: Dict[str, Any]) -> str:
    value = _first_value(item, ["ts_unix_13digits", "ts_unix", "timestamp_ms"])
    text = str(value).strip() if value is not None else ""
    if not item.get("ts_unix_13digits") and text.isascii() and text.isdigit() and len(text) <= 13:
        return text.zfill(13)
    return text


def str_frame_error(row: Dict[str, Any]) -> str:
    for key, label in [("mode", "mode"), ("group_name", "collection"), ("stream_name", "stream"),
                       ("modality", "modality"), ("filename", "filename")]:
        if not str(row.get(key) or "").strip():
            return f"missing_{label}"
    ts = str(row.get("ts_unix_13digits") or "")
    if len(ts) != 13 or not ts.isascii() or not ts.isdigit():
        return "invalid_timestamp"
    return ""


def _search_row(item: Dict[str, Any], context: Dict[str, Any], verbose: bool) -> Dict[str, Any]:
    raw_modality = str(item.get("modality") or "").strip()
    req_stream = str(context.get("stream_name") or "").strip()
    stream = _first_value(item, ["stream_name", "stream"], req_stream)
    filename = _str_filename(item)
    ts = _str_timestamp(item)
    source_path = _first_value(item, ["source_path", "source_asset_file", "path"],
                               _first_value(item, ["filename", "file_name", "filename_sanitized", "video_filename"], filename))
    text = _first_value(item, ["text_snippet", "text", "snippet", "text_agg_tok"])
    mode = _first_value(item, ["mode"], context.get("mode", ""))
    modality = "vid_img" if str(mode).startswith("vid_") else (raw_modality or "img_raw")
    legacy_ts = item.get("ts_unix")
    if legacy_ts is None or (isinstance(legacy_ts, str) and not legacy_ts.strip()):
        legacy_ts = ts
    row = dict(item) if verbose else {}
    if verbose and raw_modality and raw_modality != modality:
        row["search_modality"] = raw_modality
    row.update(
        {
            "score": item.get("score"),
            "mode": mode,
            "group_name": _first_value(item, ["group_name"], context.get("group_name", "")),
            "stream_name": stream,
            "modality": modality,
            "filename": filename,
            "source_path": source_path,
            "ts_unix_13digits": ts,
            "ts_unix": legacy_ts,
            "text_snippet": str(text or "") if verbose else _text_snippet(text),
        }
    )
    row["frame_error"] = str_frame_error(row)
    row["frame_fetchable"] = not row["frame_error"]
    return row


def normalize_image_records(records: Any) -> List[Dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError({"record_index": None, "missing_fields": ["records"]})
    out = []
    required = ["mode", "group_name", "stream_name", "modality", "filename"]
    for idx, raw in enumerate(records):
        item = _item_dict(raw)
        modality = str(item.get("modality") or "").strip()
        if modality in {"img_emb", "vid_img_emb"}:
            modality = "vid_img"
        row = {
            "mode": str(item.get("mode") or "").strip(),
            "group_name": str(item.get("group_name") or "").strip(),
            "stream_name": str(_first_value(item, ["stream_name", "stream"])).strip(),
            "modality": modality,
            "filename": _str_filename(item),
        }
        ts = _str_timestamp(item)
        if ts:
            row["ts_unix_13digits"] = ts
        missing = [key for key in required if not str(row.get(key) or "").strip()]
        if modality == "vid_img" and (len(ts) != 13 or not ts.isascii() or not ts.isdigit()):
            missing.append("ts_unix_13digits")
        if missing:
            raise ValueError({"record_index": idx, "missing_fields": missing})
        out.append(row)
    return out


def trim_search(
    resp: SearchResponse_frontui,
    verbose: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = context or {}
    source = []
    if hasattr(resp, "data"):
        source = getattr(resp, "data") or []
    elif isinstance(resp, dict):
        source = resp.get("data") or []
    if not isinstance(source, list):
        source = []
    limit = int(context.get("limit", 20))
    rows = []
    for item in source[:limit]:
        rows.append(_search_row(_item_dict(item), context, verbose))
    payload = {
        "n_total": int((resp.get("cnt_total", len(source)) if isinstance(resp, dict) else getattr(resp, "cnt_total", len(source))) or 0),
        "execution_time_ms": resp.get("execution_time_ms", 0) if isinstance(resp, dict) else getattr(resp, "execution_time_ms", 0),
        "data": rows,
        "trimmed": not verbose,
        "n_total_returned": len(rows),
        "requested_limit": limit,
        "offset": int(context.get("offset") or 0),
    }
    if "version_lancedb" in context:
        payload["version_lancedb"] = context["version_lancedb"]
        payload["available_versions"] = context.get("available_versions", [])
    return payload


def trim_jobs(resp: IndexationJobsListResponse) -> Dict[str, Any]:
    source = []
    if hasattr(resp, "data"):
        source = getattr(resp, "data") or []
    if not isinstance(source, list):
        source = []
    rows = []
    for item in source:
        if hasattr(item, "model_dump"):
            item = item.model_dump(exclude_none=True)
        if not isinstance(item, dict):
            item = {}
        rows.append(
            {
                "job_id": item.get("job_id", ""),
                "status": item.get("status", ""),
                "mode": item.get("mode", ""),
                "created_at": item.get("created_at"),
                "progress": item.get("progress"),
            }
        )
    return {"data": rows, "total": int(getattr(resp, "total", len(rows)) or 0)}
