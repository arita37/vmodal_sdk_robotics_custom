"""Run the shared planted-event and C8 contract tests from the skill directory."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.utils.util_base import os_makedirs, os_path_cleanup
from src.mcp_server.robot_similar import telemetry_detect, signature_distances, candidate_tags
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/"tests"))
from test_robot_similar import test1, test2, test3, test4, test5, test6

dirtest="ztmp/ztests"


def test_all():
    test1(); test2(); test3(); test4(); test5(); test6()


if __name__ == "__main__":
    fire.Fire()
