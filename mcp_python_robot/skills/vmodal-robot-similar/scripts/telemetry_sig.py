"""Rank telemetry windows by named-field signature distance."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.mcp_server.robot_similar import signature_distances, fuse
from src.mcp_server.utils import os_json_read, os_json_write


def run(path, output_path):
    data = os_json_read(path)
    out = {"distances":signature_distances(data["anchor"],data["candidates"],data["spec"],data["fields"],data.get("steps",32))}
    if "searches" in data:
        out["candidates"] = fuse(data["searches"],data["telemetry_hits"],out["distances"])
    os_json_write(output_path,out)
    return out


if __name__ == "__main__":
    fire.Fire(run)
