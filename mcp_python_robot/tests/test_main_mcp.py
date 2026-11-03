"""


  - TEST_CLIENT_USER_ID as VMODAL_USER_ID
  - TEST_CLIENT_CLERK_USER_API_TOKEN as the API key through existing SDK env handling
  - mode="vid_file"
  - group_name="newsalien2"
  - stream_name="astream"
  - search_sources=["image"], because the default TEXT/AUDIO search hits a missing LanceDB text table for
    this fixture

  Verified locally with:


"""
import asyncio
import json
import os
import sys
import base64
import inspect
import socket
from unittest import TestCase
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from urllib.parse import urlparse
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from vmodal.routes import ACTIVE_ENDPOINTS, DISABLED_ENDPOINTS
from vmodal.models import SearchResponse_frontui, GroupsResponse, AdminUserStatsResponse
from vmodal.errors import ApiError, AuthError
from utils_datafake import dict_fake_catalog, dict_fake_stats, dict_fake_frame, image_fake_bytes
from PIL import Image
from vmodal import Client
from vmodal.resources.collections import CollectionsResource

from vmodal.config import SdkConfig, PUBLIC_GATEWAY_URL, DEV_GATEWAY_URL
from src.mcp_server.config import McpConfig
from src.mcp_server.main_mcp import build_server
from src.mcp_server.main_mcp import _check_upload_path
from src.mcp_server.main_mcp import _check_upload_folder
from src.mcp_server.main_mcp import _os_dir_cap, _image_download_records
from src.mcp_server.utils import os_frame_path, os_save_frame, str_frame_component
import src.mcp_server.main_mcp as main_mcp
from src.mcp_server.trim import normalize_image_records, trim_search
from src.mcp_server.registry import TOOL_REGISTRY, tool_schema

dirtest = "ztmp/ztests"


def _snapshot_user_env():
    return {
        "VMODAL_USER_ID": os.environ.get("VMODAL_USER_ID", ""),
        "VMODAL_BASE_URL": os.environ.get("VMODAL_BASE_URL", ""),
        "VMODAL_API_URL": os.environ.get("VMODAL_API_URL", ""),
        "VMODAL_API_TOKEN": os.environ.get("VMODAL_API_TOKEN", ""),
        "VMODAL_API_KEY": os.environ.get("VMODAL_API_KEY", ""),
        "VMODAL_ENV": os.environ.get("VMODAL_ENV", ""),
        "VMODAL_MODE": os.environ.get("VMODAL_MODE", ""),
        "TEST_CLIENT_SERVER_API_URL": os.environ.get("TEST_CLIENT_SERVER_API_URL", ""),
        "TEST_CLIENT_CLERK_USER_API_TOKEN": os.environ.get("TEST_CLIENT_CLERK_USER_API_TOKEN", ""),
        "TEST_CLIENT_USER_TOKEN": os.environ.get("TEST_CLIENT_USER_TOKEN", ""),
        "VMODAL_TRACE": os.environ.get("VMODAL_TRACE", ""),
        "api_key": os.environ.get("api_key", ""),
    }


def _restore_user_env(snapshot):
    for key, value in snapshot.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def test1():
    here = _snapshot_user_env()
    for key in [
        "VMODAL_USER_ID",
        "VMODAL_API_URL",
        "VMODAL_BASE_URL",
        "VMODAL_API_TOKEN",
        "VMODAL_API_KEY",
        "VMODAL_ENV",
        "VMODAL_MODE",
        "TEST_CLIENT_SERVER_API_URL",
        "TEST_CLIENT_CLERK_USER_API_TOKEN",
        "TEST_CLIENT_USER_TOKEN",
        "api_key",
    ]:
        os.environ.pop(key, None)
    os.environ["MCP_IMAGE_DIR"] = "ztmp/mcp_images"
    cfg = McpConfig.from_env(resolve_identity=False)
    assert cfg.image_dir == "ztmp/mcp_images"
    assert cfg.transport in {"stdio", "http"}
    assert cfg.upload_max_mb == 5120
    assert cfg.sdk.mode == "gateway"
    assert cfg.sdk.base_url == PUBLIC_GATEWAY_URL + "/api/v1/proxy/search_api"
    assert cfg.cfg_error == "API key required: set api_key in the MCP server environment"
    _restore_user_env(here)


def test1b():
    here = _snapshot_user_env()
    for key in [
        "VMODAL_API_URL",
        "VMODAL_API_TOKEN",
        "VMODAL_API_KEY",
        "VMODAL_ENV",
        "VMODAL_USER_ID",
        "VMODAL_BASE_URL",
        "VMODAL_MODE",
        "TEST_CLIENT_SERVER_API_URL",
        "TEST_CLIENT_CLERK_USER_API_TOKEN",
        "TEST_CLIENT_USER_TOKEN",
    ]:
        os.environ.pop(key, None)
    os.environ["api_key"] = "ak_mcp"
    cfg = McpConfig.from_env(resolve_identity=False)
    assert cfg.cfg_error == ""
    assert cfg.sdk.mode == "gateway"
    assert cfg.sdk.base_url == PUBLIC_GATEWAY_URL + "/api/v1/proxy/search_api"
    assert cfg.sdk.token == "ak_mcp"
    assert cfg.sdk.user_id == ""
    _restore_user_env(here)


def test1c():
    here = _snapshot_user_env()
    os.environ["VMODAL_ENV"] = "dev"
    os.environ["VMODAL_BASE_URL"] = DEV_GATEWAY_URL
    os.environ["VMODAL_MODE"] = "gateway"
    os.environ["api_key"] = "ak_mcp"
    cfg = McpConfig.from_env(resolve_identity=False)
    assert cfg.cfg_error == ""
    assert cfg.sdk.mode == "gateway"
    assert cfg.sdk.base_url == DEV_GATEWAY_URL + "/api/v1/proxy/search_api"
    assert cfg.sdk.token == "ak_mcp"
    _restore_user_env(here)


def test1d():
    here = _snapshot_user_env()
    os.environ["api_key"] = "ak_mcp"

    def resolve_identity(cfg, refresh=False):
        cfg.user_id = "user_mcp"
        return {"user_id": cfg.user_id}

    with patch.object(SdkConfig, "resolve_identity", resolve_identity):
        cfg = McpConfig.from_env()
    assert cfg.cfg_error == ""
    assert cfg.sdk.user_id == "user_mcp"
    _restore_user_env(here)


