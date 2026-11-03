from typing import Any, Dict, Optional, Literal, Annotated
import os
import sys
import base64
import json
import fire
import inspect
import asyncio
from contextlib import asynccontextmanager

os.environ.setdefault("VMODAL_AUTH_CACHE_DIR", "ztmp/vmodal_auth")

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from vmodal import Client
from vmodal.errors import SdkError, AuthError, ApiError, ValidationFailed
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.mcp_server.registry import TOOL_REGISTRY, tool_schema
from src.mcp_server.trim import normalize_image_records, str_frame_error
from src.mcp_server.config import McpConfig
from src.mcp_server.utils import obj_dict as _coerce_dict, int_version_id, list_versions, collection_listing, bool_missing_index
from src.mcp_server.utils import os_frame_path, os_save_frame, os_read_image, image_validate
from src.mcp_server.utils import RobotError

_ACTIVE_CFG: Optional[McpConfig] = None
_ACTIVE_CLIENT: Optional[Client] = None
_TARGET_CACHE: Dict[str, Any] = {}

def _json_type_to_py(py_prop: Dict[str, Any]) -> Any:
    if "anyOf" in py_prop:
        non_null = [x for x in py_prop["anyOf"] if (x or {}).get("type") != "null"]
        if len(non_null) == 1:
            ann = _json_type_to_py(non_null[0])
            return Optional[ann] if len(non_null) < len(py_prop["anyOf"]) else ann
    ptype = py_prop.get("type")
    if isinstance(ptype, list):
        non_null = [x for x in ptype if x != "null"]
        if len(non_null) == 1:
            ann = _json_type_to_py({"type": non_null[0]})
            return Optional[ann] if "null" in ptype else ann
    if ptype == "string":
        return str
    if ptype == "integer":
        return int
    if ptype == "number":
        return float
    if ptype == "boolean":
        return bool
    if ptype == "array":
        values = (py_prop.get("items") or {}).get("enum")
        if values:
            return list[Literal[tuple(values)]]
        return list[Any]
    if ptype == "object":
        return dict
    return Any


def _build_signature(schema: Dict[str, Any]) -> inspect.Signature:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []) or [])
    req_params = []
    opt_params = []
    for key, value in properties.items():
        ann = _json_type_to_py(value if isinstance(value, dict) else {})
        bounds = {new: value[old] for old, new in [("minLength", "min_length"), ("minimum", "ge"),
                  ("maximum", "le"), ("description", "description")]
                  if old in value}
        # Publish batch bounds while retaining the handler's JSON 422 error contract.
        batch_bounds = {key: value[key] for key in ["minItems", "maxItems"] if key in value}
        if batch_bounds:
            bounds["json_schema_extra"] = batch_bounds
        if bounds:
            ann = Annotated[ann, Field(**bounds)]
        if key in required:
            default = inspect.Parameter.empty
        else:
            default = value.get("default") if isinstance(value, dict) else inspect.Parameter.empty
        param = inspect.Parameter(
            name=key,
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=ann,
            default=default,
        )
        if key in required:
            req_params.append(param)
        else:
            opt_params.append(param)
    return inspect.Signature(req_params + opt_params)

def _os_dir_cap(dirpath: str, max_files: int = 500):
    if not dirpath or not os.path.isdir(dirpath):
        return
    files = [os.path.join(dirpath, f) for f in os.listdir(dirpath)]
    files = [f for f in files if os.path.isfile(f)]
    if len(files) <= max_files:
        return
    files.sort(key=lambda f: os.path.getmtime(f))  # oldest first
    for f in files[: len(files) - max_files]:
        try:
            os.remove(f)
        except Exception:
            pass


