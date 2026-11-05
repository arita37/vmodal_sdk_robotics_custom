"""Frame-aligned (30 fps) state/action normalization stats and training-readiness checks for VLA datasets.

usage (from the MCP package root):
  .venv/bin/python skills/vmodal-robot-norm-stats/scripts/norm_stats.py EPISODES_DIR OUT_DIR (--spec F | --format_id N@V)
      [--state q,gripper] [--action cmd_q,cmd_gripper] [--exclusions exclusions.json] [--export DIR]

Per scene frame: state = nearest telemetry row in time; action = latest command at or before the frame
(what the controller was executing); delta = action - matching state dims. Writes OUT_DIR/norm_stats.json
(LeRobot-style keys: mean,std,min,max,q01,q99,count + names) and OUT_DIR/norm_report.json.
--export writes one <uid>.npz per episode (t_ns, frame_index, state, action) plus names.json.
"""
import argparse, bisect, json, os, statistics, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def load_spec(a):
    if a.spec:
        return json.loads(Path(a.spec).read_text())
    name, ver = a.format_id.split("@")
    return json.loads((Path(a.robot_dir) / "formats" / name / f"v{ver}.json").read_text())


def dim_names(spec, fields):
    by = {f["name"]: f for f in spec["fields"]}
    out = []
    for n in fields:
        f = by[n]
        size = int(np.prod(f["shape"])) if f["shape"] else 1
        names = f.get("names") or ([] if size == 1 else [str(i) for i in range(size)])
        out += [n] if size == 1 else [f"{n}.{x}" for x in names]
    return out


def vec(row, fields):
    return np.concatenate([np.ravel(np.asarray(row[n], dtype=float)) for n in fields])


def stats(x):
    return {"mean": x.mean(0).tolist(), "std": x.std(0).tolist(), "min": x.min(0).tolist(), "max": x.max(0).tolist(),
            "q01": np.quantile(x, 0.01, axis=0).tolist(), "q99": np.quantile(x, 0.99, axis=0).tolist(), "count": [len(x)]}


