"""Scan local episode telemetry for versioned failure candidates."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.mcp_server.robot_similar import scan
from src.mcp_server.utils import os_json_write


def run(collection_name, detector, output_path, robot_dir=None, thresholds_path=None):
    result = scan(collection_name,detector,robot_dir,thresholds_path)
    os_json_write(output_path,result)
    return result


if __name__ == "__main__":
    fire.Fire(run)