def test2():
    os_makedirs(dirtest)
    server = build_server(McpConfig.from_env(resolve_identity=False))
    tools = asyncio.run(server.list_tools())
    assert len(tools) == len(TOOL_REGISTRY)
    upload = [x for x in tools if x.name == "collection_video_upload"][0]
    sdk_upload = set(inspect.signature(CollectionsResource.video_upload).parameters) - {"self"}
    assert set(upload.inputSchema["properties"]) == sdk_upload
    if "reduce_size" in sdk_upload:
        assert upload.inputSchema["properties"]["reduce_size"]["default"] is False
    search = [x for x in tools if x.name == "search_video"][0]
    assert search.inputSchema["properties"]["search_sources"]["default"] == ["image"]
    assert search.inputSchema["properties"]["search_sources"]["items"]["const"] == "image"
    assert search.inputSchema["properties"]["stream_name"]["default"] == ""
    assert search.inputSchema["properties"]["mode"]["default"] is None
    assert {x["type"] for x in search.inputSchema["properties"]["mode"]["anyOf"]} == {"string", "null"}
    assert search.inputSchema["properties"]["version_lancedb"]["default"] is None
    assert search.inputSchema["properties"]["limit"]["default"] == 20
    assert "group_name" in search.inputSchema["required"]
    assert "default" not in search.inputSchema["properties"]["group_name"]


def test3():
    schema = tool_schema(TOOL_REGISTRY["search_video"])
    props = schema.get("properties", {})
    assert "query_text" in props
    assert "mode" in props
    assert "limit" in props
    assert props["search_sources"]["default"] == ["image"]
    assert props["search_sources"]["items"]["enum"] == ["image"]
    assert props["stream_name"]["default"] == ""
    assert props["mode"]["default"] is None
    assert props["version_lancedb"]["default"] is None
    assert props["limit"]["default"] == 20
    assert "group_name" in schema["required"]
    assert "default" not in props["group_name"]
    assert props["group_name"]["minLength"] == 1
    assert "user_id" not in props
    assert "userid" not in props
    groups = tool_schema(TOOL_REGISTRY["collection_groups_list"])
    assert groups["properties"]["mode"]["default"] is None
    upload = tool_schema(TOOL_REGISTRY["collection_video_upload"])
    sdk_params = dict(inspect.signature(CollectionsResource.video_upload).parameters)
    sdk_params.pop("self")
    assert upload["properties"]["modality"]["default"] == "vid_raw"
    assert upload["properties"]["multipart"]["default"] is None
    assert upload["properties"]["multipart_threshold_bytes"]["default"] == 100 * 1024 * 1024
    assert upload["properties"]["max_part_attempts"]["default"] == 5
    assert upload["properties"]["resume"]["default"] is True
    for name, param in sdk_params.items():
        if param.default is not inspect.Parameter.empty:
            assert upload["properties"][name]["default"] == param.default
    assert set(upload["properties"]) == set(sdk_params)
    assert set(upload["required"]) == {"filepath_local", "collection_name", "sub_collection_name"}
    assert "collection_upload_file" not in TOOL_REGISTRY
    assert "collection_upload_gdrive" not in TOOL_REGISTRY
    update = tool_schema(TOOL_REGISTRY["collection_description_update"])
    assert "tag" in update["properties"]
    assert set(update["required"]) == {"group_name", "mode", "stream_name", "filename_sanitized"}
    image = tool_schema(TOOL_REGISTRY["image_get_url"])
    ts_types = {x["type"] for x in image["properties"]["ts_unix_13digits"]["anyOf"]}
    assert ts_types == {"string", "integer", "null"}
    image_one = tool_schema(TOOL_REGISTRY["image_get_from_url"])
    image_bulk = tool_schema(TOOL_REGISTRY["image_get_bulk_from_urls"])
    assert set(image_one["required"]) == {"url_pre_signed", "record"}
    assert set(image_bulk["required"]) == {"urls", "records"}
    assert image_bulk["properties"]["records"]["maxItems"] == 20
    find = tool_schema(TOOL_REGISTRY["find"])
    assert set(find["required"]) == {"collection_name"}
    assert {"image_path", "image_url", "image_query"}.issubset(find["properties"])
    assert find["properties"]["version_id"]["default"] is None
    assert find["properties"]["sub_collection_name"]["default"] == ""


def test9():
    got = {item["target"] for item in TOOL_REGISTRY.values()}
    users_api = {
        "auth.me",
        "admin.usage",
        "admin.cache_stats",
        "r2.get_credentials",
        "r2.presign_upload_file",
        "r2.presign_upload_folder_video",
    }
    sdk_helpers = {
        "collections.video_upload",
        "collections.video_upload_bulk",
    }
    removed = {
        "auth.auth_check",
        "collections.upload_google_drive_folder",
    }
    robot_helpers = {"robot."+name for name in (
        "telemetry_format_draft_from_file", "update_json_format_specs_from_file",
        "telemetry_format_list", "telemetry_format_check", "robot_episode_upload",
        "robot_dataset_upload", "robot_manifest_build", "robot_find", "robot_retrieve")}
    want = (set(ACTIVE_ENDPOINTS.keys()) - removed) | users_api | sdk_helpers | robot_helpers
    assert got == want
    dead = set(DISABLED_ENDPOINTS.keys())
    assert not (got & dead)
    assert users_api.issubset(got)
    assert sdk_helpers.issubset(got)
    assert not (got & removed)
    assert TOOL_REGISTRY["image_download_from_records"]["target"] == "images.get_url_bulk"
    assert TOOL_REGISTRY["image_download_from_records"]["handler"] == "image_records"