def _str_tool_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, AuthError):
        detail = getattr(exc, "details", None) or getattr(exc, "body", None) or str(exc)
        return {
            "error_type": "AuthError",
            "status_code": int(getattr(exc, "status_code", 401) or 401),
            "detail": detail or "Bearer token required",
        }
    if isinstance(exc, ValidationFailed):
        return {
            "error_type": "ValidationFailed",
            "status_code": int(getattr(exc, "status_code", 422) or 422),
            "detail": getattr(exc, "details", None) or str(exc),
        }
    if isinstance(exc, ApiError):
        return {
            "error_type": "ApiError",
            "status_code": int(getattr(exc, "status_code", 500) or 500),
            "detail": getattr(exc, "details", None) or str(exc),
        }
    if isinstance(exc, Exception):
        return {
            "error_type": exc.__class__.__name__,
            "status_code": 500,
            "detail": str(exc),
        }
    return {"error_type": "Error", "status_code": 500, "detail": str(exc)}


@asynccontextmanager
async def _lifespan(server: FastMCP):
    config = _ACTIVE_CFG
    if not isinstance(config, McpConfig):
        config = McpConfig.from_env()
    max_files = int(str(os.environ.get("MCP_IMAGE_MAX_FILES") or "500") or 500)
    _os_dir_cap(config.image_dir, max_files=max_files)
    client = Client(cfg=config.sdk)
    global _ACTIVE_CLIENT
    _ACTIVE_CLIENT = client
    _TARGET_CACHE.clear()  # fresh client → drop stale bound methods
    try:
        # async with already closes the client on exit
        async with client:
            yield
    finally:
        _ACTIVE_CLIENT = None
        _TARGET_CACHE.clear()


def _resolve_target(client: Client, target: str):
    cached = _TARGET_CACHE.get(target)
    if cached is not None:
        return cached
    method_fix = {
        "description_update": "update_description",
    }
    obj = client
    for part in target.split("."):
        method = getattr(obj, part, None)
        if method is None and part in method_fix:
            method = getattr(obj, method_fix[part], None)
        if method is None:
            raise RuntimeError(f"tool target not found: {target}")
        obj = method
    _TARGET_CACHE[target] = obj
    return obj


