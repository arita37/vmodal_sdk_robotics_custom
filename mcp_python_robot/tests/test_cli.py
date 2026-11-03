from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from unittest.mock import patch
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup

from src.mcp_server.cli import VmodalCli, os_test_video_path, str_api_key

dirtest = "ztmp/ztests"


def test1():
    assets = os.path.join(dirtest, "assets")
    os_path_cleanup(assets)
    path = os_test_video_path(dirtest)
    assert path == os.path.abspath(os.path.join(assets, "test_video_20_frames.mp4"))
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 10_000


def test2():
    with patch.dict(os.environ, {"VMODAL_API_KEY": "ak_cli", "api_key": ""}):
        assert str_api_key() == "ak_cli"


def test4():
    """No key: one readable line, not a traceback."""
    names = ["VMODAL_API_KEY", "api_key", "TEST_CLIENT_CLERK_USER_API_TOKEN"]
    with patch.dict(os.environ, {name: "" for name in names}):
        try:
            VmodalCli()
        except SystemExit as exc:
            assert "API key required" in str(exc)
        else:
            raise AssertionError("VmodalCli() without a key must exit")


def test3(group_name: str = "", timeout_sec: int = 1800, poll_sec: int = 10):
    app = VmodalCli()
    out = app.test(group_name=group_name, timeout_sec=timeout_sec, poll_sec=poll_sec)
    assert out["ok"] is True
    assert out["frame_count"] == 20
    assert out["job"].get("job_id")
    assert out["search"].get("data")
    return out


def test_all(live: bool = False):
    os_makedirs(dirtest)
    test1()
    test2()
    test4()
    if live:
        test3()
    log_info("test_cli: all passed")


if __name__ == "__main__":
    import fire
    fire.Fire()
