"""Audit camera/telemetry synchronization per episode and estimate video<->telemetry lag from motion.

usage (from the MCP package root):
  audit: .venv-robot/bin/python skills/vmodal-robot-sync-audit/scripts/sync_audit.py audit EPISODES_DIR OUT_DIR [--only uid,..]
  fix:   .venv-robot/bin/python skills/vmodal-robot-sync-audit/scripts/sync_audit.py shift EPISODES_DIR OUT_DIR --offset_ms X [--only ...]

audit: decoded frames vs frame map, 30/1 CFR, wrist offsets/repeats, telemetry coverage of the
video, and lag_ms = shift that best aligns image motion energy with robot speed (positive: telemetry
shows motion X ms AFTER the video; correction = shift telemetry by -X).
shift: writes copies whose telemetry t_ns are moved by --offset_ms (applied as t_ns += offset);
everything else is hard-linked. Re-run vmodal-robot-qc-batch afterwards.
"""
import argparse, json, os, shutil, statistics, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.mcp_server.utils import os_video_probe  # noqa: E402

W, H = 80, 60
TOL_MS = 1000 / 60      # half a frame, same as the validator's frame_tol_ms


def motion_energy(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    return np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)), len(f)


def robot_speed(rows):
    t = np.array([r["t_ns"] for r in rows], dtype=np.float64)
    key = "q" if "q" in rows[0] else "ee_pos"
    x = np.array([r[key] for r in rows], dtype=float).reshape(len(rows), -1)
    v = np.linalg.norm(np.diff(x, axis=0), axis=1) / (np.diff(t) / 1e9)
    v = np.convolve(v, np.ones(5) / 5, mode="same")           # ~65 ms smoothing at 76 Hz
    return (t[1:] + t[:-1]) / 2, v, key


def best_lag(t_frames, energy, t_tel, speed, max_ms=1500, step_ms=10, band=0.05):
    """Lag maximizing corr(energy(t), speed(t+lag)); interval = lags whose corr is within `band` of the peak."""
    tm = (t_frames[1:] + t_frames[:-1]) / 2                     # energy[i] is between frame i and i+1
    if len(tm) < 90 or np.std(energy) < 1e-6:          # < 3 s of video: too little motion to estimate
        return None, None, None
    e = (energy - energy.mean()) / (energy.std() + 1e-9)
    lags, cors = [], []
    for lag in range(-max_ms, max_ms + 1, step_ms):
        s = np.interp(tm + lag * 1e6, t_tel, speed)
        if np.std(s) < 1e-9:
            continue
        lags.append(lag); cors.append(float(np.mean(e * (s - s.mean()) / s.std())))
    if not cors:
        return None, None, None
    k = int(np.argmax(cors))
    lo = k
    while lo > 0 and cors[lo - 1] >= cors[k] - band:
        lo -= 1
    hi = k
    while hi < len(cors) - 1 and cors[hi + 1] >= cors[k] - band:
        hi += 1
    return lags[k], cors[k], [lags[lo], lags[hi]]


