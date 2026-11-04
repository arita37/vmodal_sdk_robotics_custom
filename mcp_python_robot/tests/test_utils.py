from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
import subprocess
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from utils import os_read_text, os_write_text, sdk_version_sync, str_sdk_requirement, str_sdk_version
from utils_datafake import str_fake_mcp_pyproject, str_fake_sdk_init

dirtest = "ztmp/ztests"


def test1():
    os_makedirs(dirtest)
    path = os.path.join(dirtest, "sdk_init.py")
    os_write_text(path, str_fake_sdk_init("1.2.3"))
    assert str_sdk_version(path) == "1.2.3"
    assert str_sdk_requirement("1.2.3") == "vmodal>=1.2.3,<2.0.0"


def test2():
    os_makedirs(dirtest)
    sdk_path = os.path.join(dirtest, "sdk_sync_init.py")
    mcp_path = os.path.join(dirtest, "mcp_pyproject.toml")
    os_write_text(sdk_path, str_fake_sdk_init("1.4.2"))
    os_write_text(mcp_path, str_fake_mcp_pyproject("1.0.0"))
    out = sdk_version_sync(sdk_path=sdk_path, mcp_path=mcp_path)
    assert out["sdk_version"] == "1.4.2"
    assert out["requirement"] == "vmodal>=1.4.2,<2.0.0"
    assert out["changed"] is True
    assert '"vmodal>=1.4.2,<2.0.0"' in os_read_text(mcp_path)


def test3():
    sdk_path = os.path.join(dirtest, "sdk_sync_init.py")
    mcp_path = os.path.join(dirtest, "mcp_pyproject.toml")
    out = sdk_version_sync(check=True, sdk_path=sdk_path, mcp_path=mcp_path)
    assert out["changed"] is False


def test4():
    sdk_path = os.path.join(dirtest, "sdk_drift_init.py")
    mcp_path = os.path.join(dirtest, "mcp_drift_pyproject.toml")
    os_write_text(sdk_path, str_fake_sdk_init("1.5.0"))
    os_write_text(mcp_path, str_fake_mcp_pyproject("1.0.0"))
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out = subprocess.run(
        [
            sys.executable,
            os.path.join(root, "utils.py"),
            "sdk_version_sync",
            "--check=true",
            f"--sdk_path={os.path.abspath(sdk_path)}",
            f"--mcp_path={os.path.abspath(mcp_path)}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0
    assert "MCP dependency drift" in out.stderr
    assert '"vmodal>=1.0.0,<2.0.0"' in os_read_text(mcp_path)


def test5():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    repo = os.path.abspath(os.path.join(root, "..", ".."))
    install = os_read_text(os.path.join(root, "install.sh"))
    assert install.count("sdk_version_sync --check=true") == 2
    path = os.path.join(repo, ".github", "workflows", "sdk_mcp_robot_test_release.yml")
    if not os.path.exists(path):
        # Source distributions intentionally omit the monorepo's GitHub directory.
        return
    workflow = os_read_text(path)
    assert workflow.index("Check SDK and MCP version contract") < workflow.index("Install MCP")
    assert 'python utils.py sdk_version_sync --check=true' in workflow


def test6():
    """Cuts retain exact frame counts, zero-based timestamps, and 30 fps duration."""
    import json
    from pathlib import Path
    from src.mcp_server.utils import os_video_cut, os_video_probe

    source = Path("data/robot/lerobot/videos/observation.images.cam_scene/chunk-000/file-000.mp4")
    for index, (start, length) in enumerate(((0, 60), (2, 60), (1 / 30, 17), (0, 1))):
        target = Path(dirtest) / "video_cuts" / f"cut_{index}.mp4"
        os_video_cut(source, target, start, length)
        assert os_video_probe(target) == {"n_frames_decoded": length, "fps": 30.0, "cfr": True}
        info = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=start_time,duration:frame=best_effort_timestamp_time",
            "-of", "json", str(target),
        ], check=True, capture_output=True, text=True).stdout)
        stream = info["streams"][0]
        assert abs(float(stream["start_time"])) < 0.000001
        assert abs(float(stream["duration"]) - length / 30) < 0.000001
        assert len(info["frames"]) == length
        for frame, row in enumerate(info["frames"]):
            assert abs(float(row["best_effort_timestamp_time"]) - frame / 30) < 0.000001


def test_all():
    os_path_cleanup(dirtest)
    test1()
    test2()
    test3()
    test4()
    test5()
    test6()
    log_info("test_utils: all passed")


if __name__ == "__main__":
    import fire
    fire.Fire()
