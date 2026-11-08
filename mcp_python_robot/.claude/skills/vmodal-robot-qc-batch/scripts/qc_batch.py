"""Batch dry-run QC of robot episodes: validator verdicts, metadata completeness, collection outliers.

usage (from the MCP package root):
  .venv-robot/bin/python skills/vmodal-robot-qc-batch/scripts/qc_batch.py COLLECTION EPISODES_DIR DATASET_REV OUT_DIR
      [--format_id NAME@V] [--robot_dir DIR] [--only uid,uid]

EPISODES_DIR/<uid>/{cam_scene.mp4,cam_wrist.mp4?,frame_map.json,telemetry.jsonl,meta.json}
Calls robot_episode_upload(dry_run=True) per episode (no network, no SDK client) and prints ONE line per episode.
Writes OUT_DIR/qc_report.json, qc_table.md, qc_table.csv. Exit code 1 if any episode is reject/flag/exception.
"""
import argparse, asyncio, csv, json, os, statistics, sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.mcp_server.robot import robot_episode_upload  # noqa: E402

META_REQUIRED = {"task": str, "success": bool, "robot_id": str, "length": int}
META_RECOMMENDED = ("operator_id", "start_time", "source_dataset")


def robust_z(values):
    """Median/MAD z-scores; 0 when the spread is degenerate."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values) * 1.4826
    return [0.0 if mad < 1e-9 else (v - med) / mad for v in values]


def meta_issues(meta, n_frames):
    out = []
    for key, typ in META_REQUIRED.items():
        if key not in meta:
            out.append(f"meta.{key} missing")
        elif not isinstance(meta[key], typ) or (typ is str and not meta[key].strip()):
            out.append(f"meta.{key} wrong type/empty")
    if isinstance(meta.get("length"), int) and meta["length"] != n_frames:
        out.append(f"meta.length {meta['length']} != frame map {n_frames}")
    out += [f"meta.{k} recommended" for k in META_RECOMMENDED if k not in meta]
    return out


async def check_one(cfg, coll, ep, rev, format_id):
    uid = ep.name
    frames = json.loads((ep / "frame_map.json").read_text())
    meta = json.loads((ep / "meta.json").read_text())
    row = {"uid": uid, "frames": len(frames), "duration_s": round(len(frames) / 30, 2)}
    wrist = ep / "cam_wrist.mp4"
    try:
        r = await robot_episode_upload(cfg, coll, uid, str(ep / "cam_scene.mp4"), str(ep / "telemetry.jsonl"),
                                       str(ep / "frame_map.json"), str(ep / "meta.json"), rev,
                                       video_wrist=str(wrist) if wrist.exists() else None,
                                       format_id=format_id, dry_run=True)
        rep = r["check_report"]
        t, al = rep.get("time", {}), rep.get("align", {})
        row.update(status=r["status"], verdict=rep["verdict"], n_errors=len(rep["errors"]),
                   first_error=rep["errors"][0] if rep["errors"] else "", n_warnings=len(rep["warnings"]),
                   rate_hz=round(t.get("rate_hz_median") or 0, 1), gap_ms_max=round(t.get("gap_ms_max") or 0, 1),
                   align_dt_ms_max=round(al.get("dt_ms_max") or 0, 1), cmd_age_ms_max=round(al.get("cmd_age_ms_max") or 0, 1),
                   frames_no_tel=al.get("n_frames_no_telemetry"), check_report=r.get("check_report_path"))
    except Exception as exc:  # report and keep going: one broken episode must not hide the rest
        row.update(status="exception", verdict="exception", n_errors=1, first_error=f"{type(exc).__name__}: {str(exc)[:200]}")
    wdt = [abs(f.get("wrist_dt_ms", 0)) for f in frames]
    row["wrist_dt_ms_max"] = round(max(wdt), 1) if wdt else None
    row["wrist_repeat_pct"] = round(100 * sum(bool(f.get("wrist_repeated")) for f in frames) / len(frames), 1)
    issues = meta_issues(meta, len(frames))
    row["meta_errors"] = [i for i in issues if not i.endswith("recommended")]
    row["meta_hints"] = [i for i in issues if i.endswith("recommended")]
    row["meta_success"] = meta.get("success")
    return row


async def main(a):
    cfg = SimpleNamespace(robot_dir=a.robot_dir, upload_max_mb=int(os.environ.get("MCP_UPLOAD_MAX_MB", 5120)))
    eps = sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "telemetry.jsonl").exists())
    if a.only:
        keep = set(a.only.split(","))
        eps = [p for p in eps if p.name in keep]
    rows = []
    for ep in eps:
        row = await check_one(cfg, a.collection, ep, a.dataset_rev, a.format_id)
        rows.append(row)
        print(f"{row['uid']:<12} frames={row['frames']:<5} verdict={row['verdict']:<9} err={row['n_errors']} "
              f"meta_err={len(row['meta_errors'])} first_error={row['first_error'] or (row['meta_errors'][:1] or ['-'])[0]}", flush=True)
    ok = [r for r in rows if r["verdict"] != "exception"]
    # Collection-level outliers: technically valid episodes that look unlike their siblings.
    for key in ("duration_s", "gap_ms_max", "wrist_dt_ms_max", "align_dt_ms_max"):
        vals = [r.get(key) for r in ok]
        if len(ok) >= 5 and all(v is not None for v in vals):
            for r, z in zip(ok, robust_z(vals)):
                if abs(z) > a.z:
                    r.setdefault("outliers", []).append(f"{key}={r[key]} (z={z:+.1f})")
    summary = {"n": len(rows), "verdicts": {v: sum(r["verdict"] == v for r in rows) for v in sorted({r["verdict"] for r in rows})},
               "n_meta_errors": sum(bool(r["meta_errors"]) for r in rows),
               "outliers": {r["uid"]: r["outliers"] for r in rows if r.get("outliers")},
               "collection": a.collection, "dataset_rev": a.dataset_rev, "format_id": a.format_id or "collection binding"}
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "qc_report.json").write_text(json.dumps({"summary": summary, "episodes": rows}, indent=1))
    cols = ["uid", "frames", "duration_s", "verdict", "n_errors", "first_error", "rate_hz", "gap_ms_max",
            "align_dt_ms_max", "cmd_age_ms_max", "wrist_dt_ms_max", "wrist_repeat_pct", "meta_success"]
    with open(out / "qc_table.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols + ["outliers", "meta_errors"])
        for r in rows:
            w.writerow([r.get(c, "") for c in cols] + ["; ".join(r.get("outliers", [])), "; ".join(r["meta_errors"])])
    md = ["| " + " | ".join(cols + ["outliers"]) + " |", "|" + "---|" * (len(cols) + 1)]
    md += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " | " + "; ".join(r.get("outliers", [])) + " |" for r in rows]
    (out / "qc_table.md").write_text("\n".join(md) + "\n")
    print("SUMMARY", json.dumps(summary))
    print("wrote", out / "qc_report.json")
    return 0 if all(r["verdict"] == "pass" for r in rows) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("collection"); p.add_argument("episodes_dir"); p.add_argument("dataset_rev"); p.add_argument("out_dir")
    p.add_argument("--format_id", default=None, help="NAME@VERSION; default = the collection's bound format")
    p.add_argument("--robot_dir", default=os.environ.get("MCP_ROBOT_DIR", str(ROOT / "ztmp/mcp_robot")))
    p.add_argument("--only", default="", help="comma-separated episode uids")
    p.add_argument("--z", type=float, default=3.5, help="robust z threshold for collection outliers")
    sys.exit(asyncio.run(main(p.parse_args())))
