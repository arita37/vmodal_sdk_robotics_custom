"""Episode-level outcome screen for robot demonstrations: catches failed/misfired demos that pass format checks.

usage (from the MCP package root):
  screen: .venv-robot/bin/python skills/vmodal-robot-failure-screen/scripts/failure_screen.py screen EPISODES_DIR OUT_DIR
              [--thresholds JSON] [--no_sheets]
  review: .venv-robot/bin/python skills/vmodal-robot-failure-screen/scripts/failure_screen.py review OUT_DIR/review_sheet.csv
              REVIEWER OUT_DIR/exclusions.json

screen writes: candidates.json (source=auto, review_status=unreviewed), review_sheet.csv (decision column EMPTY),
contact_sheets/<uid>.png (scene camera at 0/25/50/75/100%). review turns a HUMAN-filled sheet into exclusions.json.
Gripper polarity is inferred from data (state when the command is high vs low), never from unit strings.
"""
import argparse, csv, hashlib, json, statistics, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

VERSION = "failure_screen_v2"
DEFAULTS = {"cmd_field": "cmd_gripper", "state_field": "gripper", "pos_field": "ee_pos",
            "state_polarity": None, "opening_hold_s": 0.1, "cmd_close_above": 0.5, "state_delta": 0.05, "min_duration_s": 2.0, "short_frac": 0.4,
            "low_motion_frac": 0.25, "idle_speed_mps": 0.01, "idle_frac": 0.5, "end_pose_min_m": 0.05,
            "end_pose_mad_k": 4.0, "grip_width_z": 3.5, "duration_z": 3.5, "release_window_s": 0.5, "release_delay_s": 1.0}


def robust_z(vals):
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals) * 1.4826
    return [0.0 if mad < 1e-9 else (v - med) / mad for v in vals], med, mad


def features(ep, th, polarity=None):
    rows = [r for r in (json.loads(l) for l in (ep / "telemetry.jsonl").read_text().splitlines() if l.strip()) if "t_ns" in r]
    meta = json.loads((ep / "meta.json").read_text())
    n_frames = len(json.loads((ep / "frame_map.json").read_text()))
    t = np.array([r["t_ns"] for r in rows], dtype=np.float64)
    cmd = np.array([r[th["cmd_field"]] for r in rows], dtype=float)
    st = np.array([r[th["state_field"]] for r in rows], dtype=float)
    pos = np.array([r[th["pos_field"]] for r in rows], dtype=float)
    sp = np.linalg.norm(np.diff(pos, axis=0), axis=1) / (np.diff(t) / 1e9)
    closing = cmd > th["cmd_close_above"]
    moving = np.nonzero(sp > th["idle_speed_mps"])[0]
    active = sp[moving[0]:] if len(moving) else sp
    end = t[-1] - th["release_window_s"] * 1e9
    first = int(np.argmax(closing)) if closing.any() else len(st)
    open_ref = float(np.median(st[:max(first, 1)]))          # state before the first close command
    releases = []
    openings = []
    closed_peak = None
    if polarity is not None:
        # Compare only within uninterrupted close-command runs. Require both the
        # held reference and the subsequent opening to persist, rejecting spikes.
        signed = polarity * st
        start = 0
        peak = None
        peak_t = None
        drop_start = None
        flagged = False
        for i in range(len(st)):
            if not closing[i]:
                start, peak, peak_t, drop_start, flagged = i + 1, None, None, None, False
                continue
            left = max(start, int(np.searchsorted(t, t[i] - th["opening_hold_s"] * 1e9, side="right")) - 1)
            if t[i] - t[start] >= th["opening_hold_s"] * 1e9:
                held = float(np.min(signed[left:i + 1]))
                closed_peak = held if closed_peak is None else max(closed_peak, held)
                if peak is None or held > peak:
                    peak, peak_t = held, int(t[i])
            if peak is not None and peak - signed[i] >= th["state_delta"]:
                drop_start = i if drop_start is None else drop_start
                if not flagged and t[i] - t[drop_start] >= th["opening_hold_s"] * 1e9:
                    openings.append({"t_start_ns": peak_t, "t_end_ns": int(t[i]),
                                     "delta": float(peak - signed[i])})
                    flagged = True
            else:
                drop_start = None
        for i in np.nonzero(closing[:-1] & ~closing[1:])[0] + 1:   # command falls: open requested
            held = float(np.median(st[max(0, i - 20):i]))           # state just before the release
            half = open_ref + (held - open_ref) / 2                 # response = time to get halfway open
            back = np.nonzero(polarity * (st[i:] - half) < 0)[0]
            delay = (t[i + back[0]] - t[i]) / 1e9 if len(back) else (t[-1] - t[i]) / 1e9
            releases.append({"t_ns": int(t[i]), "delay_s": round(float(delay), 2), "reopened": bool(len(back))})
    return {"uid": ep.name, "t0": int(t[0]), "t1": int(t[-1]), "duration_s": n_frames / 30,
            "meta_success": meta.get("success"), "close_cmd": bool(closing.any()),
            "first_close_t": int(t[np.argmax(closing)]) if closing.any() else None,
            "state_open": open_ref, "observed_open_before_close": 0 < first < len(st),
            "releases": releases, "openings": openings, "closed_peak": closed_peak,
            "state_closed": float(np.median(st[closing])) if closing.any() else None,
            "state_range": float(st.max() - st.min()),
            "closed_at_end": bool(closing[t >= end].all()),
            "path_m": float(np.linalg.norm(np.diff(pos, axis=0), axis=1).sum()),
            "idle_frac": float((active < th["idle_speed_mps"]).mean()) if len(active) else 1.0,
            "end_pos": pos[-1].tolist()}