def longest_run(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def audit_one(ep):
    frames = json.loads((ep / "frame_map.json").read_text())
    rows = [json.loads(l) for l in (ep / "telemetry.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if "t_ns" in r]
    ts = np.array([f["t_scene_ns"] for f in frames], dtype=np.float64)
    tw = np.array([f["t_wrist_ns"] for f in frames], dtype=np.float64)
    tt, sp, key = robot_speed(rows)
    rec = {"uid": ep.name, "frames": len(frames), "issues": []}
    for cam, tcol in (("cam_scene", ts), ("cam_wrist", tw)):
        p = ep / f"{cam}.mp4"
        if not p.exists():
            continue
        probe = os_video_probe(p)
        energy, n = motion_energy(p)
        lag, cor, ci = best_lag(tcol, energy, tt, sp)
        rec[cam] = {"decoded": probe["n_frames_decoded"], "cfr": probe["cfr"],
                    "lag_ms": lag, "lag_ci_ms": ci, "corr": None if cor is None else round(cor, 2)}
        if probe["n_frames_decoded"] != len(frames):
            rec["issues"].append(f"{cam}: decoded {probe['n_frames_decoded']} != frame map {len(frames)}")
        if not probe["cfr"]:
            rec["issues"].append(f"{cam}: not 30/1 CFR")
    wdt = np.array([f["wrist_dt_ms"] for f in frames])
    rep = [bool(f["wrist_repeated"]) for f in frames]
    rec.update(wrist_dt_ms_mean=round(float(np.abs(wdt).mean()), 1), wrist_dt_ms_max=round(float(np.abs(wdt).max()), 1),
               wrist_repeat_pct=round(100 * sum(rep) / len(rep), 1), wrist_repeat_longest=longest_run(rep),
               lead_ms=round((ts[0] - rows[0]["t_ns"]) / 1e6, 1), tail_ms=round((rows[-1]["t_ns"] - ts[-1]) / 1e6, 1),
               speed_from=key)
    if rec["lead_ms"] < -TOL_MS:
        rec["issues"].append(f"video starts {-rec['lead_ms']} ms before telemetry")
    if rec["tail_ms"] < -TOL_MS:
        rec["issues"].append(f"video ends {-rec['tail_ms']} ms after telemetry")
    if rec["wrist_repeat_longest"] >= 3:
        rec["issues"].append(f"wrist camera frozen for {rec['wrist_repeat_longest']} consecutive frames")
    return rec


def cmd_audit(a):
    eps = sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "frame_map.json").exists())
    if a.only:
        eps = [p for p in eps if p.name in set(a.only.split(","))]
    recs = []
    for ep in eps:
        r = audit_one(ep)
        recs.append(r)
        sc, wr = r.get("cam_scene", {}), r.get("cam_wrist", {})
        print(f"{r['uid']:<14} frames={r['frames']:<4} scene_lag={sc.get('lag_ms')}ms{sc.get('lag_ci_ms')} c={sc.get('corr')} "
              f"wrist_lag={wr.get('lag_ms')}ms{wr.get('lag_ci_ms')} c={wr.get('corr')} wrist_max={r['wrist_dt_ms_max']}ms "
              f"repeat={r['wrist_repeat_pct']}% lead={r['lead_ms']} tail={r['tail_ms']} issues={len(r['issues'])}", flush=True)
    agg, rec_txt, far = {}, [], {}
    for cam in ("cam_scene", "cam_wrist"):
        ok = [r for r in recs if cam in r and r[cam]["lag_ms"] is not None and r[cam]["corr"] >= a.min_corr]
        if not ok:
            continue
        lags = [r[cam]["lag_ms"] for r in ok]
        widths = [r[cam]["lag_ci_ms"][1] - r[cam]["lag_ci_ms"][0] for r in ok]
        med = statistics.median(lags)
        mad = statistics.median(abs(x - med) for x in lags)
        res = statistics.median(widths) / 2
        agg[cam] = {"n_reliable": len(ok), "n_total": sum(cam in r for r in recs), "lag_ms_median": med,
                    "lag_ms_mad": mad, "resolution_ms": res}
        # direction of each episode whose whole interval sits > gross_ms from the median (weak corr allowed as support)
        for r in recs:
            c = r.get(cam, {})
            if c.get("lag_ms") is None or c["corr"] < 0.3:
                continue
            lo, hi = c["lag_ci_ms"]
            if lo > med + a.gross_ms or hi < med - a.gross_ms:
                far.setdefault(r["uid"], {})[cam] = (1 if lo > med else -1, c["corr"] >= a.min_corr)
        if abs(med) > max(res, 1000 / 60) and mad < res:
            rec_txt.append(f"{cam}: consistent lag {med} ms (MAD {mad}, resolution ±{res:.0f}); candidate correction "
                           f"`shift --offset_ms {-med}` after the user confirms")
        else:
            rec_txt.append(f"{cam}: median lag {med} ms, MAD {mad}, resolution ±{res:.0f} ms -> motion evidence does not support a collection-wide shift")
    confirmed, possible = [], []
    for uid, cams in far.items():
        dirs = {d for d, _ in cams.values()}
        (confirmed if len(cams) == 2 and len(dirs) == 1 else possible).append(uid)
        r = next(x for x in recs if x["uid"] == uid)
        r["issues"].append(f"motion-lag outlier (> {a.gross_ms} ms from median) on {sorted(cams)}: verify with event_strip")
    agg["motion_lag_outliers"] = {"both_cameras": sorted(confirmed), "one_camera": sorted(possible)}
    rec_txt.append(f"motion-lag outliers (> {a.gross_ms} ms): both cameras {sorted(confirmed) or 'none'}; one camera "
                   f"{sorted(possible) or 'none'} -> NOT proof of desync; verify each with `event_strip` before acting")
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "sync_audit.json").write_text(json.dumps({"aggregate": agg, "recommendation": rec_txt, "episodes": recs}, indent=1))
    print("AGGREGATE", json.dumps(agg))
    for t in rec_txt:
        print("RECOMMEND", t)
    print("wrote", out / "sync_audit.json")
    return 1 if any(r["issues"] for r in recs) else 0


