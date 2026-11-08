"""Build corrupted copies of clean 100 Hz episodes to test telemetry repair.

usage: python make_corrupt.py EPISODES_DIR OUT_DIR SRC_UID [SRC_UID2]
SRC_UID  -> <uid>_corrupt: shuffle, duplicates, 3-row NaN run, 70 ms gap,
            quaternion scale + sign flips, small gripper overshoot.
SRC_UID2 -> <uid2>_broken: a 310 ms gap and a 20-row NaN run, not repairable.

At least 80 telemetry samples (excluding an optional JSONL header) are required.
Shorter or non-uniform/non-100-Hz inputs are rejected before writing output;
defects are never silently omitted or shortened below the repair limits.
"""
import copy
import json
import random
import shutil
import sys
from pathlib import Path


MIN_ROWS = 80


def read_episode(src):
    records = [json.loads(line) for line in (src / "telemetry.jsonl").read_text().splitlines() if line.strip()]
    header = records.pop(0) if records and "t_ns" not in records[0] else None
    if len(records) < MIN_ROWS:
        raise ValueError(f"{src.name}: need at least {MIN_ROWS} telemetry rows; got {len(records)}")
    times = [r.get("t_ns") for r in records]
    if any(type(t) is not int for t in times) or any(b - a != 10_000_000 for a, b in zip(times, times[1:])):
        raise ValueError(f"{src.name}: fixture requires sorted, uniform 100 Hz t_ns samples")
    return header, records


def corrupt(rows, broken=False):
    """Place bounded defects proportionally, without changing the input rows."""
    rows = copy.deepcopy(rows)
    if len(rows) < MIN_ROWS:
        raise ValueError(f"need at least {MIN_ROWS} telemetry rows")
    if broken:
        start = len(rows) // 4
        del rows[start:start + 30]  # 31 sample intervals = 310 ms at 100 Hz
        start = max(start + 1, min(int(len(rows) * .65), len(rows) - 21))
        for row in rows[start:start + 20]:
            row["gripper"] = float("nan")
        return rows
    start = int(len(rows) * .55)
    del rows[start:start + 6]  # 7 sample intervals = 70 ms at 100 Hz
    n = len(rows)
    for row in rows[int(n * .15):int(n * .15) + 3]:
        row["q"][2] = float("nan")
    for row in rows[int(n * .25):int(n * .25) + min(50, n // 10)]:
        row["ee_quat"] = [v * 1.01 for v in row["ee_quat"]]
    for row in rows[int(n * .75):int(n * .75) + min(20, n // 20)]:
        row["ee_quat"] = [-v for v in row["ee_quat"]]
    for row in rows[int(n * .9):int(n * .9) + 4]:
        row["cmd_gripper"] = 1.004
    duplicates = copy.deepcopy(rows[int(n * .05):int(n * .05) + 5])
    start, size = int(n * .4), min(20, n // 10)
    seg = rows[start:start + size]
    random.Random(7).shuffle(seg)
    if seg == rows[start:start + size]:
        seg.reverse()  # guarantee an out-of-order segment
    rows[start:start + size] = seg
    return rows + duplicates


def write_episode(src, dst, header, rows):
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and f.name != "telemetry.jsonl":
            shutil.copy2(f, dst / f.name)
    # Also support the bundled layout where meta lives beside episode folders.
    if not (dst / "meta.json").exists():
        shutil.copy2(src.parent / "meta" / f"{src.name}.json", dst / "meta.json")
    records = rows
    if header is not None:
        header = dict(header, episode_uid=dst.name)
        records = [header] + rows
    (dst / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    for name in ("meta.json", "frame_map.json"):
        d = json.loads((dst / name).read_text())
        for r in d if isinstance(d, list) else [d]:
            r["episode_uid"] = dst.name
        (dst / name).write_text(json.dumps(d))


def main(src_dir, out_dir, uid, uid2=None):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    jobs = [(uid, False)] + ([(uid2, True)] if uid2 else [])
    # Validate all requested inputs before creating any fixture.
    inputs = [(name, broken, *read_episode(src_dir / name)) for name, broken in jobs]
    for name, broken, header, rows in inputs:
        dst = out_dir / f"{name}_{'broken' if broken else 'corrupt'}"
        write_episode(src_dir / name, dst, header, corrupt(rows, broken))
        print("wrote", dst)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except ValueError as exc:
        sys.exit(str(exc))