def cmd_screen(a):
    th = dict(DEFAULTS)
    if a.thresholds:
        th.update(json.loads(Path(a.thresholds).read_text()))
    th_sha = hashlib.sha256(json.dumps(th, sort_keys=True).encode()).hexdigest()[:12]
    eps = sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "telemetry.jsonl").exists())
    F = [features(ep, th) for ep in eps]
    # gripper polarity from data: does the state go up or down when the close command is on?
    if not F:
        sys.exit("no episodes with telemetry.jsonl found")
    pairs = [f["state_closed"] - f["state_open"] for f in F
             if f["observed_open_before_close"] and
             abs(f["state_closed"] - f["state_open"]) >= th["state_delta"]]
    polarity = th["state_polarity"]
    if polarity not in (None, -1, 1):
        sys.exit("state_polarity must be -1, 1, or null")
    if polarity is None and pairs and abs(statistics.median(pairs)) >= th["state_delta"]:
        polarity = 1 if statistics.median(pairs) > 0 else -1
    polarity_label = ("unknown (no informative close transition)" if polarity is None else
                      "state increases when closing" if polarity > 0 else "state decreases when closing")
    F = [features(ep, th, polarity) for ep in eps]
    durz, dmed, _ = robust_z([f["duration_s"] for f in F])
    path_med = statistics.median(f["path_m"] for f in F)
    endp = np.array([f["end_pos"] for f in F])
    end_med = np.median(endp, axis=0)
    end_d = np.linalg.norm(endp - end_med, axis=1)
    end_mad = float(np.median(np.abs(end_d - np.median(end_d)))) * 1.4826
    # Leave the candidate out of its own baseline. A fixed minimum delta makes
    # comparisons usable with one peer or zero MAD; robust spread protects varied sets.
    widths = [(i, f["closed_peak"]) for i, f in enumerate(F)
              if f["closed_peak"] is not None and
              (not f["observed_open_before_close"] or
               polarity * (f["state_closed"] - f["state_open"]) >= th["state_delta"])]
    width_flags = {}
    for i, width in widths:
        peers = [v for j, v in widths if j != i]
        if peers:
            _, med, mad = robust_z(peers)
            if width - med > max(th["state_delta"], th["grip_width_z"] * mad):
                width_flags[i] = (width - med, len(peers))
    done = [r["delay_s"] for f in F for r in f["releases"] if r["reopened"]]
    rel_med = statistics.median(done) if done else 0.0
    rel_limit = max(th["release_delay_s"], 3 * rel_med)
    cands = []
    def add(f, rule, sev, evidence, t0=None, t1=None):
        cands.append({"episode_uid": f["uid"], "rule": rule, "severity": sev, "evidence": evidence,
                      "t_start_ns": f["t0"] if t0 is None else t0, "t_end_ns": f["t1"] if t1 is None else t1, "source": "auto",
                      "review_status": "unreviewed", "detector": VERSION, "thresholds_sha": th_sha})
    for i, f in enumerate(F):
        if f["duration_s"] < max(th["min_duration_s"], th["short_frac"] * dmed):
            add(f, "too_short", "high", f"{f['duration_s']:.2f} s vs median {dmed:.2f} s")
        elif abs(durz[i]) > th["duration_z"]:
            add(f, "duration_outlier", "low", f"{f['duration_s']:.2f} s, robust z {durz[i]:+.1f}")
        if not f["close_cmd"]:
            add(f, "no_close_command", "high", f"{th['cmd_field']} never above {th['cmd_close_above']}")
        elif (polarity is not None and f["observed_open_before_close"] and
              polarity * (f["state_closed"] - f["state_open"]) < th["state_delta"]):
            add(f, "gripper_did_not_close", "high", f"state {f['state_open']:.3f} -> {f['state_closed']:.3f} while commanded closed",
                f["first_close_t"])
        if i in width_flags:
            delta, count = width_flags[i]
            add(f, "closed_further_than_peers", "medium",
                f"sustained closed state exceeds median of {count} peer(s) by {delta:.3f}: possible empty grasp",
                f["first_close_t"])
        for opening in f["openings"]:
            add(f, "opens_while_commanded_closed", "medium",
                f"state opened by {opening['delta']:.3f} while close command remained on "
                f"for at least {th['opening_hold_s']} s: possible drop",
                opening["t_start_ns"], opening["t_end_ns"])
        for rel in f["releases"]:
            # censored releases (episode ended first) count only if they already exceed the limit
            if rel["delay_s"] > rel_limit:
                add(f, "slow_or_stuck_release", "medium",
                    f"open commanded; gripper {'got halfway open only after' if rel['reopened'] else 'still not halfway open after'} "
                    f"{rel['delay_s']} s (collection median {rel_med:.2f} s)", rel["t_ns"], int(rel["t_ns"] + rel["delay_s"] * 1e9))
        if f["close_cmd"] and f["closed_at_end"]:
            add(f, "not_released", "medium", f"gripper still commanded closed in the last {th['release_window_s']} s",
                int(f["t1"] - th["release_window_s"] * 1e9))
        if f["path_m"] < th["low_motion_frac"] * path_med:
            add(f, "low_motion", "high", f"end-effector path {f['path_m']:.3f} m vs median {path_med:.3f} m")
        if f["idle_frac"] > th["idle_frac"]:
            add(f, "mostly_idle", "medium", f"{100 * f['idle_frac']:.0f}% of time below {th['idle_speed_mps']} m/s after first motion")
        if end_d[i] > max(th["end_pose_min_m"], th["end_pose_mad_k"] * end_mad + float(np.median(end_d))):
            add(f, "end_pose_outlier", "medium", f"final {th['pos_field']} {end_d[i]:.3f} m from the median final pose")
    by = {}
    for c in cands:
        by.setdefault(c["episode_uid"], []).append(c)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "candidates.json").write_text(json.dumps({"detector": VERSION, "thresholds": th, "thresholds_sha": th_sha,
        "gripper_polarity": polarity_label,
        "candidates": cands}, indent=1))
    with open(out / "review_sheet.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["episode_uid", "meta_success", "flags", "suggestion", "decision", "note"])
        for f in F:
            fl = by.get(f["uid"], [])
            high = any(c["severity"] == "high" for c in fl)
            agree = (f["meta_success"] is False) == high
            sug = ("exclude?" if high else "check" if fl else "keep") + ("" if agree or f["meta_success"] is None else " (disagrees with meta.success)")
            w.writerow([f["uid"], f["meta_success"], "; ".join(f"{c['rule']}[{c['severity']}]" for c in fl), sug, "", ""])
    if not a.no_sheets:
        cs = out / "contact_sheets"; cs.mkdir(exist_ok=True)
        for old in cs.glob("*.png"):
            old.unlink()             # sheets always match this run
        for uid in by:
            ep = Path(a.episodes_dir) / uid
            n = len(json.loads((ep / "frame_map.json").read_text()))
            picks = sorted({min(n - 1, int(round(p * (n - 1)))) for p in (0, .25, .5, .75, 1)})
            sel = "+".join(f"eq(n\\,{k})" for k in picks)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ep / "cam_scene.mp4"), "-vf",
                            f"select='{sel}',scale=256:-1,tile={len(picks)}x1", "-frames:v", "1", str(cs / f"{uid}.png")], check=True)
    print(f"gripper polarity: {polarity_label}")
    for f in F:
        fl = by.get(f["uid"], [])
        print(f"{f['uid']:<12} meta_success={str(f['meta_success']):<5} flags={', '.join(c['rule'] + '[' + c['severity'][0] + ']' for c in fl) or '-'}")
    print(f"{len(cands)} candidates on {len(by)} episodes (all unreviewed). wrote {out}/candidates.json, review_sheet.csv"
          + ("" if a.no_sheets else ", contact_sheets/"))
    return 0