def test4():
    data = []
    for idx in range(50):
        data.append(
            {
                "score": 0.95,
                "mode": "vid_file",
                "group_name": "agroup",
                "stream_name": "astream",
                "source_path": "s/path.bin",
                "ts_unix": idx,
                "text_snippet": "x" * 500,
                "embedding": [1, 2, 3],
                "raw": {"vec": [1, 2, 3]},
            }
        )
    raw = SearchResponse_frontui(data=data, cnt_actual=50, cnt_total=50, execution_time_ms=12.5)
    got = trim_search(raw, verbose=False, context={"limit": 50, "offset": 10})
    assert len(got["data"]) == 50
    assert got["n_total_returned"] == 50 and got["requested_limit"] == 50 and got["offset"] == 10
    assert len(trim_search(raw, context={"limit": 3})["data"]) == 3
    assert trim_search(raw, verbose=True, context={"limit": 50})["n_total_returned"] == 50
    assert got["n_total"] == 50
    assert got["trimmed"] is True
    assert len(got["data"][0]["text_snippet"]) <= 200
    assert "embedding" not in got["data"][0]
    hit = {
        "score": 0.7346,
        "filename": "folder\\Rome walk.mp4",
        "title": "A walk, not an asset name",
        "stream": "rome",
        "source": "image",
        "ts_unix": 18421,
        "modality": "vid_img_emb",
        "embedding": [1, 2, 3],
        "text_snippet": "z" * 500,
    }
    ctx = {"mode": "vid_file", "group_name": "city", "stream_name": "request-stream"}
    class RawResponse:
        data = [hit]
        cnt_actual = 1
        cnt_total = 1
        execution_time_ms = 1

    raw2 = RawResponse()
    compact = trim_search(raw2, context=ctx)
    row = compact["data"][0]
    assert row["mode"] == "vid_file"
    assert row["group_name"] == "city"
    assert row["stream_name"] == "rome"
    assert row["modality"] == "vid_img"
    assert row["filename"] == "Rome walk.mp4"
    assert row["source_path"] == "folder\\Rome walk.mp4"
    assert row["ts_unix_13digits"] == "0000000018421"
    assert "title" not in row
    assert "embedding" not in row
    verbose = trim_search(raw2, verbose=True, context=ctx)
    vrow = verbose["data"][0]
    assert verbose["trimmed"] is False
    assert vrow["title"] == "A walk, not an asset name"
    assert vrow["stream"] == "rome"
    assert vrow["source"] == "image"
    assert vrow["search_modality"] == "vid_img_emb"
    assert vrow["modality"] == "vid_img"
    assert len(vrow["text_snippet"]) == 500


def test5():
    row = dict_fake_frame()
    root = os.path.abspath(os.path.join(dirtest, "jpeg_contract"))
    os_path_cleanup(root)
    path = os_frame_path(root, row)
    assert path == os.path.join(root, "fashion_milan", "runway", "Look_01_1735689600123.jpg")
    for fmt in ["WebP", "PNG", "GIF", "JPEG"]:
        rec = dict_fake_frame(filename=fmt + ".mp4")
        saved = os_save_frame(image_fake_bytes(fmt), os_frame_path(root, rec), rec)
        with open(saved["saved_path"], "rb") as fh:
            assert fh.read(3) == b"\xff\xd8\xff"
        with Image.open(saved["saved_path"]) as img:
            assert img.format == "JPEG" and img.size == (4, 3)
        if fmt == "JPEG":
            with open(saved["saved_path"], "rb") as fh:
                assert fh.read() == image_fake_bytes(fmt)


def test6():
    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.upload_max_mb = 5120
    try:
        _check_upload_path("this_path_does_not_exist.bin", cfg)
        assert False
    except Exception:
        assert True
    os_makedirs(dirtest)
    path = os.path.join(dirtest, "sparse_1g.mp4")
    with open(path, "wb") as fh:
        fh.truncate(1024 * 1024 * 1024)
    assert _check_upload_path(path, cfg) == path
    os.remove(path)


def test7():
    if not os.environ.get("VMODAL_USER_ID") and os.environ.get("TEST_CLIENT_USER_ID"):
        os.environ["VMODAL_USER_ID"] = os.environ["TEST_CLIENT_USER_ID"]
    cfg = McpConfig.from_env()
    assert not cfg.cfg_error, cfg.cfg_error
    assert cfg.sdk.user_id, "live test requires a resolved user_id"
    mode = os.environ.get("VMODAL_LIVE_MODE", "vid_file")
    group_name = os.environ.get("VMODAL_LIVE_GROUP_NAME", "newsalien2")
    stream_name = os.environ.get("VMODAL_LIVE_STREAM_NAME", "astream")

    assert cfg.sdk.base_url, "live test requires a base URL"

    async def _live():
        async with Client(cfg=cfg.sdk) as cli:
            await cli.health()
            await cli.collections.list_groups(mode=mode)
            await cli.searches.search_video(
                query_text="sample",
                mode=mode,
                group_name=group_name,
                stream_name=stream_name,
                search_sources=["image"],
                version_lancedb=0,
            )

    asyncio.run(_live())


def test8():
    if not os.environ.get("VMODAL_USER_ID") and os.environ.get("TEST_CLIENT_USER_ID"):
        os.environ["VMODAL_USER_ID"] = os.environ["TEST_CLIENT_USER_ID"]
    cfg = McpConfig.from_env()
    assert not cfg.cfg_error, cfg.cfg_error
    assert cfg.sdk.base_url, "live_mcp requires TEST_CLIENT_SERVER_API_URL or VMODAL_BASE_URL"
    mode = os.environ.get("VMODAL_LIVE_MODE", "vid_file")
    group_name = os.environ.get("VMODAL_LIVE_GROUP_NAME", "newsalien2")
    stream_name = os.environ.get("VMODAL_LIVE_STREAM_NAME", "astream")
    query_text = os.environ.get("VMODAL_LIVE_QUERY_TEXT", "sample")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env = dict(os.environ)

    async def _live_mcp():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server.main_mcp", "run", "--transport", "stdio"],
            env=env,
            cwd=root,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {item.name for item in listed.tools}
                assert names == set(TOOL_REGISTRY)
                health = await session.call_tool("health", {})
                assert not health.isError
                assert health.content
                groups = await session.call_tool("collection_groups_list", {"mode": mode})
                assert not groups.isError
                assert groups.content
                cols = await session.call_tool("collection_list", {})
                assert not cols.isError
                assert "table" in json.loads(cols.content[0].text)
                subs = await session.call_tool("collection_subcollections_list", {})
                assert not subs.isError
                assert "table" in json.loads(subs.content[0].text)
                found = await session.call_tool("find", {"query_text": query_text, "collection_name": group_name, "mode": mode, "limit": 3})
                assert not found.isError, found.content
                assert "version_lancedb" in json.loads(found.content[0].text)
                search = await session.call_tool(
                    "search_video",
                    {
                        "query_text": query_text,
                        "mode": mode,
                        "group_name": group_name,
                        "stream_name": stream_name,
                        "search_sources": ["image"],
                        "limit": 3,
                    },
                )
                assert not search.isError
                assert search.content
                search_data = json.loads(search.content[0].text)
                rows = search_data.get("data") or []
                assert rows, f"search returned no frames for: {query_text}"
                image_res = await session.call_tool(
                    "image_download_from_records",
                    {"records": rows, "root_folder": os.path.abspath(os.path.join(dirtest, "live_frames"))},
                )
                assert not image_res.isError
                image_data = json.loads(image_res.content[0].text)
                output_dir = image_data.get("output_dir") or ""
                saved_paths = image_data.get("saved_paths") or []
                assert os.path.isabs(output_dir)
                assert saved_paths
                assert all(os.path.isfile(path) for path in saved_paths)
                log_info(
                    "live_mcp ok tools=%s mode=%s group_name=%s stream_name=%s query=%s output_dir=%s"
                    % (len(names), mode, group_name, stream_name, query_text, output_dir)
                )

    asyncio.run(_live_mcp())


