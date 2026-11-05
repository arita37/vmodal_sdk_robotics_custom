"""Write new candidate or explicit human-review files; never edit customer tags."""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from src.mcp_server.robot_similar import write_from_file, review_tags


if __name__ == "__main__":
    fire.Fire({"candidates":write_from_file,"review":review_tags})