def _tool_payload(payload: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if len(payload) == 1:
        key = next(iter(payload.keys()))
        if key not in schema.get("properties", {}):
            wrapped = payload[key]
            if isinstance(wrapped, dict):
                return wrapped
    return payload


async def _tool_output(
    resp: Any,
    spec: Dict[str, Any],
    *,
    verbose: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    if spec.get("trim"):
        if spec.get("target") == "searches.search_video":
            resp = spec["trim"](resp, verbose=verbose, context=context)
        else:
            resp = spec["trim"](resp)
    if hasattr(resp, "model_dump"):
        payload = resp.model_dump(exclude_none=True)
    elif isinstance(resp, (dict, list, str, int, float, bool)) or resp is None:
        payload = resp
    else:
        payload = {"result": str(resp)}
    return json.dumps(payload, ensure_ascii=False)


def _ensure_client() -> Client:
    if _ACTIVE_CLIENT is None:
        raise RuntimeError("mcp server lifecycle not initialized")
    return _ACTIVE_CLIENT


def _tool_error(error: SdkError) -> str:
    return json.dumps(_str_tool_error(error))


def _validation_error(detail: Any) -> RuntimeError:
    return RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": detail}))


def _apply_call_contract(data: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(data)
    for key, value in (spec.get("call_defaults") or {}).items():
        if key not in data or (data.get(key) is None and key in (spec.get("call_defaults_null") or [])):
            data[key] = value
    missing = [key for key in spec.get("required_nonempty") or [] if not str(data.get(key) or "").strip()]
    if missing:
        raise _validation_error({"missing_fields": missing})
    transform = spec.get("input_transform")
    if transform:
        key = spec.get("input_transform_key") or "records"
        try:
            data[key] = transform(data.get(key))
        except ValueError as exc:
            detail = exc.args[0] if exc.args else str(exc)
            raise _validation_error(detail)
    return data


def _str_search_error(exc: SdkError, context: Optional[Dict[str, Any]] = None) -> str:
    payload = _str_tool_error(exc)
    detail = payload.get("detail")
    text = str(detail or "").lower()
    if any(key in text for key in ["img_emb", "image index", "lancedb", "table", "version"]):
        hint = "Call collection_list() to inspect available versions. Ensure this collection has a usable image index; an explicit version stays pinned."
        payload["detail"] = f"{detail} {hint}" if detail else hint
        payload.update({key: (context or {}).get(key, []) for key in ["available_versions", "attempted_versions"]})
    return json.dumps(payload)


async def _search_video(client: Client, data: Dict[str, Any], context: Dict[str, Any]):
    """Select advertised revisions, retrying only missing-index failures."""
    groups = [_coerce_dict(row) for row in _coerce_dict(await client.collections.list_groups(mode=data.get("mode"))).get("data", [])]
    matches = [row for row in groups if row.get("group_name") == data["group_name"]
               and (not data.get("mode") or row.get("mode") == data["mode"])]
    if len(matches) != 1:
        raise _validation_error({
            "message": "Collection not found" if not matches else "Collection exists in multiple modes; specify mode",
            "collection_name": data["group_name"],
            "available_modes": sorted({row["mode"] for row in matches}),
            "hint": "Call collection_list() for available collections and modes.",
        })
    group = matches[0]
    data["mode"] = group["mode"]
    try:
        pinned = int_version_id(data.get("version_lancedb"))
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc
    versions = list_versions(group)
    if pinned is not None and versions and pinned not in versions:
        raise _validation_error({"message": "Index version is not available for this collection", "version_lancedb": pinned, "available_versions": versions})
    candidates = [pinned] if pinned is not None else (versions or [None])
    context["available_versions"] = versions
    context["attempted_versions"] = []
    for idx, version in enumerate(candidates):
        context["attempted_versions"].append(version)
        data["version_lancedb"] = version
        context.update({key: data.get(key) for key in ["mode", "group_name", "stream_name", "version_lancedb"]})
        try:
            return await client.searches.search_video(**data)
        except ApiError as exc:
            if pinned is not None or idx == len(candidates) - 1 or not bool_missing_index(exc):
                raise
            log_warning("search_missing_index", data["group_name"], version)


async def _find_save_images(client: Client, payload: Dict[str, Any], n_save: int, cfg: McpConfig) -> Dict[str, Any]:
    rows = payload["data"][:n_save]
    saved = await _image_download_records(client, rows, cfg, allow_empty=True)
    payload.update(saved)
    for row, result in zip(rows, saved["results"]):
        if result["saved_path"]:
            row["saved_path"] = result["saved_path"]
    return payload


async def _find_image_input(client: Client, data: Dict[str, Any]) -> None:
    text = str(data.get("query_text") or "").strip()
    sources = [key for key in ("image_query", "image_path", "image_url") if data.get(key)]
    if len(sources) > 1 or (not text and not sources):
        raise _validation_error("Provide nonblank query_text or one image source; at most one image source is allowed")
    data["query_text"] = text
    path = data.pop("image_path", "")
    url = data.pop("image_url", "")
    query = data.pop("image_query", "")
    if not sources:
        return
    try:
        if path:
            raw = await asyncio.to_thread(os_read_image, path)
        elif url:
            # The SDK endpoint validates VMX signatures and preserves expired-URL errors.
            raw = await client.images.get_image_from_url(url_pre_signed=url)
        else:
            raw = base64.b64decode(query, validate=True)
        await asyncio.to_thread(image_validate, raw)
    except (ValueError, OSError) as exc:
        raise _validation_error("Empty, unreadable, or malformed image input") from exc
    data["image_query"] = base64.b64encode(raw).decode("ascii")


def _image_batch(records: Any, allow_empty: bool = False) -> None:
    if not isinstance(records, list) or len(records) > 20 or (not records and not allow_empty):
        raise _validation_error("records must contain 1 to 20 search result objects")


def _str_image_error(exc: SdkError, urls: Any = None) -> Dict[str, Any]:
    text = json.dumps(_str_tool_error(exc))
    for url in urls or []:
        if url:
            text = text.replace(json.dumps(url)[1:-1], "<signed image URL>")
    return json.loads(text)


async def _image_download_records(client: Client, records: Any, cfg: McpConfig,
                                  root_folder: Optional[str] = None, urls: Any = None,
                                  allow_empty: bool = False) -> Dict[str, Any]:
    """Validate each frame, sign valid selectors, and retain every input position."""
    _image_batch(records, allow_empty)
    if urls is not None and (not isinstance(urls, list) or len(urls) != len(records)
                             or any(not isinstance(url, str) or not url.strip() for url in urls)):
        raise _validation_error("urls and records must be nonempty and aligned one to one")
    root = os.path.realpath(os.path.expanduser(root_folder or cfg.image_dir))
    results = [{"input_index": i, "found": False, "saved_path": "", "error": ""} for i in range(len(records))]
    valid, positions, paths = [], [], []
    owners = {}
    for i, raw in enumerate(records):
        try:
            row = normalize_image_records([raw])[0]
            error = str_frame_error(row)
            if error:
                raise ValueError(error)
            path = os_frame_path(root, row)
            if path in owners and owners[path] != row:
                raise ValueError("path_conflict")
            owners[path] = row
            valid.append(row)
            positions.append(i)
            paths.append(path)
        except ValueError as exc:
            detail = exc.args[0]
            if isinstance(detail, dict):
                field = detail["missing_fields"][0]
                detail = {"filename": "missing_filename", "stream_name": "missing_stream",
                          "ts_unix_13digits": "invalid_timestamp"}.get(field, f"missing_{field}")
            results[i]["error"] = str(detail)
    found = {}
    if valid:
        try:
            if urls is None:
                reply = await asyncio.wait_for(client.images.get_url_bulk(records=valid), timeout=cfg.tool_timeout)
                for item in _coerce_dict(reply).get("records") or []:
                    item = _coerce_dict(item)
                    index = item.get("input_index")
                    if type(index) is int and 0 <= index < len(valid):
                        if index in found:
                            found[index] = {"error": "duplicate_input_index"}
                        else:
                            found[index] = item
            else:
                found = {j: {"found": True, "url_pre_signed": urls[i]} for j, i in enumerate(positions)}
        except (SdkError, asyncio.TimeoutError) as exc:
            error = _str_image_error(exc, urls) if isinstance(exc, SdkError) else "timeout"
            for i in positions:
                results[i]["error"] = error
    for j, i in enumerate(positions):
        if results[i]["error"]:
            continue
        item = found.get(j, {})
        url = item.get("url_pre_signed")
        if not item.get("found") or not url:
            results[i]["error"] = "duplicate_input_index" if item.get("error") == "duplicate_input_index" else "frame_not_found"
            continue
        try:
            raw = await asyncio.wait_for(client.images.get_image_from_url(url_pre_signed=url), timeout=cfg.tool_timeout)
            saved = await asyncio.to_thread(os_save_frame, raw, paths[j], valid[j])
            results[i].update(found=True, saved_path=saved["saved_path"])
        except SdkError as exc:
            results[i]["error"] = _str_image_error(exc, [url])
        except asyncio.TimeoutError:
            results[i]["error"] = "timeout"
        except (ValueError, OSError) as exc:
            results[i]["error"] = str(exc) if str(exc) == "path_conflict" else "image_conversion_or_write_failed"
    saved_paths = [item["saved_path"] for item in results if item["saved_path"]]
    return {"results": results, "saved_paths": saved_paths, "n_requested": len(records),
            "n_saved": len(saved_paths), "n_failed": len(records) - len(saved_paths), "output_dir": root}


def _check_upload_path(path: str, cfg: McpConfig) -> str:
    if not str(path or "").strip():
        raise RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": "missing file_path"}))
    file_path = str(path).strip()
    if not os.path.isfile(file_path):
        raise RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": f"missing file: {file_path}"}))
    max_bytes = int(cfg.upload_max_mb) * 1024 * 1024
    if os.path.getsize(file_path) > max_bytes:
        raise RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": f"file too large: > {cfg.upload_max_mb}MB"}))
    return file_path


def _check_upload_folder(path: str) -> str:
    if not str(path or "").strip():
        raise RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": "missing folder_path"}))
    folder_path = str(path).strip()
    if not os.path.isdir(folder_path):
        raise RuntimeError(json.dumps({"error_type": "ValidationError", "status_code": 422, "detail": f"missing folder: {folder_path}"}))
    return folder_path


def _build_handler(name: str, spec: Dict[str, Any]):
    target = spec["target"]
    schema = tool_schema(spec)
    if target == "searches.search_video":
        if "verbose" not in schema.get("properties", {}):
            schema = dict(schema)
            props = dict(schema.get("properties", {}))
            props["verbose"] = {"type": "boolean", "title": "Verbose", "default": False}
            schema["properties"] = props
    handler_name = spec.get("handler") or name

    async def _handler(**payload):
        log_trace("tool", name)
        cfg = _ACTIVE_CFG
        if not isinstance(cfg, McpConfig):
            raise RuntimeError("mcp server lifecycle not initialized")
        if cfg and cfg.cfg_error and not spec.get("robot_func"):
            raise RuntimeError(json.dumps({"error_type": "AuthError", "status_code": 401, "detail": cfg.cfg_error}))
        data = _tool_payload(payload, schema)
        data = _apply_call_contract(data, spec)
        if spec.get("robot_func"):
            try:
                func = spec["robot_func"]
                if name in ("robot_episode_upload", "robot_dataset_upload") and not data.get("dry_run", False):
                    if cfg.cfg_error:
                        raise RuntimeError(json.dumps({"status_code":401,"detail":cfg.cfg_error}))
                    data["client"] = _ensure_client()
                if name == "robot_find":
                    async def find(**args):
                        text = await _build_handler("find", TOOL_REGISTRY["find"])(**args)
                        return json.loads(text)
                    data["find"] = find
                if name == "robot_retrieve":
                    async def download(records, root):
                        if cfg.cfg_error:
                            return {"saved_paths": []}
                        return await _image_download_records(_ensure_client(), records, cfg, root)
                    data["image_download"] = download
                if inspect.iscoroutinefunction(func):
                    out = await func(cfg, **data)
                else:
                    out = await asyncio.to_thread(func, cfg, **data)
                return json.dumps(out, ensure_ascii=False, allow_nan=False)
            except RobotError as exc:
                raise RuntimeError(json.dumps({"error_type":"ValidationError","status_code":exc.status_code,"detail":str(exc)})) from exc
            except SdkError as exc:
                raise RuntimeError(_tool_error(exc)) from exc
        if spec.get("is_upload"):
            key = spec.get("upload_path_key") or "path"
            file_path = _check_upload_path(data.get(key, ""), cfg)
            data[key] = file_path
        if spec.get("is_upload_folder"):
            key = spec.get("upload_folder_key") or "folderpath_local"
            data[key] = _check_upload_folder(data.get(key, ""))
        verbose = False
        context = None
        n_save = 0
        if handler_name == "find":
            n_save = int(data.pop("save_images", 0) or 0)
            if not 0 <= n_save <= 20:
                raise _validation_error("save_images must be between 0 and 20")
            data["group_name"] = str(data.pop("collection_name")).strip()
            data["stream_name"] = str(data.pop("sub_collection_name", "") or "").strip()
            data["version_lancedb"] = data.pop("version_id", None)
            data.setdefault("limit", 20)
            data["search_sources"] = ["image"]
        if target == "searches.search_video":
            verbose = bool(data.pop("verbose", False))
            data["group_name"] = str(data["group_name"]).strip()
            data["stream_name"] = str(data.get("stream_name") or "").strip()
            data.setdefault("offset", 0)
            if type(data.get("limit")) is not int or data["limit"] < 1 or type(data["offset"]) is not int or data["offset"] < 0:
                raise _validation_error("limit must be positive and offset must be nonnegative integers")
            context = {key: data.get(key) for key in ["mode", "group_name", "stream_name", "search_sources", "version_lancedb", "limit", "offset"]}
        if handler_name == "subcollections_list":
            context = {"collection_name": str(data.pop("collection_name", "") or "").strip(), "mode": data.pop("mode", None)}
        client = _ensure_client()
        try:
            if handler_name in {"image_records", "image_bytes", "image_bulk"}:
                records = [data.get("record")] if handler_name == "image_bytes" else data.get("records")
                if handler_name == "image_bytes" and not isinstance(data.get("record"), dict):
                    raise _validation_error("record metadata is required alongside url_pre_signed")
                urls = [data.get("url_pre_signed")] if handler_name == "image_bytes" else data.get("urls")
                if handler_name == "image_bulk" and urls is None:
                    raise _validation_error("urls and aligned records are required")
                out = await _image_download_records(client, records, cfg, data.get("root_folder"), urls)
                return json.dumps(out, ensure_ascii=False)
            call = _resolve_target(client, target)
            if spec.get("long_running"):
                # SDK upload parts already have bounded timeouts and retry/resume.
                # An outer timeout would cancel a healthy large-file transfer.
                out = await call(**data)
            else:
                async def search_task():
                    if handler_name == "find":
                        await _find_image_input(client, data)
                    return await _search_video(client, data, context)
                task = search_task() if target == "searches.search_video" else call(**data)
                out = await asyncio.wait_for(task, timeout=cfg.tool_timeout)
        except asyncio.TimeoutError:
            log_error("tool_fail", name, "timeout")
            raise RuntimeError(json.dumps({"error_type": "Timeout", "status_code": 504,
                                           "detail": f"tool timed out after {cfg.tool_timeout}s"}))
        except SdkError as exc:
            log_error("tool_fail", name, exc.__class__.__name__)
            if target == "searches.search_video":
                error = _str_search_error(exc, context)
                if data.get("image_query"):
                    error = error.replace(data["image_query"], "<image bytes>")
                raise RuntimeError(error)
            raise RuntimeError(_tool_error(exc))
        if handler_name in ["collection_list", "subcollections_list"]:
            out = collection_listing(out, subcollections=handler_name == "subcollections_list", **(context or {}))
        out_spec = {**spec, "handler": handler_name}
        text = await _tool_output(out, out_spec, verbose=verbose, context=context)
        if n_save:
            saved = await _find_save_images(client, json.loads(text), n_save, cfg)
            text = json.dumps(saved, ensure_ascii=False)
        return text

    _handler.__name__ = f"{name}_handler"
    _handler.__signature__ = _build_signature(schema)
    _handler.__doc__ = spec.get("desc", "")
    return _handler


def _register_tools(server: FastMCP):
    for name, spec in TOOL_REGISTRY.items():
        server.add_tool(
            _build_handler(name, spec),
            name=name,
            description=spec.get("desc"),
        )


def build_server(config: Optional[McpConfig] = None) -> FastMCP:
    cfg = config or McpConfig.from_env()
    global _ACTIVE_CFG
    _ACTIVE_CFG = cfg
    server = FastMCP(
        name="vmodal-mcp-robot",
        lifespan=_lifespan,
        instructions=(
            "For 'List all collections', call collection_list without a mode filter. "
            "For 'List all sub-collections', call collection_subcollections_list and show "
            "its table with Collection and Sub-collection columns. "
            "For 'Find {query}' with 'Collection: {name}', call find with query_text and "
            "collection_name. A blank Sub-collection means omit sub_collection_name "
            "to search the whole collection. Use exact collection/sub-collection names "
            "from discovery. Omit mode and version_id unless the user explicitly selects "
            "them; the tool resolves them automatically. Never guess or reuse another "
            "collection's index version. When the user wants the matching pictures, call "
            "find with save_images set to how many, and tell them the saved_path of each. "
            "For an image query use image_path or image_url; never put a URL in image_query. "
            "Download existing search hits with image_download_from_records in batches of "
            "at most 20 records, without copying signed URLs between tools. "
            "For robot data, register a user-reviewed telemetry format before upload. "
            "Use robot_find and robot_retrieve to preserve frame-map time and dataset/index versions. "
            "Run upload dry runs first; never treat unreviewed failure candidates as accepted tags."
        ),
    )
    _register_tools(server)
    return server


def run(transport: str = "", port: int = 8199):
    cfg = McpConfig.from_env()
    cfg.transport = transport.strip().lower() or cfg.transport
    server = build_server(cfg)
    if cfg.transport == "http":
        server.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        server.run()


def main() -> int:
    run()
    return 0


def cli() -> int:
    if len(sys.argv) == 1:
        return main()
    fire.Fire({"run": run, "main": main})
    return 0


if __name__ == "__main__":
    cli()