def test10():
    root = os.path.abspath(os.path.join(dirtest, "paths"))
    row = dict_fake_frame(group_name="../fashion", stream_name="a/b", filename="../../Look:01.mp4")
    path = os_frame_path(root, row)
    assert os.path.commonpath([root, path]) == root
    assert path.endswith("fashion/a_b/Look_01_1735689600123.jpg")
    for key, value in [("filename", ".."), ("stream_name", ""), ("group_name", ".."), ("ts_unix_13digits", "42")]:
        with TestCase().assertRaises(ValueError):
            os_frame_path(root, dict_fake_frame(**{key: value}))
    assert str_frame_component("a b") == "a_b"


def test11():
    row = dict_fake_frame()
    path = os_frame_path(os.path.join(dirtest, "invalid_bytes"), row)
    os_path_cleanup(os.path.dirname(path))
    for raw in [b"", b"fake-image", {"img_base64": "!!!"}]:
        with TestCase().assertRaises((ValueError, OSError)):
            os_save_frame(raw, path, row)
        assert not os.path.exists(path)


def test12():
    cfg = McpConfig.from_env(resolve_identity=False)
    cli = SimpleNamespace(images=SimpleNamespace(get_url_bulk=AsyncMock(), get_image_from_url=AsyncMock()))
    for records in [[], [dict_fake_frame()] * 21, None]:
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(_image_download_records(cli, records, cfg))
        assert json.loads(str(err.exception))["status_code"] == 422
    cli.images.get_url_bulk.assert_not_awaited()
    cli.images.get_image_from_url.assert_not_awaited()


def test13():
    # P2 config: tool_timeout default derivation + env override
    here = _snapshot_user_env()
    os.environ.pop("MCP_TOOL_TIMEOUT", None)
    cfg = McpConfig.from_env(resolve_identity=False)
    want = cfg.sdk.timeout * (cfg.sdk.max_retries + 1) + 10
    assert cfg.tool_timeout == want
    os.environ["MCP_TOOL_TIMEOUT"] = "5"
    cfg2 = McpConfig.from_env(resolve_identity=False)
    assert cfg2.tool_timeout == 5.0
    os.environ.pop("MCP_TOOL_TIMEOUT", None)
    _restore_user_env(here)


def test14():
    # S6 dir cap: 510 files → keep 500 newest
    import time
    d = "ztmp/mcp_images_test/cap"
    os_makedirs(d)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for i in range(510):
        p = os.path.join(d, f"f{i:04d}.jpg")
        with open(p, "wb") as fh:
            fh.write(b"x")
        os.utime(p, (i, i))
    _os_dir_cap(d, max_files=500)
    left = os.listdir(d)
    assert len(left) == 500
    # oldest (f0000..f0009) removed, newest kept
    assert "f0000.jpg" not in left
    assert "f0509.jpg" in left


def test15():
    root = os.path.join(dirtest, "conflicts")
    os_path_cleanup(root)
    row = dict_fake_frame(filename="Look:01.mp4")
    path = os_frame_path(root, row)
    raw = image_fake_bytes()
    os_save_frame(raw, path, row)
    assert os_save_frame(raw, path, row)["saved_path"] == path
    other = dict_fake_frame(filename="Look?01.mp4")
    assert os_frame_path(root, other) == path
    with TestCase().assertRaisesRegex(ValueError, "path_conflict"):
        os_save_frame(raw, path, other)
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test16():
    # Latest SDK upload controls are forwarded and are not cancelled by the
    # short outer timeout used for ordinary MCP tools.
    os_makedirs(dirtest)
    path = os.path.abspath(os.path.join(dirtest, "upload_options.mp4"))
    with open(path, "wb") as fh:
        fh.write(b"video")
    calls = []

    class FakeCollections:
        async def video_upload(self, **kw):
            await asyncio.sleep(0.02)
            calls.append(kw)
            return {"uploaded": True, "upload_strategy": "multipart"}

    class FakeClient:
        def __init__(self):
            self.collections = FakeCollections()

    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    cfg.upload_max_mb = 5120
    cfg.tool_timeout = 0.001
    old_cfg = main_mcp._ACTIVE_CFG
    old_client = main_mcp._ACTIVE_CLIENT
    old_cache = dict(main_mcp._TARGET_CACHE)
    main_mcp._ACTIVE_CFG = cfg
    main_mcp._ACTIVE_CLIENT = FakeClient()
    main_mcp._TARGET_CACHE.clear()
    sdk_params = set(inspect.signature(CollectionsResource.video_upload).parameters)
    opts = {
        "filepath_local": path,
        "collection_name": "agroup",
        "sub_collection_name": "astream",
        "multipart": True,
        "multipart_threshold_bytes": 64 * 1024 * 1024,
        "part_size_bytes": 16 * 1024 * 1024,
        "max_concurrency": 2,
        "max_part_attempts": 7,
        "part_timeout_seconds": 45.0,
        "resume": True,
    }
    if "network_mbps" in sdk_params:
        opts["network_mbps"] = 25.0
    if "reduce_size" in sdk_params:
        opts["reduce_size"] = True
    try:
        handler = main_mcp._build_handler("collection_video_upload", TOOL_REGISTRY["collection_video_upload"])
        out = asyncio.run(handler(**opts))
    finally:
        main_mcp._ACTIVE_CFG = old_cfg
        main_mcp._ACTIVE_CLIENT = old_client
        main_mcp._TARGET_CACHE.clear()
        main_mcp._TARGET_CACHE.update(old_cache)
    assert '"uploaded": true' in out
    assert len(calls) == 1
    got = calls[0]
    assert got["multipart"] is True
    assert got["part_size_bytes"] == 16 * 1024 * 1024
    assert got["max_concurrency"] == 2
    assert got["max_part_attempts"] == 7
    assert got["part_timeout_seconds"] == 45.0
    assert got["resume"] is True
    if "network_mbps" in sdk_params:
        assert got["network_mbps"] == 25.0
    if "reduce_size" in sdk_params:
        assert got["reduce_size"] is True


