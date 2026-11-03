from typing import Any, Dict, List, Optional, get_type_hints
import inspect
from pydantic import ConfigDict, create_model
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from vmodal.resources.collections import CollectionsResource
from vmodal.models import (
    SearchRequest_frontui_In,
    SearchResponse_frontui,
    GroupsResponse,
    VideoUploadResponse,
    VideoUploadBulkResponse,
    MetadataParquetUploadResponse,
    CollectionDescriptionUpdateResponse,
    DeleteCollectionResponse,
    CollectionAddAssetsResponse,
    IndexationJobsListResponse,
    IndexationSubmitRequest,
    IndexationSubmitResponse,
    IndexationStatusResponse,
    IndexationDeleteResponse,
    AdminUserStatsResponse,
    UserProfile,
    UsageUserDetail,
    CacheStats,
    R2CredentialsResponse,
    PresignedUploadResponse,
    PresignedFolderResponse,
    ImageUrlResponse,
    ImageUrlBulkResponse,
    ImageGetBulkResponse,
    HealthResponse,
)
from src.mcp_server.trim import normalize_image_records, trim_search, trim_jobs
from src.mcp_server import robot, robot_format


def _mk_schema(
    props: Dict[str, Dict[str, Any]],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "object",
        "properties": props,
        "additionalProperties": False,
    }
    if required:
        payload["required"] = required
    return payload


