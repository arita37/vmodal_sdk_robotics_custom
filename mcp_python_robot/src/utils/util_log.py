from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire


def _msg(*s, **kw) -> str:
    ss = ",".join([str(xi) for xi in s])
    if kw:
        skw = ",".join([f"{k}:{v}" for k, v in kw.items()])
        ss = f"{ss},{skw}" if ss else skw
    return ss.replace(str(os.getcwd()), ".")


def log_info(*s, **kw):
    print(_msg(*s, **kw), file=sys.stderr, flush=True)


def log_warning(*s, **kw):
    print(f"warning,{_msg(*s, **kw)}", file=sys.stderr, flush=True)


def log_trace(*s, **kw):
    if str(os.environ.get("VMODAL_TRACE", "")).strip():
        print(f"trace,{_msg(*s, **kw)}", file=sys.stderr, flush=True)


def log_error(*s, **kw):
    print(f"error,{_msg(*s, **kw)}", file=sys.stderr, flush=True)