def test17():
    search_calls = []
    image_calls = []

    class RawResponse:
        def __init__(self, group_name):
            self.data = [{
                "score": 0.9,
                "filename": f"folder/{group_name}.mp4",
                "stream": f"hit-{group_name}",
                "source": "image",
                "ts_unix": 42,
            }]
            self.cnt_actual = 1
            self.cnt_total = 1
            self.execution_time_ms = 2

    class FakeSearches:
        async def search_video(self, **kw):
            search_calls.append(kw)
            return RawResponse(kw["group_name"])

    class FakeImages:
        async def get_url_bulk(self, **kw):
            image_calls.append(kw)
            return {"records": kw["records"]}

    class FakeClient:
        def __init__(self):
            self.searches = FakeSearches()
            self.images = FakeImages()
            self.collections = SimpleNamespace(list_groups=AsyncMock(return_value=GroupsResponse.model_validate(dict_fake_catalog())))

    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    old_cfg = main_mcp._ACTIVE_CFG
    old_client = main_mcp._ACTIVE_CLIENT
    old_cache = dict(main_mcp._TARGET_CACHE)
    main_mcp._ACTIVE_CFG = cfg
    main_mcp._ACTIVE_CLIENT = FakeClient()
    main_mcp._TARGET_CACHE.clear()
    try:
        search = main_mcp._build_handler("search_video", TOOL_REGISTRY["search_video"])
        bulk = main_mcp._build_handler("image_get_url_bulk", TOOL_REGISTRY["image_get_url_bulk"])
        city = json.loads(asyncio.run(search(query_text="a red car", group_name="city")))
        assert search_calls[0]["stream_name"] == ""
        assert search_calls[0]["version_lancedb"] == 10
        assert city["version_lancedb"] == 10
        assert search_calls[0]["search_sources"] == ["image"]
        assert search_calls[0]["limit"] == 20
        crow = city["data"][0]
        assert crow["mode"] == "vid_file"
        assert crow["group_name"] == "city"
        assert crow["stream_name"] == "hit-city"
        assert crow["filename"] == "city.mp4"
        assert crow["modality"] == "vid_img"
        assert crow["ts_unix_13digits"] == "0000000000042"

        japan = json.loads(asyncio.run(search(
            query_text="temple",
            group_name="japan",
            stream_name="asked-stream",
            version_lancedb=3,
        )))
        assert search_calls[1]["stream_name"] == "asked-stream"
        assert search_calls[1]["version_lancedb"] == 3
        assert japan["data"][0]["group_name"] == "japan"
        assert japan["data"][0]["stream_name"] == "hit-japan"
        assert city["data"][0]["group_name"] == "city"

        asyncio.run(search(query_text="null version", group_name="city", version_lancedb=None))
        assert search_calls[2]["version_lancedb"] == 10
        before = len(search_calls)
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(search(query_text="bad", group_name=" "))
        detail = json.loads(str(err.exception))
        assert detail["status_code"] == 422
        assert detail["detail"]["missing_fields"] == ["group_name"]
        assert len(search_calls) == before

        got = json.loads(asyncio.run(bulk(records=city["data"])))
        assert got["records"] == image_calls[0]["records"]
        sent = image_calls[0]["records"][0]
        assert list(sent) == ["mode", "group_name", "stream_name", "modality", "filename", "ts_unix_13digits"]
        assert sent["stream_name"] == "hit-city"
        assert sent["modality"] == "vid_img"
        assert sent["filename"] == "city.mp4"

        aliases = [
            {"mode": "vid_file", "group_name": "city", "stream": "s1", "filename": "a/b.mp4", "modality": "vid_img_emb", "ts_unix": 9},
            {"mode": "img_file", "group_name": "photos", "stream_name": "s2", "file_name": "c.jpg", "modality": "thumbnail"},
        ]
        asyncio.run(bulk(records=aliases))
        assert image_calls[1]["records"][0]["modality"] == "vid_img"
        assert image_calls[1]["records"][0]["filename"] == "b.mp4"
        assert image_calls[1]["records"][0]["ts_unix_13digits"] == "0000000000009"
        assert image_calls[1]["records"][1]["modality"] == "thumbnail"
        assert len(image_calls[1]["records"]) == 2

        before = len(image_calls)
        bad = [aliases[0], {"mode": "vid_file", "group_name": "city", "stream": "", "filename": "missing.mp4", "modality": "vid_img", "ts_unix": 9}]
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(bulk(records=bad))
        detail = json.loads(str(err.exception))
        assert detail["status_code"] == 422
        assert detail["detail"]["record_index"] == 1
        assert detail["detail"]["missing_fields"] == ["stream_name"]
        assert len(image_calls) == before
    finally:
        main_mcp._ACTIVE_CFG = old_cfg
        main_mcp._ACTIVE_CLIENT = old_client
        main_mcp._TARGET_CACHE.clear()
        main_mcp._TARGET_CACHE.update(old_cache)


