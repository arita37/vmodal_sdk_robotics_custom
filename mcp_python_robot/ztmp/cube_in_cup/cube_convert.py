"""Convert Bigenlight/cube_in_cup_raw takes into vmodal robot episode inputs.

usage: python -I cube_convert.py RAW_DIR OUT_DIR take_folder [take_folder ...]
Per take writes OUT/<uid>/{cam_scene.mp4,cam_wrist.mp4,frame_map.json,telemetry.jsonl,meta.json}
cam1 = scene (tripod), cam2 = wrist (verified visually on take_10).
"""
import bisect, json, os, statistics, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import h5py, numpy as np

def col(f, g, k):
    return f[g][k][:]

def ns(base, t):
    return base + int(round(float(t) * 1e9))

def clip(src, picks, dst):
    """Re-encode `src` so output frame i is decoded source frame picks[i], 30/1 CFR."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-fps_mode", "passthrough",
                        "-q:v", "2", f"{tmp}/src_%05d.jpg"], check=True)
        n_src = len([p for p in os.listdir(tmp) if p.startswith("src_")])
        if max(picks) >= n_src:
            raise SystemExit(f"{src}: needs frame {max(picks)} but decoded {n_src}")
        for i, j in enumerate(picks):
            os.symlink(f"{tmp}/src_{j+1:05d}.jpg", f"{tmp}/seq_{i:05d}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", f"{tmp}/seq_%05d.jpg",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(dst)], check=True)
    return n_src

def hold(times, t):
    """Index of the latest sample at or before t (first sample if none yet)."""
    return max(bisect.bisect_right(times, t) - 1, 0)

def convert(raw, out, take):
    uid = "_".join(take.split("_")[:2])                    # take_03
    stamp = datetime.strptime("_".join(take.split("_")[2:]), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    base = int(stamp.timestamp()) * 1_000_000_000          # folder time; real time zone unknown -> treated as UTC
    o = Path(out) / uid
    o.mkdir(parents=True, exist_ok=True)
    with h5py.File(Path(raw) / take / "vectors.h5", "r") as f:
        c1, c2 = col(f, "cam1_frames", "t_rel_s"), col(f, "cam2_frames", "t_rel_s")
        # frame map: one row per scene frame, wrist = nearest cam2 frame by time
        # drop leading scene frames captured before the first robot sample (no telemetry/command yet)
        t_first = float(col(f, "ur_joint_states", "t_rel_s")[0])
        keep1 = [i for i, t in enumerate(c1) if t >= t_first]
        frames, picks2, prev = [], [], None
        for i, t in enumerate(c1[keep1[0]:]):
            k = int(np.argmin(np.abs(c2 - t)))
            ts, tw = ns(base, t), ns(base, c2[k])
            frames.append({"episode_uid": uid, "episode_index": 0, "frame_index": i, "t_scene_ns": ts,
                           "t_wrist_ns": tw, "wrist_dt_ms": (tw - ts) / 1e6, "wrist_repeated": k == prev})
            picks2.append(k); prev = k
        # telemetry: one row per UR joint-state sample; other streams sample-and-hold
        tq = [ns(base, t) for t in col(f, "ur_joint_states", "t_rel_s")]
        q = np.stack([col(f, "ur_joint_states", f"q{j}") for j in range(1, 7)], 1)
        eff = np.stack([col(f, "ur_joint_states", f"eff{j}") for j in range(1, 7)], 1)
        tt = [ns(base, t) for t in col(f, "tcp_pose", "t_rel_s")]
        pos = np.stack([col(f, "tcp_pose", k) for k in "xyz"], 1)
        quat = np.stack([col(f, "tcp_pose", k) for k in ("qx", "qy", "qz", "qw")], 1)   # wxyz -> xyzw
        tc = [ns(base, t) for t in col(f, "command", "t_rel_s")]
        cmd = np.stack([col(f, "command", f"cmd{j}") for j in range(1, 7)], 1)
        tg = [ns(base, t) for t in col(f, "gripper", "t_rel_s")]
        gp, gc = col(f, "gripper", "grip_pos"), col(f, "gripper", "grip_cmd")
    rows, last = [], None
    for i, t in enumerate(tq):
        if last is not None and t <= last:
            continue                                     # keep time strictly increasing
        a, c, g = hold(tt, t), hold(tc, t), hold(tg, t)
        qn = quat[a] / np.linalg.norm(quat[a])
        rows.append({"t_ns": t, "q": q[i].tolist(), "current": eff[i].tolist(), "gripper": float(gp[g]),
                     "ee_pos": pos[a].tolist(), "ee_quat": qn.tolist(), "cmd_q": cmd[c].tolist(),
                     "cmd_gripper": float(gc[g])})
        last = t
    n1 = clip(Path(raw) / take / "cam1.mp4", list(range(keep1[0], keep1[0] + len(frames))), o / "cam_scene.mp4")
    n2 = clip(Path(raw) / take / "cam2.mp4", picks2, o / "cam_wrist.mp4")
    (o / "frame_map.json").write_text(json.dumps(frames))
    (o / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    wdt = [abs(r["wrist_dt_ms"]) for r in frames]
    meta = {"episode_uid": uid, "length": len(frames), "duration_s": round(len(frames) / 30, 3),
            "task": "put the cube in the cup", "success": uid != "take_23",
            "success_source": "dataset card: take_23 is a recording misfire, others are successful demos",
            "robot_id": "ur7e_gello", "operator_id": "bigenlight_op1", "start_time": stamp.isoformat().replace("+00:00", "Z"),
            "start_time_note": "from take folder name; time zone unknown, treated as UTC",
            "source_dataset": "Bigenlight/cube_in_cup_raw", "source_take": take,
            "n_dropped": 0, "cmd_latency_ms": 0,
            "sync_offset_ms_max": round(max(wdt), 3), "sync_offset_ms_mean": round(statistics.mean(wdt), 3)}
    (o / "meta.json").write_text(json.dumps(meta, indent=1))
    dts = np.diff(tq) / 1e6
    return {"uid": uid, "frames": len(frames), "dropped_lead_frames": keep1[0], "cam1_decoded": n1, "cam2_decoded": n2, "tel_rows": len(rows),
            "tel_median_hz": round(1000 / float(np.median(dts)), 1), "tel_max_gap_ms": round(float(dts.max()), 1),
            "wrist_repeats": sum(r["wrist_repeated"] for r in frames), "wrist_dt_ms_max": round(max(wdt), 2)}

if __name__ == "__main__":
    raw, out, *takes = sys.argv[1:]
    for take in takes:
        print(json.dumps(convert(raw, out, take)))
