from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
import re
from src.utils.util_log import log_info, log_error, log_trace, log_warning


def os_read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def os_write_text(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def str_sdk_version(path: str = "") -> str:
    root = os.path.abspath(os.path.dirname(__file__))
    path = path or os.path.join(root, "..", "sdk_python", "src", "vmodal", "__init__.py")
    text = os_read_text(path)
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise ValueError("SDK __version__ was not found")
    return match.group(1)


def str_sdk_requirement(version: str) -> str:
    major = int(version.split(".", 1)[0])
    return f"vmodal>={version},<{major + 1}.0.0"


def sdk_version_sync(
    check: bool = False,
    sdk_path: str = "",
    mcp_path: str = "",
) -> Dict[str, Any]:
    root = os.path.abspath(os.path.dirname(__file__))
    mcp_path = mcp_path or os.path.join(root, "pyproject.toml")
    version = str_sdk_version(sdk_path)
    requirement = str_sdk_requirement(version)
    text = os_read_text(mcp_path)
    updated, count = re.subn(r'"vmodal>=[^"]+"', f'"{requirement}"', text, count=1)
    if count != 1:
        raise ValueError("MCP vmodal dependency was not found")
    changed = updated != text
    if check and changed:
        raise ValueError(f"MCP dependency drift: expected {requirement}")
    if changed:
        os_write_text(mcp_path, updated)
    out = {"sdk_version": version, "requirement": requirement, "changed": changed}
    log_info("sdk_version_sync", out)
    return out


if __name__ == "__main__":
    fire.Fire()