def _method_schema(method: Any) -> Dict[str, Any]:
    hints = get_type_hints(method)
    fields: Dict[str, Any] = {}
    for name, param in inspect.signature(method).parameters.items():
        if name in ("self", "cfg", "client", "find", "image_download"):
            continue
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (hints.get(name, Any), default)
    model = create_model(
        "McpMethodInput",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "health": {
        "target": "auth.health",
        "desc": "Check gateway/API health and version metadata.",
        "req_model": None,
        "resp_model": HealthResponse,
        "trim": None,
        "params": _mk_schema({}),
    },
    "auth_me": {
        "target": "auth.me",
        "desc": "Return the current users_api profile resolved from the Bearer token.",
        "req_model": None,
        "resp_model": UserProfile,
        "trim": None,
        "params": _mk_schema({}, []),
    },
    "search_video": {
        "target": "searches.search_video",
        "desc": "Find video/image content in group_name (collection), optionally stream_name (sub-collection). Blank stream searches all. Omit mode to infer it from the collection. Omit version_lancedb to resolve an available image index automatically; never guess a version. For natural-language Find prompts, prefer the find tool.",
        "req_model": SearchRequest_frontui_In,
        "schema_defaults": {
            "mode": None,
            "search_sources": ["image"],
            "stream_name": "",
            "version_lancedb": None,
            "limit": 20,
        },
        "call_defaults": {
            "mode": None,
            "search_sources": ["image"],
            "stream_name": "",
            "version_lancedb": None,
            "limit": 20,
        },
        "call_defaults_null": ["version_lancedb"],
        "required_nonempty": ["group_name"],
        "schema_required": ["group_name"],
        "schema_no_default": ["group_name"],
        "schema_overrides": {
            "mode": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Omit/null to infer the collection mode. Specify a listed mode only when the collection name is ambiguous."},
            "group_name": {"minLength": 1},
            "search_sources": {"items": {"type": "string", "enum": ["image"]}},
            "version_lancedb": {"description": "Omit/null for automatic index selection. Explicit versions must exist in collection_groups_list.lancedb_versions.", "anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        },
        "resp_model": SearchResponse_frontui,
        "trim": trim_search,
        "params": None,
    },
    "collection_groups_list": {
        "target": "collections.list_groups",
        "desc": "List groups for a collection mode. For 'List all collections', prefer collection_list, which also returns a Markdown table. Omit mode to include every mode.",
        "req_model": None,
        "resp_model": GroupsResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "mode": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Mode",
                    "default": None,
                }
            },
            [],
        ),
    },
    "collection_list": {
        "target": "collections.list_groups",
        "handler": "collection_list",
        "desc": "List all collections with their modes and available index versions, as data and a Markdown table. Omit mode to list every mode.",
        "params": _mk_schema({"mode": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}}),
    },
    "collection_subcollections_list": {
        "target": "admin.user_stats",
        "handler": "subcollections_list",
        "desc": "List all sub-collections in a Markdown table: Collection | Sub-collection | Mode. Optionally filter by collection_name or mode. Uses the SDK raw-asset inventory.",
        "params": _mk_schema({
            "collection_name": {"type": "string", "default": ""},
            "mode": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        }),
    },
    "find": {
        "target": "searches.search_video",
        "handler": "find",
        "desc": "Search collection_name with text, one image source, or both. Use image_query for plain base64, image_path for a server-local image, or image_url for a VMX signed URL; never put URLs in image_query. Resolves mode/version automatically. save_images=0..20 saves matching JPEG frames and returns absolute saved_path values.",
        "trim": trim_search,
        "required_nonempty": ["collection_name"],
        "params": _mk_schema({
            "query_text": {"type": "string", "default": ""},
            "image_query": {"type": "string", "default": "", "description": "Plain base64 image bytes, without data URI prefix or URL."},
            "image_path": {"type": "string", "default": "", "description": "Image path on the MCP server filesystem."},
            "image_url": {"type": "string", "default": "", "description": "VMX signed image URL; fetched through the SDK."},
            "collection_name": {"type": "string", "minLength": 1},
            "sub_collection_name": {"type": "string", "default": ""},
            "mode": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "version_id": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "string", "pattern": "^v?[0-9]+$"}, {"type": "null"}], "default": None},
            "limit": {"type": "integer", "minimum": 1, "default": 20},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "save_images": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
        }, ["collection_name"]),
    },
    "collection_video_upload": {
        "target": "collections.video_upload",
        "is_upload": True,
        "long_running": True,
        "upload_path_key": "filepath_local",
        "desc": "Upload one local video or image with adaptive multipart resume and optional 360px MP4 reduction.",
        "req_model": None,
        "resp_model": VideoUploadResponse,
        "trim": None,
        "schema_method": CollectionsResource.video_upload,
        "params": None,
    },
    "collection_video_upload_bulk": {
        "target": "collections.video_upload_bulk",
        "is_upload_folder": True,
        "long_running": True,
        "upload_folder_key": "folderpath_local",
        "desc": "Upload local MP4 files from a folder through the SDK signed-upload flow.",
        "req_model": None,
        "resp_model": VideoUploadBulkResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "folderpath_local": {"type": "string", "title": "folderpath_local"},
                "collection_name": {"type": "string", "title": "collection_name"},
                "sub_collection_name": {"type": "string", "title": "sub_collection_name"},
                "mode": {"type": "string", "title": "mode", "default": "vid_file"},
                "modality": {"type": "string", "title": "modality", "default": "vid_raw"},
                "ttl": {"type": "integer", "title": "ttl", "default": 12600},
            },
            ["folderpath_local", "collection_name", "sub_collection_name"],
        ),
    },
    "collection_upload_metadata": {
        "target": "collections.upload_metadata_jsonl",
        "is_upload": True,
        "desc": "Upload a local metadata JSONL file.",
        "req_model": None,
        "resp_model": MetadataParquetUploadResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "path": {"type": "string", "title": "path"},
                "mode": {"type": "string", "title": "mode", "default": "img_file"},
                "group_name": {"type": "string", "title": "group_name", "default": ""},
                "stream_name": {"type": "string", "title": "stream_name", "default": ""},
                "write_mode": {"type": "string", "title": "write_mode", "default": "append"},
                "allow_overlap": {"type": "boolean", "title": "allow_overlap", "default": False},
            },
            ["path"],
        ),
    },
    "collection_description_update": {
        "target": "collections.update_description",
        "desc": "Update collection/video metadata fields.",
        "req_model": None,
        "resp_model": CollectionDescriptionUpdateResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "group_name": {"type": "string", "title": "group_name"},
                "mode": {"type": "string", "title": "mode"},
                "stream_name": {"type": "string", "title": "stream_name"},
                "filename_sanitized": {"type": "string", "title": "filename_sanitized"},
                "description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "description",
                    "default": None,
                },
                "tag": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ],
                    "title": "tag",
                    "default": None,
                },
            },
            ["group_name", "mode", "stream_name", "filename_sanitized"],
        ),
    },
    "collection_delete": {
        "target": "collections.delete",
        "desc": "Delete or dry-run a group/mode collection scope.",
        "req_model": None,
        "resp_model": DeleteCollectionResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "group_name": {"type": "string", "title": "group_name"},
                "mode": {"type": "string", "title": "mode"},
                "scope": {"type": "string", "title": "scope", "default": "all"},
                "dry_run": {"type": "boolean", "title": "dry_run", "default": False},
                "confirm": {"type": "boolean", "title": "confirm", "default": False},
            },
            ["group_name", "mode"],
        ),
    },
    "collection_add_assets": {
        "target": "collections.add_assets",
        "desc": "Append asset IDs to an existing collection.",
        "req_model": None,
        "resp_model": CollectionAddAssetsResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "collection_id": {"type": "string", "title": "collection_id"},
                "mode": {"type": "string", "title": "mode"},
                "group_name": {"type": "string", "title": "group_name"},
                "stream_name": {"type": "string", "title": "stream_name", "default": "astream"},
                "asset_ids": {"type": "array", "title": "asset_ids", "items": {"type": "string"}},
            },
            ["collection_id", "mode", "group_name", "asset_ids"],
        ),
    },
    "index_jobs_list": {
        "target": "indexes.jobs_list",
        "desc": "List active or historical indexing jobs.",
        "req_model": None,
        "resp_model": IndexationJobsListResponse,
        "trim": trim_jobs,
        "params": _mk_schema(
            {
                "status": {"type": "string", "title": "status", "default": None},
                "mode": {"type": "string", "title": "mode", "default": None},
                "group_name": {"type": "string", "title": "group_name", "default": None},
                "limit": {"type": "integer", "title": "limit", "default": 200},
            },
            [],
        ),
    },
    "index_create": {
        "target": "indexes.create_index",
        "desc": "Start an indexing job and return job_id.",
        "req_model": IndexationSubmitRequest,
        "resp_model": IndexationSubmitResponse,
        "trim": None,
        "params": None,
    },
    "index_status": {
        "target": "indexes.index_status",
        "desc": "Poll indexing job state by job_id.",
        "req_model": None,
        "resp_model": IndexationStatusResponse,
        "trim": None,
        "params": _mk_schema({"job_id": {"type": "string", "title": "job_id"}}, ["job_id"]),
    },
    "index_delete": {
        "target": "indexes.delete_index",
        "desc": "Delete an index revision or job.",
        "req_model": None,
        "resp_model": IndexationDeleteResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "mode": {"type": "string", "title": "mode"},
                "group_name": {"type": "string", "title": "group_name"},
                "version": {"type": "string", "title": "version"},
                "modality": {"type": "string", "title": "modality", "default": None},
                "dry_run": {"type": "boolean", "title": "dry_run", "default": False},
                "confirm": {"type": "boolean", "title": "confirm", "default": False},
            },
            ["mode", "group_name", "version"],
        ),
    },
    "admin_user_stats": {
        "target": "admin.user_stats",
        "desc": "Fetch admin usage counters and totals.",
        "req_model": None,
        "resp_model": AdminUserStatsResponse,
        "trim": None,
        "params": _mk_schema({}, []),
    },
    "admin_usage": {
        "target": "admin.usage",
        "desc": "Fetch users_api usage detail for the current Bearer identity.",
        "req_model": None,
        "resp_model": UsageUserDetail,
        "trim": None,
        "params": _mk_schema(
            {
                "date": {"type": "string", "title": "date", "default": ""},
            },
            [],
        ),
    },
    "admin_cache_stats": {
        "target": "admin.cache_stats",
        "desc": "Fetch users_api auth/cache stats for the current Bearer identity.",
        "req_model": None,
        "resp_model": CacheStats,
        "trim": None,
        "params": _mk_schema({}, []),
    },
    "r2_credentials": {
        "target": "r2.get_credentials",
        "desc": "Fetch temporary R2 credentials for the current Bearer identity.",
        "req_model": None,
        "resp_model": R2CredentialsResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "dir_prefix": {"type": "string", "title": "dir_prefix", "default": ""},
            },
            [],
        ),
    },
    "r2_presign_upload_file": {
        "target": "r2.presign_upload_file",
        "desc": "Create one users_api presigned R2 upload URL.",
        "req_model": None,
        "resp_model": PresignedUploadResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "mode": {"type": "string", "title": "mode"},
                "group_name": {"type": "string", "title": "group_name"},
                "stream_name": {"type": "string", "title": "stream_name"},
                "modality": {"type": "string", "title": "modality"},
                "filename": {"type": "string", "title": "filename"},
                "expires_in": {"type": "integer", "title": "expires_in", "default": 86400},
            },
            ["mode", "group_name", "stream_name", "modality", "filename"],
        ),
    },
    "r2_presign_upload_folder_video": {
        "target": "r2.presign_upload_folder_video",
        "desc": "Create users_api presigned R2 upload URLs for multiple video files.",
        "req_model": None,
        "resp_model": PresignedFolderResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "mode": {"type": "string", "title": "mode"},
                "group_name": {"type": "string", "title": "group_name"},
                "stream_name": {"type": "string", "title": "stream_name"},
                "filenames": {"type": "array", "title": "filenames", "items": {"type": "string"}},
                "expires_in": {"type": "integer", "title": "expires_in", "default": 86400},
            },
            ["mode", "group_name", "stream_name", "filenames"],
        ),
    },
    "image_get_url": {
        "target": "images.get_url",
        "desc": "Resolve an image frame to a signed image URL.",
        "req_model": None,
        "resp_model": ImageUrlResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "mode": {"type": "string", "title": "mode"},
                "group_name": {"type": "string", "title": "group_name"},
                "modality": {"type": "string", "title": "modality"},
                "filename": {"type": "string", "title": "filename"},
                "stream_name": {"type": "string", "title": "stream_name", "default": "astream"},
                "ts_unix_13digits": {
                    "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}],
                    "title": "ts_unix_13digits",
                    "default": None,
                },
            },
            ["mode", "group_name", "modality", "filename"],
        ),
    },
    "image_get_url_bulk": {
        "target": "images.get_url_bulk",
        "desc": "Resolve a batch of frame references to signed image URLs.",
        "req_model": None,
        "resp_model": ImageUrlBulkResponse,
        "trim": None,
        "input_transform": normalize_image_records,
        "input_transform_key": "records",
        "params": _mk_schema(
            {
                "records": {
                    "type": "array",
                    "title": "records",
                    "items": {"type": "object", "additionalProperties": True},
                }
            },
            ["records"],
        ),
    },
    "image_get_from_url": {
        "target": "images.get_image_from_url",
        "desc": "Fetch a VMX signed URL and save a JPEG with canonical frame coordinates. Requires record metadata; prefer image_download_from_records for search hits.",
        "is_image": True,
        "handler": "image_bytes",
        "req_model": None,
        "resp_model": None,
        "trim": None,
        "params": _mk_schema(
            {
                "url_pre_signed": {"type": "string", "title": "url_pre_signed"},
                "record": {"type": "object", "additionalProperties": True},
                "root_folder": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            },
            ["url_pre_signed", "record"],
        ),
    },
    "image_get_bulk_from_urls": {
        "target": "images.get_image_bulk_from_urls",
        "desc": "Fetch 1..20 VMX signed URLs with aligned frame records and save canonical JPEG paths. Prefer image_download_from_records for search hits.",
        "is_image": True,
        "handler": "image_bulk",
        "req_model": None,
        "resp_model": ImageGetBulkResponse,
        "trim": None,
        "params": _mk_schema(
            {
                "urls": {
                    "type": "array",
                    "title": "urls",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 20,
                },
                "records": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "additionalProperties": True}},
                "root_folder": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            },
            ["urls", "records"],
        ),
    },
    "image_download_from_records": {
        "target": "images.get_url_bulk",
        "handler": "image_records",
        "desc": "Download 1..20 search result records as JPEG frames without copying signed URLs. Preserves input order and reports each failure. Paths: root/collection/stream/assetstem_timestamp.jpg; root defaults to MCP_IMAGE_DIR.",
        "params": _mk_schema({
            "records": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "additionalProperties": True}},
            "root_folder": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        }, ["records"]),
    },
}


