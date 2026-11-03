from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import shutil
from pathlib import Path
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning


def os_path_cleanup(dirpath: str) -> str:
    shutil.rmtree(dirpath, ignore_errors=True)
    return dirpath


def os_copytree(src: str, dst: str) -> str:
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


def os_makedirs(dir_or_file: str):
    path = os.path.abspath(dir_or_file)
    name = os.path.basename(path)
    if "." in name:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
    else:
        os.makedirs(path, exist_ok=True)


def os_read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def os_write_text(path: str, text: str) -> str:
    os_makedirs(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def os_read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()