def otsu(v, bins=64):
    h, e = np.histogram(v, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    best, thr = -1, None
    for k in range(1, bins):
        w0, w1 = h[:k].sum(), h[k:].sum()
        if w0 == 0 or w1 == 0:
            continue
        m0, m1 = (h[:k] * c[:k]).sum() / w0, (h[k:] * c[k:]).sum() / w1
        b = w0 * w1 * (m0 - m1) ** 2
        if b > best:
            best, thr = b, e[k]
    return thr


def main(a):
    spec = load_spec(a)
    by = {f["name"]: f for f in spec["fields"]}
    s_f, a_f = a.state.split(","), a.action.split(",")
    for n in s_f + a_f:
        if n not in by:
            sys.exit(f"field {n} not in spec {spec['format_id']}")
    s_names, a_names = dim_names(spec, s_f), dim_names(spec, a_f)
    # delta pairs: action dim cmd_X.k minus state dim X.k when present
    pairs = [(i, s_names.index(n[4:])) for i, n in enumerate(a_names) if n.startswith("cmd_") and n[4:] in s_names]
    excluded = set()
    if a.exclusions:
        ex = json.loads(Path(a.exclusions).read_text())
        excluded = {e["episode_uid"] for e in ex.get("excluded", [])}
    eps = sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "telemetry.jsonl").exists() and p.name not in excluded)
    S, A, D, per_ep, warnings = [], [], [], {}, []
    exp = Path(a.export) if a.export else None
    if exp:
        exp.mkdir(parents=True, exist_ok=True)
    for ep in eps:
        rows = [r for r in (json.loads(l) for l in (ep / "telemetry.jsonl").read_text().splitlines() if l.strip()) if "t_ns" in r]
        frames = json.loads((ep / "frame_map.json").read_text())
        t = [r["t_ns"] for r in rows]
        st, ac, tf = [], [], []
        for fr in frames:
            tt = fr["t_scene_ns"]
            k = bisect.bisect_left(t, tt)
            near = min((j for j in (k - 1, k) if 0 <= j < len(t)), key=lambda j: abs(t[j] - tt))
            cmd = max(bisect.bisect_right(t, tt) - 1, 0)
            st.append(vec(rows[near], s_f)); ac.append(vec(rows[cmd], a_f)); tf.append(tt)
        st, ac = np.array(st), np.array(ac)
        de = np.stack([ac[:, i] - st[:, j] for i, j in pairs], 1) if pairs else np.zeros((len(st), 0))
        S.append(st); A.append(ac); D.append(de)
        per_ep[ep.name] = {"frames": len(frames)}
        for n in s_f:
            if "quat" in n:
                q = np.array([r[n] for r in rows], dtype=float)
                flips = int((np.sum(q[1:] * q[:-1], 1) < 0).sum())
                if flips:
                    warnings.append(f"{ep.name}: {n} has {flips} sign flips; repair before using it as a state feature")
        if exp:
            np.savez_compressed(exp / f"{ep.name}.npz", t_ns=np.array(tf, dtype=np.int64),
                                frame_index=np.arange(len(frames)), state=st.astype(np.float32), action=ac.astype(np.float32))
    allS, allA, allD = np.concatenate(S), np.concatenate(A), np.concatenate(D)
    report = {"episodes_used": len(eps), "frames": int(len(allS)), "excluded": sorted(excluded), "warnings": warnings}
    # zero-variance dims break z-normalization
    for nm, x, names in (("state", allS, s_names), ("action", allA, a_names)):
        z = [names[i] for i in np.nonzero(x.std(0) < 1e-6)[0]]
        if z:
            report.setdefault("zero_variance", {})[nm] = z
    # per-frame action jumps vs collection-wide robust spread of frame-to-frame changes
    dA = np.abs(np.concatenate([np.diff(x, axis=0) for x in A]))
    limit = np.maximum(a.jump_k * np.quantile(dA, 0.99, axis=0), a.jump_min)   # k × "fast but normal" motion
    jumps = []
    for ep, x in zip(eps, A):
        d = np.abs(np.diff(x, axis=0))
        for f, i in zip(*np.nonzero(d > limit)):
            if not a_names[i].startswith("cmd_gripper"):          # gripper commands are steps by design
                jumps.append({"uid": ep.name, "frame": int(f + 1), "dim": a_names[i], "delta": round(float(d[f, i]), 4)})
    report["action_jumps"] = {"n": len(jumps), "threshold": f"|Δ per frame| > max({a.jump_k}×q99 of |Δ|, {a.jump_min})",
                              "limit_per_dim": dict(zip(a_names, np.round(limit, 4).tolist())),
                              "by_episode": {u: sum(j["uid"] == u for j in jumps) for u in sorted({j["uid"] for j in jumps})},
                              "top": sorted(jumps, key=lambda j: -j["delta"])[:10]}
    # gripper command binarization
    for i, n in enumerate(a_names):
        if "gripper" in n:
            v = allA[:, i]
            thr = otsu(v)
            mid = float(((v > 0.05 * v.max()) & (v < 0.95 * v.max())).mean()) if v.max() > 0 else 0.0
            report.setdefault("gripper", {})[n] = {"suggested_binarize_threshold": round(float(thr), 3) if thr is not None else None,
                                                   "fraction_between_5_95pct": round(mid, 3)}
    # action leads state by how many frames: correlation of frame-to-frame changes pooled over episodes and joint dims
    K = 15
    num, den_a, den_b = np.zeros(K), np.zeros(K), np.zeros(K)
    for x, y in zip(A, S):
        for i, j in pairs:
            if "gripper" in a_names[i]:
                continue
            dx, dy = np.diff(x[:, i]), np.diff(y[:, j])
            for k in range(K):
                if len(dx) - k < 30:
                    continue
                u, v = dx[: len(dx) - k], dy[k:]
                num[k] += u @ v; den_a[k] += u @ u; den_b[k] += v @ v
    if den_a.any():
        prof = num / np.sqrt(den_a * den_b + 1e-18)
        k = int(np.argmax(prof))
        flat = prof.max() - min(prof[:4]) < 0.02
        report["action_leads_state_frames"] = {"best": None if flat or k == K - 1 else k,
            "ms": None if flat or k == K - 1 else round(k * 1000 / 30, 1), "corr_profile": np.round(prof, 3).tolist(),
            "hint": ("correlation profile is flat over the first frames: lag unresolved at 30 fps; use the telemetry-rate "
                     "estimate from vmodal-robot-format-review" if flat else
                     "at search edge: unreliable" if k == K - 1 else
                     "state reaches the commanded value about this many frames later; check action-chunk alignment")}
    norm = {"observation.state": {**stats(allS), "names": s_names}, "action": {**stats(allA), "names": a_names}}
    if pairs:
        norm["action_delta"] = {**stats(allD), "names": [a_names[i] for i, _ in pairs]}
    norm["_meta"] = {"format_id": spec["format_id"], "format_version": spec["format_version"], "fps": 30,
                     "state_fields": s_f, "action_fields": a_f, "episodes": [p.name for p in eps], "excluded": sorted(excluded),
                     "alignment": "state=nearest telemetry row to scene frame; action=latest command at or before the frame"}
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "norm_stats.json").write_text(json.dumps(norm, indent=1))
    (out / "norm_report.json").write_text(json.dumps(report, indent=1))
    if exp:
        (exp / "names.json").write_text(json.dumps({"state": s_names, "action": a_names, "meta": norm["_meta"]}, indent=1))
    print(f"episodes={len(eps)} frames={len(allS)} excluded={sorted(excluded) or '-'}")
    for nm, key in (("state", "observation.state"), ("action", "action")):
        st = norm[key]
        print(f"{nm:6} dims={len(st['names'])}: " + ", ".join(f"{n}[{lo:.3f},{hi:.3f}]" for n, lo, hi in zip(st["names"], st["q01"], st["q99"])))
    print("zero_variance:", report.get("zero_variance", "-"))
    print("action_jumps:", report["action_jumps"]["n"], report["action_jumps"]["by_episode"])
    print("gripper:", report.get("gripper"))
    lead = report.get("action_leads_state_frames", {})
    print("action_leads_state_frames:", lead.get("best"), f"(~{lead.get('ms')} ms)", "corr", lead.get("corr_profile", [])[:6], "-", lead.get("hint"))
    for w in warnings[:5]:
        print("WARN", w)
    if len(warnings) > 5:
        print(f"WARN ... {len(warnings) - 5} more in norm_report.json")
    print("wrote", out / "norm_stats.json", out / "norm_report.json", exp or "")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("episodes_dir"); p.add_argument("out_dir")
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--spec"); g.add_argument("--format_id")
    p.add_argument("--robot_dir", default=os.environ.get("MCP_ROBOT_DIR", str(ROOT / "ztmp/mcp_robot")))
    p.add_argument("--state", default="q,gripper"); p.add_argument("--action", default="cmd_q,cmd_gripper")
    p.add_argument("--exclusions"); p.add_argument("--export")
    p.add_argument("--jump_k", type=float, default=3.0); p.add_argument("--jump_min", type=float, default=0.05)
    sys.exit(main(p.parse_args()))