def test18():
    records = normalize_image_records([
        {
            "mode": "vid_file",
            "group_name": "city",
            "stream": "rome",
            "source_asset_file": "folder\\clip.mp4",
            "modality": "img_emb",
            "timestamp_ms": "17",
            "score": 0.8,
            "embedding": [1, 2, 3],
        }
    ])
    assert records == [{
        "mode": "vid_file",
        "group_name": "city",
        "stream_name": "rome",
        "modality": "vid_img",
        "filename": "clip.mp4",
        "ts_unix_13digits": "0000000000017",
    }]

    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    catalog = dict_fake_catalog()
    groups = AsyncMock(return_value=GroupsResponse.model_validate(catalog))
    stats = AsyncMock(return_value=AdminUserStatsResponse.model_validate(dict_fake_stats()))
    search = AsyncMock(return_value=SearchResponse_frontui())
    cli = SimpleNamespace(collections=SimpleNamespace(list_groups=groups), admin=SimpleNamespace(user_stats=stats), searches=SimpleNamespace(search_video=search))
    with patch.object(main_mcp, "_ACTIVE_CFG", cfg), patch.object(main_mcp, "_ACTIVE_CLIENT", cli), patch.dict(main_mcp._TARGET_CACHE, {}, clear=True):
        server = build_server(cfg)
        assert "collection_subcollections_list" in server.instructions
        assert "Omit mode and version_id" in server.instructions
        listed = asyncio.run(server.call_tool("collection_list", {"mode": None}))
        cols = json.loads(listed[0].text)
        assert cols["total"] == 3
        assert cols["data"][1]["collection_name"] == "city"
        assert cols["data"][1]["lancedb_versions"] == ["v10", "v2", "v0"]
        subs = asyncio.run(server.call_tool("collection_subcollections_list", {}))
        subdata = json.loads(subs[0].text)
        assert subdata["total"] == 3
        assert "| Collection | Sub-collection | Mode |" in subdata["table"]
        assert "| city | rome | vid_file |" in subdata["table"]
        assert "trip\\|2026" in subdata["table"]
        stats.assert_awaited_once_with()
        handler = main_mcp._build_handler("collection_subcollections_list", TOOL_REGISTRY["collection_subcollections_list"])
        filtered = json.loads(asyncio.run(handler(collection_name="city", mode="vid_file")))
        assert filtered["total"] == 2
        assert {row["sub_collection_name"] for row in filtered["data"]} == {"rome", "tokyo"}

        found = asyncio.run(server.call_tool("find", {"query_text": "a red car", "collection_name": "city", "mode": None, "version_id": None}))
        assert json.loads(found[0].text)["version_lancedb"] == 10
        assert search.call_args.kwargs["stream_name"] == ""
        assert search.call_args.kwargs["mode"] == "vid_file"
        assert "collection_name" not in search.call_args.kwargs
        assert "version_id" not in search.call_args.kwargs
        legacy = asyncio.run(server.call_tool("search_video", {"query_text": "a red car", "group_name": "city", "version_lancedb": None}))
        assert json.loads(legacy[0].text)["version_lancedb"] == 10
        find = main_mcp._build_handler("find", TOOL_REGISTRY["find"])
        asyncio.run(find(query_text="a temple", collection_name="city", sub_collection_name="rome", version_id="v2"))
        assert search.call_args.kwargs["stream_name"] == "rome"
        assert search.call_args.kwargs["version_lancedb"] == 2
        before = search.await_count
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(query_text="bad version", collection_name="city", version_id=99))
        detail = json.loads(str(err.exception))
        assert detail["status_code"] == 422
        assert detail["detail"]["available_versions"] == [10, 2, 0]
        assert search.await_count == before

        search.reset_mock()
        search.side_effect = [ApiError("missing", status_code=404, details="missing LanceDB index: table vid_img_emb does not exist"), SearchResponse_frontui()]
        out = json.loads(asyncio.run(find(query_text="a car", collection_name="city")))
        assert [call.kwargs["version_lancedb"] for call in search.await_args_list] == [10, 2]
        assert out["version_lancedb"] == 2

        # The newest revision exists but its embedding model cannot be resolved: fall back as well.
        search.reset_mock()
        search.side_effect = [ApiError("no model", status_code=500, details="Unable to resolve query embedding model for mode=vid_file group=city modality=vid_img_emb version=v10"), SearchResponse_frontui()]
        out = json.loads(asyncio.run(find(query_text="a car", collection_name="city")))
        assert [call.kwargs["version_lancedb"] for call in search.await_args_list] == [10, 2]
        assert out["version_lancedb"] == 2

        search.reset_mock()
        search.side_effect = ApiError("missing", status_code=404, details="missing LanceDB index")
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(query_text="a car", collection_name="city"))
        detail = json.loads(str(err.exception))
        assert detail["attempted_versions"] == [10, 2, 0]
        assert detail["available_versions"] == [10, 2, 0]
        assert search.await_count == 3

        for exc, opts in [
            (ApiError("missing", status_code=500, details="image index missing"), {"version_id": 10}),
            (ApiError("outage", status_code=500, details="database connection failed"), {}),
            (AuthError("unauthorized", status_code=401), {}),
        ]:
            search.reset_mock()
            search.side_effect = exc
            with TestCase().assertRaises(RuntimeError):
                asyncio.run(find(query_text="a car", collection_name="city", **opts))
            assert search.await_count == 1

        search.reset_mock()
        search.side_effect = None
        asyncio.run(find(query_text="photos", collection_name="photos"))
        assert search.call_args.kwargs["mode"] == "img_file"
        assert search.call_args.kwargs["version_lancedb"] is None
        assert search.await_count == 1  # Empty results never cause version retries.
        legacy = main_mcp._build_handler("search_video", TOOL_REGISTRY["search_video"])
        asyncio.run(legacy(query_text="photos", group_name="photos"))
        assert search.call_args.kwargs["mode"] == "img_file"
        assert search.call_args.kwargs["version_lancedb"] is None
        assert search.call_args.kwargs["stream_name"] == ""
        asyncio.run(legacy(query_text="a car", group_name="city", mode=None))
        assert search.call_args.kwargs["mode"] == "vid_file"
        assert search.call_args.kwargs["version_lancedb"] == 10
        search.reset_mock()
        catalog["data"].append({"mode": "img_file", "group_name": "city", "lancedb_versions": ["v1"]})
        groups.return_value = GroupsResponse.model_validate(catalog)
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(query_text="a car", collection_name="city"))
        assert "multiple modes" in str(err.exception)
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(query_text="a car", collection_name="absent"))
        assert "Collection not found" in str(err.exception)
        assert search.await_count == 0
        async def slow_groups(**kw):
            await asyncio.sleep(0.05)
            return groups.return_value

        groups.side_effect = slow_groups
        cfg.tool_timeout = 0.001
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(query_text="a car", collection_name="city"))
        assert json.loads(str(err.exception))["status_code"] == 504
        assert search.await_count == 0


