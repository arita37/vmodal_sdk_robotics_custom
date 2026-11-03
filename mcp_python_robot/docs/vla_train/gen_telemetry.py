"""Generate sample telemetry JSONL (vmodal_robot_telemetry/1, see 01_doc.md C2).

Line 1 = header, lines 2.. = rows at 100 Hz. Values anchored on 00_doc.md sample
row: episode 412, frame 120, timestamp 4.0012 s.

Usage (from uinterface/mcp_python_robot):
    export PYTHONPATH=$(pwd)
    python docs/vla_train/gen_telemetry.py gen
    python docs/vla_train/gen_telemetry.py gen --n=100 --out=ztmp/telemetry.jsonl
"""
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
import json, math
from src.utils.util_log import log_info, log_error, log_trace, log_warning

DIR_HERE = os.path.dirname(os.path.abspath(__file__))

HDR = {"schema": "vmodal_robot_telemetry/1",
       "episode_uid": "ep_000412", "time_base": "t_ns_utc_host_offset_corrected",
       "rate_hz": 100,
       "fields": [
           {"name": "q", "names": ["j1", "j2", "j3", "j4", "j5", "j6"], "unit": "rad"},
           {"name": "current", "names": ["j1", "j2", "j3", "j4", "j5", "j6"], "unit": "A", "note": "controller estimate"},
           {"name": "gripper", "unit": "0_open_1_closed"},
           {"name": "ee_pos", "names": ["x", "y", "z"], "unit": "m"},
           {"name": "ee_quat", "names": ["qx", "qy", "qz", "qw"]},
           {"name": "cmd_q", "names": ["j1", "j2", "j3", "j4", "j5", "j6"], "unit": "rad"},
           {"name": "cmd_gripper", "unit": "0_open_1_closed"}]}

Q0   = [0.214, -0.402, -0.688, 0.011, 1.093, 0.226]
DQ   = [0.0012, -0.0016, 0.0017, 0.0001, -0.0009, 0.0012]   # per 10 ms
LEAD = [0.005, -0.007, 0.007, 0.0, -0.004, 0.005]           # command ahead of state
C0   = [0.42, 2.85, 1.96, 0.18, 0.64, 0.09]
P0, DP = [0.312, 0.061, 0.184], [0.0003, 0.0006, -0.0009]
R0, PT0, Y0, DY = 3.129, 0.021, 0.207, 0.0012
T0 = 1761130004001200000


def quat(r, p, y):
    """Extrinsic XYZ Euler (rad) -> quaternion [qx, qy, qz, qw]."""
    cr, sr = math.cos(r / 2), math.sin(r / 2)
    cp, sp = math.cos(p / 2), math.sin(p / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    return [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def rows_make(n=10, t0=T0):
    """Return n telemetry rows, 10 ms apart."""
    rows = []
    for i in range(n):
        q   = [round(a + i * d, 4) for a, d in zip(Q0, DQ)]
        cur = [round(c + 0.03 * math.sin(i * 0.9 + k), 3) for k, c in enumerate(C0)]
        pos = [round(a + i * d, 4) for a, d in zip(P0, DP)]
        qu  = [round(v, 5) for v in quat(R0, PT0, Y0 + i * DY)]
        cmd = [round(a + b, 4) for a, b in zip(q, LEAD)]
        rows.append({"t_ns": t0 + i * 10_000_000, "q": q, "current": cur, "gripper": 0.0,
                     "ee_pos": pos, "ee_quat": qu, "cmd_q": cmd, "cmd_gripper": 0.0})
    return rows


def gen(n=10, out=None):
    """Write header + n rows to out (default: telemetry.jsonl next to this script)."""
    out = out or os.path.join(DIR_HERE, "telemetry.jsonl")
    with open(out, "w") as f:
        for r in [HDR] + rows_make(int(n)):
            f.write(json.dumps(r, separators=(", ", ": ")) + "\n")
    log_info(f"saved {n} rows: {out}")
    return out


if __name__ == '__main__':
    fire.Fire()