def cmd_shift(a):
    if a.offset_ms is None:
        sys.exit("--offset_ms required")
    src, out = Path(a.episodes_dir), Path(a.out_dir)
    if src.resolve() == out.resolve():
        sys.exit("OUT_DIR must differ from EPISODES_DIR")
    eps = sorted(p for p in src.iterdir() if (p / "telemetry.jsonl").exists())
    if a.only:
        eps = [p for p in eps if p.name in set(a.only.split(","))]
    off = int(round(a.offset_ms * 1e6))
    for ep in eps:
        o = out / ep.name; o.mkdir(parents=True, exist_ok=True)
        for f in ep.iterdir():
            if f.is_file() and f.name not in ("telemetry.jsonl", "meta.json"):
                dst = o / f.name
                if dst.exists():
                    dst.unlink()
                try:
                    os.link(f, dst)
                except OSError:
                    shutil.copy2(f, dst)
        lines = []
        for l in (ep / "telemetry.jsonl").read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                if "t_ns" in r:
                    r["t_ns"] += off
                lines.append(json.dumps(r))
        (o / "telemetry.jsonl").write_text("\n".join(lines) + "\n")
        meta = json.loads((ep / "meta.json").read_text())
        meta["sync_correction"] = {"telemetry_shift_ms": a.offset_ms, "source": str(ep), "tool": "vmodal-robot-sync-audit@1"}
        (o / "meta.json").write_text(json.dumps(meta, indent=1))
        print(f"{ep.name}: telemetry shifted {a.offset_ms:+} ms -> {o}")
    return 0


def cmd_event_strip(a):
    """Wrist/scene frames around the first gripper state change: the precise, visual sync check."""
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    eps = [Path(a.episodes_dir) / u for u in a.only.split(",")] if a.only else sorted(Path(a.episodes_dir).iterdir())
    for ep in eps:
        frames = json.loads((ep / "frame_map.json").read_text())
        rows = [r for r in (json.loads(l) for l in (ep / "telemetry.jsonl").read_text().splitlines() if l.strip()) if "t_ns" in r]
        g = np.array([r[a.event_field] for r in rows], dtype=float).reshape(len(rows), -1)[:, 0]
        moved = np.nonzero(np.abs(g - g[0]) > a.event_delta)[0]
        if not len(moved):
            print(f"{ep.name}: {a.event_field} never changes by > {a.event_delta}; no event"); continue
        t_ev = rows[int(moved[0])]["t_ns"]
        for cam, col in (("cam_wrist", "t_wrist_ns"), ("cam_scene", "t_scene_ns")):
            if not (ep / f"{cam}.mp4").exists():
                continue
            tc = np.array([f[col] for f in frames], dtype=float)
            picks = [int(np.argmin(np.abs(tc - (t_ev + o * 1e6)))) for o in (-600, -300, 0, 300, 600)]
            sel = "+".join(f"eq(n\\,{k})" for k in picks)
            dst = out / f"{ep.name}_{cam}_event.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ep / f"{cam}.mp4"), "-vf",
                            f"select='{sel}',scale=256:-1,tile=5x1", "-frames:v", "1", str(dst)], check=True)
            print(f"{ep.name} {cam}: {a.event_field} event at frame {picks[2]}; strip = -600,-300,0,+300,+600 ms -> {dst}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["audit", "shift", "event_strip"]); p.add_argument("episodes_dir"); p.add_argument("out_dir")
    p.add_argument("--only", default=""); p.add_argument("--offset_ms", type=float)
    p.add_argument("--min_corr", type=float, default=0.4, help="lag estimates below this correlation are ignored")
    p.add_argument("--gross_ms", type=float, default=250, help="flag episodes whose lag interval is this far from the median")
    p.add_argument("--event_field", default="gripper", help="event_strip: scalar field whose first change marks the event")
    p.add_argument("--event_delta", type=float, default=0.05)
    a = p.parse_args()
    sys.exit({"audit": cmd_audit, "shift": cmd_shift, "event_strip": cmd_event_strip}[a.cmd](a))