def test19():
    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.image_dir = os.path.join(dirtest, "find_save")
    os_path_cleanup(cfg.image_dir)
    row = {"mode": "vid_file", "group_name": "city", "stream_name": "rome", "modality": "vid_img", "filename": "walk in rome.mp4"}
    rows = [{**row, "ts_unix_13digits": "0000000018421"}, {**row, "ts_unix_13digits": "0000000019000"}]
    urls = AsyncMock(return_value={"records": [{"found": True, "url_pre_signed": "/u1", "input_index": 0}, {"found": False, "url_pre_signed": "", "input_index": 1}]})
    image = AsyncMock(return_value=image_fake_bytes("WebP"))
    cli = SimpleNamespace(images=SimpleNamespace(get_url_bulk=urls, get_image_from_url=image))
    image_dir = os.path.abspath(cfg.image_dir)
    out = asyncio.run(main_mcp._find_save_images(cli, {"data": rows}, 5, cfg))
    assert out["output_dir"] == image_dir
    assert out["saved_paths"] == [os.path.join(image_dir, "city", "rome", "walk_in_rome_0000000018421.jpg")]
    assert out["n_saved"] == 1 and out["n_failed"] == 1 and out["n_requested"] == 2
    assert os.path.isfile(out["saved_paths"][0])
    assert out["data"][0]["saved_path"] == out["saved_paths"][0]
    assert "saved_path" not in out["data"][1]
    image.assert_awaited_once_with(url_pre_signed="/u1")
    assert urls.call_args.kwargs["records"][0]["ts_unix_13digits"] == "0000000018421"
    assert tool_schema(TOOL_REGISTRY["find"])["properties"]["save_images"]["default"] == 0

    # Hits without a video filename (dashcam_v1) keep the hits and report why nothing was saved.
    urls.reset_mock()
    bare = asyncio.run(main_mcp._find_save_images(cli, {"data": [{**row, "filename": ""}]}, 3, cfg))
    assert bare["saved_paths"] == [] and bare["results"][0]["error"] == "missing_filename"
    assert len(bare["data"]) == 1
    urls.assert_not_awaited()
    # Records that come back in another order are matched by input_index.
    urls.return_value = {"records": [{"found": True, "url_pre_signed": "/u2", "input_index": 1}]}
    swapped = asyncio.run(main_mcp._find_save_images(cli, {"data": [{**row, "ts_unix_13digits": ts} for ts in ["0000000018421", "0000000019000"]]}, 5, cfg))
    assert [os.path.basename(path) for path in swapped["saved_paths"]] == ["walk_in_rome_0000000019000.jpg"]


def test20():
    """Image input is validated and converted before the SDK search call."""
    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    cfg.image_dir = os.path.join(dirtest, "image_find")
    raw = image_fake_bytes("PNG")
    b64 = base64.b64encode(raw).decode()
    path = os.path.abspath(os.path.join(dirtest, "query.png"))
    with open(path, "wb") as fh:
        fh.write(raw)
    groups = AsyncMock(return_value=dict_fake_catalog())
    search = AsyncMock(return_value={"data": [], "cnt_total": 0})
    image = AsyncMock(return_value=raw)
    cli = SimpleNamespace(collections=SimpleNamespace(list_groups=groups), searches=SimpleNamespace(search_video=search),
                          images=SimpleNamespace(get_image_from_url=image))
    with patch.object(main_mcp, "_ACTIVE_CFG", cfg), patch.object(main_mcp, "_ACTIVE_CLIENT", cli), patch.object(main_mcp, "_TARGET_CACHE", {}):
        find = main_mcp._build_handler("find", TOOL_REGISTRY["find"])
        for opts in [{"query_text": "red car"}, {"image_query": b64}, {"image_path": path}, {"image_url": "/vmx-signed"},
                     {"query_text": "red car", "image_path": path}]:
            out = json.loads(asyncio.run(find(collection_name="city", **opts)))
            assert out["data"] == []
            sent = search.call_args.kwargs
            assert "image_path" not in sent and "image_url" not in sent
            assert sent.get("image_query") == (b64 if any(key.startswith("image_") for key in opts) else None)
            assert b64 not in json.dumps(out)
        image.assert_awaited_once_with(url_pre_signed="/vmx-signed")
        count = search.await_count
        bad = [{}, {"query_text": " "}, {"image_query": "https://example.org/x"}, {"image_query": "!!!"},
               {"image_query": "data:image/png;base64," + b64}, {"image_query": base64.b64encode(b"junk").decode()},
               {"image_path": path + ".missing"}, {"image_query": b64, "image_path": path}, {"save_images": 21, "query_text": "x"}]
        for opts in bad:
            with TestCase().assertRaises(RuntimeError) as err:
                asyncio.run(find(collection_name="city", **opts))
            assert json.loads(str(err.exception))["status_code"] == 422
            assert b64 not in str(err.exception)
        assert search.await_count == count
        image.side_effect = ApiError("expired signed image", status_code=403, details="signature expired")
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(collection_name="city", image_url="/expired"))
        error = json.loads(str(err.exception))
        assert error["status_code"] == 403 and error["detail"] == "signature expired"
        assert search.await_count == count
        image.side_effect = None
        image.return_value = b""
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(collection_name="city", image_url="/empty"))
        assert json.loads(str(err.exception))["status_code"] == 422
        image.return_value = raw
        search.side_effect = ApiError("invalid image request", status_code=422, details={"input": b64})
        with TestCase().assertRaises(RuntimeError) as err:
            asyncio.run(find(collection_name="city", image_query=b64))
        assert b64 not in str(err.exception) and "<image bytes>" in str(err.exception)
        search.side_effect = None
        search.return_value = {"data": [dict_fake_frame(group_name="city")], "cnt_total": 1}
        cli.images.get_url_bulk = AsyncMock(return_value={"records": [{"input_index": 0, "found": True, "url_pre_signed": "/frame"}]})
        os_path_cleanup(cfg.image_dir)
        saved = json.loads(asyncio.run(find(collection_name="city", image_path=path, save_images=5)))
        assert saved["n_saved"] == 1 and saved["n_requested"] == 1
        assert saved["data"][0]["saved_path"] == saved["saved_paths"][0]


