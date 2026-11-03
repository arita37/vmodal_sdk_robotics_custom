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


def test_all():
    os_path_cleanup(dirtest)
    test1()
    test2()
    test3()
    test4()
    test5()
    log_info("test_utils: all passed")


if __name__ == "__main__":
    import fire
    fire.Fire()
