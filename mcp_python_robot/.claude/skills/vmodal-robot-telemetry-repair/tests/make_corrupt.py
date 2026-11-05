"""Build corrupted copies of real episodes to test telemetry repair.

usage: python make_corrupt.py EPISODES_DIR OUT_DIR SRC_UID [SRC_UID2]
SRC_UID  -> <uid>_corrupt: every defect is repairable (shuffle, duplicates, NaN run, 90 ms gap,
            quaternion scale + sign flips, small gripper overshoot).
SRC_UID2 -> <uid2>_broken: a 400 ms gap and a 20-row NaN run that must be REPORTED, not repaired.
"""
import json, os, random, shutil, sys
from pathlib import Path


def copy_ep(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.name != "telemetry.jsonl":
            shutil.copy2(f, dst / f.name)
    return [json.loads(l) for l in (src / "telemetry.jsonl").read_text().splitlines() if l.strip()]


def write(dst, rows, uid):
    (dst / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for name in ("meta.json", "frame_map.json"):
        d = json.loads((dst / name).read_text())
        if isinstance(d, list):
            for r in d:
                r["episode_uid"] = uid
        else:
            d["episode_uid"] = uid
        (dst / name).write_text(json.dumps(d))


def main(src_dir, out_dir, uid, uid2=None):
    random.seed(7)
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    dst = out_dir / f"{uid}_corrupt"
    rows = copy_ep(src_dir / uid, dst)
    del rows[300:306]                                   # ~90 ms gap
    for i in range(100, 103):
        rows[i]["q"][2] = float("nan")                  # 3-row NaN run
    for i in range(150, 200):
        rows[i]["ee_quat"] = [v * 1.01 for v in rows[i]["ee_quat"]]   # off-norm
    for i in range(400, 420):
        rows[i]["ee_quat"] = [-v for v in rows[i]["ee_quat"]]         # sign flips
    for i in range(500, 504):
        rows[i]["cmd_gripper"] = 1.004                  # small overshoot
    rows += [dict(rows[i]) for i in (50, 51, 52, 53, 54)]             # duplicates
    seg = rows[200:220]; random.shuffle(seg); rows[200:220] = seg    # out of order
    write(dst, rows, f"{uid}_corrupt")
    print("wrote", dst)
    if uid2:
        dst2 = out_dir / f"{uid2}_broken"
        rows = copy_ep(src_dir / uid2, dst2)
        del rows[200:230]                               # ~400 ms gap
        for i in range(300, 320):
            rows[i]["gripper"] = float("nan")           # 20-row NaN run
        write(dst2, rows, f"{uid2}_broken")
        print("wrote", dst2)


if __name__ == "__main__":
    main(*sys.argv[1:])