for _func in [robot_format.telemetry_format_draft_from_file,
              robot_format.update_json_format_specs_from_file,
              robot_format.telemetry_format_list, robot_format.telemetry_format_check,
              robot.robot_episode_upload, robot.robot_dataset_upload,
              robot.robot_manifest_build, robot.robot_retrieve, robot.robot_find]:
    TOOL_REGISTRY[_func.__name__] = {
        "target": "robot." + _func.__name__, "robot_func": _func,
        "schema_method": _func, "desc": _func.__doc__ or {
            "telemetry_format_draft_from_file": "Draft telemetry format from a sample; unknown values require user review.",
            "update_json_format_specs_from_file": "Register a user-checked immutable format version, optionally bind a collection.",
            "telemetry_format_list": "List registered telemetry versions and collection bindings.",
            "telemetry_format_check": "Check telemetry against a registered spec and optional frame map/videos.",
            "robot_episode_upload": "Validate and hand off an episode with telemetry, frame map and camera clips. dry_run avoids network calls.",
            "robot_dataset_upload": "Cut LeRobot v3 packed videos, validate episodes, upload resumably or report dry-run verdicts.",
            "robot_manifest_build": "Rebuild the local manifest from preserved episode artifacts and statuses.",
            "robot_retrieve": "Resolve search hits or t_ns through the frame map; retrieve images and named telemetry.",
            "robot_find": "Search indexed robot frames, filter manifest metadata, return versioned episode hits and windows.",
        }[_func.__name__],
    }