def cmd_review(a):
    if not a.reviewer.strip():
        sys.exit("reviewer name required")
    rows = list(csv.DictReader(open(a.sheet)))
    allowed = {"keep", "exclude", "relabel_failure"}
    missing = [r["episode_uid"] for r in rows if r["flags"] and r["decision"].strip() not in allowed]
    bad = [r["episode_uid"] for r in rows if r["decision"].strip() and r["decision"].strip() not in allowed]
    if bad:
        sys.exit(f"invalid decision for {bad}; use one of {sorted(allowed)}")
    if missing:
        sys.exit(f"flagged episodes without a decision: {missing}. A human must decide each one.")
    now = datetime.now(timezone.utc).isoformat()
    out = {"tool": VERSION, "reviewer": a.reviewer, "reviewed_at": now, "sheet": str(Path(a.sheet).resolve()),
           "excluded": [], "relabel_failure": [], "kept_flagged": []}
    for r in rows:
        d = r["decision"].strip()
        item = {"episode_uid": r["episode_uid"], "flags": r["flags"], "note": r["note"]}
        if d == "exclude":
            out["excluded"].append(item)
        elif d == "relabel_failure":
            out["relabel_failure"].append(item)
        elif d == "keep" and r["flags"]:
            out["kept_flagged"].append(item)
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(f"excluded={len(out['excluded'])} relabel_failure={len(out['relabel_failure'])} kept_flagged={len(out['kept_flagged'])} -> {a.out}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screen"); s.add_argument("episodes_dir"); s.add_argument("out_dir")
    s.add_argument("--thresholds"); s.add_argument("--no_sheets", action="store_true")
    r = sub.add_parser("review"); r.add_argument("sheet"); r.add_argument("reviewer"); r.add_argument("out")
    a = p.parse_args()
    sys.exit(cmd_screen(a) if a.cmd == "screen" else cmd_review(a))
