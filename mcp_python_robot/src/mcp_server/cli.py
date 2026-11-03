"""VModal CLI extension with a packaged upload/index/search smoke test."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_copytree
import time

from vmodal.cli import CliApp


MODE = "vid_file"
STREAM = "astream"
INDEX_TYPE = "vid_img_emb"
MODALITY_INDEX = "vid_img_emb"
MODALITY_RAW = "vid_raw"
OK_STATUS = {"success", "succeeded", "done", "completed", "ok"}
FAIL_STATUS = {"failed", "failure", "error", "cancelled", "canceled", "dead_letter"}


def str_api_key(api_key: str = "") -> str:
    return (
        api_key
        or os.environ.get("VMODAL_API_KEY", "")
        or os.environ.get("api_key", "")
        or os.environ.get("TEST_CLIENT_CLERK_USER_API_TOKEN", "")
    )


def os_assets_copy(folder: str = "") -> str:
    src = os.path.join(os.path.dirname(__file__), "assets")
    dst = os.path.join(os.path.abspath(folder or os.getcwd()), "assets")
    return os_copytree(src, dst)


def os_test_video_path(folder: str = "") -> str:
    path = os.path.join(os_assets_copy(folder), "test_video_20_frames.mp4")
    if not os.path.isfile(path):
        raise FileNotFoundError("Copied test video is missing: %s" % path)
    return path


def obj_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return dict(obj)
    return dict(getattr(obj, "__dict__", {}) or {})


def str_status(obj: Any) -> str:
    return str(obj_dict(obj).get("status") or "").strip().lower()


def int_version_lancedb(status_obj: Any) -> int:
    data = obj_dict(status_obj)
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    vals = [data.get("version_lancedb"), data.get("version"), result.get("version_lancedb"), result.get("version")]
    for val in vals:
        text = str(val or "").strip().lower().lstrip("v")
        if text.isdigit():
            return int(text)
    return 0


def int_indexed_frames(status_obj: Any) -> int:
    data = obj_dict(status_obj)
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    pre = result.get("pre_indexation_vid_img_emb")
    if not isinstance(pre, dict):
        return 0
    return int(pre.get("n_frame") or 0)


def str_test_group() -> str:
    tail = str(int(time.time() * 1000))[-8:]
    return "mcp_test_%s" % tail


def run_test_flow(
    client: Any,
    group_name: str = "",
    query_text: str = "colorful test pattern",
    timeout_sec: int = 1800,
    poll_sec: int = 10,
) -> Dict[str, Any]:
    group_name = group_name or str_test_group()
    video_path = os_test_video_path()
    upload = obj_dict(client.collections.video_upload(
        filepath_local=video_path,
        collection_name=group_name,
        sub_collection_name=STREAM,
        mode=MODE,
        modality=MODALITY_RAW,
        re_process=True,
    ))
    log_info("test upload complete", group_name)

    job = obj_dict(client.indexes.create_index(
        mode=MODE,
        group_name=group_name,
        stream_name=STREAM,
        index_type=INDEX_TYPE,
        modality=MODALITY_INDEX,
        insert_mode="append",
        create_index=True,
        version="new_version",
        re_process=True,
        dry_run=False,
    ))
    job_id = str(job.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError("Index creation did not return job_id: %s" % job)

    end_time = time.time() + int(timeout_sec)
    status: Dict[str, Any] = {}
    while time.time() <= end_time:
        status = obj_dict(client.indexes.index_status(job_id=job_id))
        state = str_status(status)
        log_info("test index status", job_id, state)
        if state in OK_STATUS:
            break
        if state in FAIL_STATUS:
            raise RuntimeError("Indexing failed: %s" % status)
        time.sleep(max(1, int(poll_sec)))
    else:
        raise RuntimeError("Indexing timed out after %s seconds: %s" % (timeout_sec, status))

    frame_count = int_indexed_frames(status)
    if frame_count != 20:
        raise RuntimeError("Expected 20 indexed frames, got %s: %s" % (frame_count, status))
    version = int_version_lancedb(status)
    search = obj_dict(client.searches.search_video(
        query_text=query_text,
        mode=MODE,
        group_name=group_name,
        stream_name=STREAM,
        search_sources=["image"],
        search_combine_mode="union",
        limit=3,
        offset=0,
        text_emb_score_min=0.0,
        image_emb_score_min=0.0,
        version_lancedb=version,
    ))
    if not list(search.get("data") or []):
        raise RuntimeError("Search returned no frames: %s" % search)
    log_info("test search complete", group_name, query_text)
    return {
        "ok": True,
        "video_path": video_path,
        "frame_count": frame_count,
        "group_name": group_name,
        "upload": upload,
        "job": job,
        "status": status,
        "version_lancedb": version,
        "search": search,
    }


class VmodalCli(CliApp):
    def __init__(
        self,
        base_url: str = "",
        user_id: str = "",
        tenant_id: str = "",
        email: str = "",
        token: str = "",
        api_key: str = "",
        timeout: float = 30,
    ):
        key = str_api_key(api_key)
        if not (token or key):
            raise SystemExit("API key required: export api_key=PUT_API_KEY_HERE (VMODAL_API_KEY also works), then re-run.")
        super().__init__(
            base_url=base_url,
            user_id=user_id,
            tenant_id=tenant_id,
            email=email,
            token=token or key,
            timeout=timeout,
        )

    def test(
        self,
        group_name: str = "",
        query_text: str = "colorful test pattern",
        timeout_sec: int = 1800,
        poll_sec: int = 10,
    ) -> Dict[str, Any]:
        """Upload the packaged 20-frame video, index it, and verify search."""
        return run_test_flow(
            self.client,
            group_name=group_name,
            query_text=query_text,
            timeout_sec=timeout_sec,
            poll_sec=poll_sec,
        )


def main():
    fire.Fire(VmodalCli)


if __name__ == "__main__":
    main()