def get_tool_schema(req_model):
    if req_model is None:
        return {}
    if hasattr(req_model, "model_json_schema"):
        return req_model.model_json_schema()
    return {}


def tool_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    method = spec.get("schema_method")
    spec_schema = _method_schema(method) if method else spec.get("params")
    if spec_schema is None:
        spec_schema = get_tool_schema(spec.get("req_model"))
    if not spec_schema:
        spec_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    if "properties" in spec_schema:
        spec_schema = dict(spec_schema)
        props = dict(spec_schema.get("properties") or {})
        for key, value in (spec.get("schema_defaults") or {}).items():
            if key in props:
                prop = dict(props[key])
                prop["default"] = value
                props[key] = prop
        for key, value in (spec.get("schema_overrides") or {}).items():
            if key in props:
                prop = dict(props[key])
                prop.update(value)
                props[key] = prop
        for key in spec.get("schema_no_default") or []:
            if key in props:
                prop = dict(props[key])
                prop.pop("default", None)
                props[key] = prop
        props.pop("user_id", None)
        props.pop("userid", None)
        spec_schema["properties"] = props
        required = list(spec_schema.get("required", []) or [])
        for key in spec.get("schema_required") or []:
            if key not in required:
                required.append(key)
        spec_schema["required"] = [x for x in required if x not in ("user_id", "userid")]
    return spec_schema