def test21():
    """Partial success, filtered indexes, duplicates, and reordered signing replies."""
    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    cfg.image_dir = os.path.join(dirtest, "direct_frames")
    os_path_cleanup(cfg.image_dir)
    row = dict_fake_frame()
    other = dict_fake_frame(group_name="documentary_world", stream_name="history", filename="Episode.mp4")
    records = [dict_fake_frame(filename=""), row, other, row, dict_fake_frame(filename="Look?01.mp4")]
    sign = AsyncMock(return_value={"records": [
        {"input_index": 2, "found": True, "url_pre_signed": "/u1"},
        {"input_index": 1, "found": True, "url_pre_signed": "/expired"},
        {"input_index": 0, "found": True, "url_pre_signed": "/u1"},
    ]})
    async def image_get(url_pre_signed):
        if url_pre_signed == "/expired":
            raise ApiError("expired", status_code=403, details="expired /expired")
        return image_fake_bytes("WebP")
    image = AsyncMock(side_effect=image_get)
    cli = SimpleNamespace(images=SimpleNamespace(get_url_bulk=sign, get_image_from_url=image))
    with patch.object(main_mcp, "_ACTIVE_CFG", cfg), patch.object(main_mcp, "_ACTIVE_CLIENT", cli):
        tool = main_mcp._build_handler("image_download_from_records", TOOL_REGISTRY["image_download_from_records"])
        out = json.loads(asyncio.run(tool(records=records)))
        assert [x["input_index"] for x in out["results"]] == list(range(5))
        assert out["n_requested"] == 5 and out["n_saved"] == 2 and out["n_failed"] == 3
        assert out["results"][0]["error"] == "missing_filename"
        assert out["results"][2]["error"]["status_code"] == 403
        assert "/expired" not in json.dumps(out)
        assert out["results"][4]["error"] == "path_conflict"
        assert out["saved_paths"][0] == out["saved_paths"][1]
        assert out["results"][1]["saved_path"] == out["results"][3]["saved_path"]
        assert sign.call_args.kwargs["records"] == [row, other, row]
        assert "/u1" not in json.dumps(out) and "url_pre_signed" not in json.dumps(out)
        sign.return_value = {"records": [{"input_index": 1, "found": True, "url_pre_signed": "/u1"},
                                         {"input_index": 0, "found": False}]}
        out = json.loads(asyncio.run(tool(records=[row, other])))
        assert out["results"][0]["error"] == "frame_not_found"
        assert out["results"][1]["saved_path"].endswith("documentary_world/history/Episode_1735689600123.jpg")
        image.side_effect = [asyncio.TimeoutError(), image_fake_bytes("WebP")]
        sign.return_value = {"records": [{"input_index": i, "found": True, "url_pre_signed": "/u1"} for i in range(2)]}
        timed = json.loads(asyncio.run(tool(records=[row, other])))
        assert timed["results"][0]["error"] == "timeout" and timed["n_saved"] == 1
        image.side_effect = image_get
        for name, opts in [("image_get_bulk_from_urls", {"urls": ["/u1"], "records": [row]}),
                           ("image_get_from_url", {"url_pre_signed": "/u1", "record": row})]:
            handler = main_mcp._build_handler(name, TOOL_REGISTRY[name])
            got = json.loads(asyncio.run(handler(**opts)))
            assert got["n_saved"] == 1
            assert got["saved_paths"][0] == out["output_dir"] + "/fashion_milan/runway/Look_01_1735689600123.jpg"
        bulk = main_mcp._build_handler("image_get_bulk_from_urls", TOOL_REGISTRY["image_get_bulk_from_urls"])
        for opts in [{"urls": ["/u1"]}, {"urls": ["/u1"], "records": [row, other]}]:
            with TestCase().assertRaises(RuntimeError) as err:
                asyncio.run(bulk(**opts))
            assert json.loads(str(err.exception))["status_code"] == 422
        sign.side_effect = ApiError("signing failure", status_code=500, details="lookup unavailable")
        failed = json.loads(asyncio.run(tool(records=[row, other])))
        assert failed["n_failed"] == 2 and failed["n_saved"] == 0


def test22():
    """Both search handlers pass the requested page size through compact/verbose output."""
    cfg = McpConfig.from_env(resolve_identity=False)
    cfg.cfg_error = ""
    hits = [dict_fake_frame(text_snippet="x" * 500, embedding=[1, 2]) for _ in range(50)]
    search = AsyncMock(return_value={"data": hits, "cnt_total": 101, "cnt_actual": 50})
    catalog = {"data": [{"mode": "vid_file", "group_name": "fashion_milan", "lancedb_versions": [0]}]}
    cli = SimpleNamespace(searches=SimpleNamespace(search_video=search), collections=SimpleNamespace(list_groups=AsyncMock(return_value=catalog)))
    with patch.object(main_mcp, "_ACTIVE_CFG", cfg), patch.object(main_mcp, "_ACTIVE_CLIENT", cli), patch.object(main_mcp, "_TARGET_CACHE", {}):
        server = build_server(cfg)
        tools = asyncio.run(server.list_tools())
        direct = next(tool for tool in tools if tool.name == "image_download_from_records")
        assert direct.inputSchema["properties"]["records"]["maxItems"] == 20
        with TestCase().assertRaises(Exception) as err:
            asyncio.run(server.call_tool("image_download_from_records", {"records": [dict_fake_frame()] * 21}))
        assert '"status_code": 422' in str(err.exception)
        assert search.await_count == 0
        for name, field in [("find", "collection_name"), ("search_video", "group_name")]:
            handler = main_mcp._build_handler(name, TOOL_REGISTRY[name])
            for verbose in [False, True]:
                out = json.loads(asyncio.run(handler(query_text="runway", **{field: "fashion_milan"}, limit=50, offset=5, verbose=verbose)))
                assert out["n_total_returned"] == 50 and out["requested_limit"] == 50 and out["offset"] == 5
                assert out["n_total"] == 101 and len(out["data"]) == 50
                assert search.call_args.kwargs["limit"] == 50 and search.call_args.kwargs["offset"] == 5
                assert all(row["frame_fetchable"] for row in out["data"])
                assert ("embedding" in out["data"][0]) == verbose
                assert "capped" not in out
            small = json.loads(asyncio.run(handler(query_text="runway", **{field: "fashion_milan"}, limit=3)))
            assert small["n_total_returned"] == 3
    broken = trim_search({"data": [dict_fake_frame(filename="", title="Looks like a filename.mp4"), dict_fake_frame(stream_name="")], "cnt_total": 2})
    assert broken["data"][0]["filename"] == "" and broken["data"][0]["frame_error"] == "missing_filename"
    assert broken["data"][1]["frame_error"] == "missing_stream"
    assert not any(row["frame_fetchable"] for row in broken["data"])


def test_all():
    os_makedirs(dirtest)
    test1()
    test1b()
    test1c()
    test1d()
    test2()
    test3()
    test4()
    test5()
    test6()
    test9()
    test10()
    test11()
    test12()
    test13()
    test14()
    test15()
    test16()
    test17()
    test18()
    test19()
    test20()
    test21()
    test22()


if __name__ == "__main__":
    import fire
    fire.Fire()
