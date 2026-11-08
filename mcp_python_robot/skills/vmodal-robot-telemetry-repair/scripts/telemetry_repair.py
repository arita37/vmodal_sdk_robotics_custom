"""Repair common telemetry defects into a NEW episode folder, with a per-episode repair log and before/after checks.

usage (from the MCP package root):
  .venv-robot/bin/python skills/vmodal-robot-telemetry-repair/scripts/telemetry_repair.py EPISODES_DIR OUT_DIR
      (--spec SPEC_JSON | --format_id NAME@V) [--only uid,uid] [--max_nan_run 5] [--max_interp_ms 150]
      [--clamp_tol 0.02] [--no_quat_continuity]

Repairs (in order): unparseable rows dropped, rows sorted by time, duplicate timestamps (keep last),
short non-finite runs interpolated (commands: hold last), quaternions renormalized + sign-continuous,
small range overshoots clamped, gaps up to --max_interp_ms filled at the nominal rate (state: linear,
commands: hold). Anything larger is REPORTED, never invented. Source folders are never modified.
"""
import argparse, json, math, os, shutil, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.mcp_server.robot_format import telemetry_check, spec_validate  # noqa: E402


def load_spec(a):
    if a.spec:
        return spec_validate(json.loads(Path(a.spec).read_text()))
    name, ver = a.format_id.split("@")
    return spec_validate(json.loads((Path(a.robot_dir) / "formats" / name / f"v{ver}.json").read_text()))


def check(spec, header, rows, frames):
    try:
        rep = telemetry_check(spec, header, [dict(r) for r in rows], frames)
        return rep["verdict"], rep["errors"][:3], len(rep["errors"])
    except Exception as exc:
        return "exception", [str(exc)[:200]], 1


def runs(mask):
    """(start, end) half-open index runs where mask is True."""
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j)); i = j
        else:
            i += 1
    return out


def repair(spec, header, raw_lines, a):
    log, unrepaired = {}, []
    bump = lambda k, n=1: log.__setitem__(k, log.get(k, 0) + n)
    key = spec["time"]["field"]
    fields = {f["name"]: f for f in spec["fields"]}
    is_cmd = {n: f.get("role") == "command" for n, f in fields.items()}
    is_quat = {n: f.get("check") == "unit_norm" or "quat" in n for n, f in fields.items()}
    rows = []
    for line in raw_lines:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            bump("dropped_unparseable_rows"); continue
        if type(r.get(key)) is not int:
            bump("dropped_rows_without_time"); continue
        rows.append(r)
    t = [r[key] for r in rows]
    n_unsorted = sum(b < a_ for a_, b in zip(t, t[1:]))
    if n_unsorted:
        rows.sort(key=lambda r: r[key]); bump("reordered_steps", n_unsorted)
    dedup = {}
    for r in rows:
        dedup[r[key]] = r
    if len(dedup) != len(rows):
        bump("dropped_duplicate_timestamps", len(rows) - len(dedup))
    rows = [dedup[k] for k in sorted(dedup)]
    t = np.array([r[key] for r in rows], dtype=np.int64)

    # columns as float arrays (n, d)
    cols = {}
    for name, f in fields.items():
        if not all(name in r for r in rows):
            unrepaired.append(f"{name}: missing in {sum(name not in r for r in rows)} rows (not repaired)")
            continue
        try:
            cols[name] = np.array([r[name] for r in rows], dtype=float).reshape(len(rows), -1)
        except (TypeError, ValueError):
            unrepaired.append(f"{name}: non-numeric values (not repaired)")

    # non-finite runs
    for name, c in cols.items():
        bad = ~np.isfinite(c).all(1)
        for s, e in runs(bad):
            if e - s > a.max_nan_run or (s == 0 and e == len(c)):
                unrepaired.append(f"{name}: {e - s} consecutive non-finite rows at t={t[s]} (> max_nan_run {a.max_nan_run})"); continue
            if is_cmd[name] or s == 0 or e == len(c):
                c[s:e] = c[s - 1] if s > 0 else c[e]          # hold (commands, or edges)
            else:
                w = ((t[s:e] - t[s - 1]) / (t[e] - t[s - 1]))[:, None]
                c[s:e] = c[s - 1] * (1 - w) + c[e] * w
            bump(f"{name}.nonfinite_rows_filled", e - s)

    # quaternions
    for name, c in cols.items():
        if not is_quat[name] or not np.isfinite(c).all():
            continue
        norm = np.linalg.norm(c, axis=1)
        off = int((np.abs(norm - 1) > 1e-6).sum())
        if off:
            c /= norm[:, None]; bump(f"{name}.renormalized_rows", off)
        if not a.no_quat_continuity:
            flips = 0
            for i in range(1, len(c)):
                if np.dot(c[i], c[i - 1]) < 0:
                    c[i] = -c[i]; flips += 1
            if flips:
                bump(f"{name}.rows_negated_for_sign_continuity", flips)

    # range overshoot
    for name, c in cols.items():
        rng = fields[name].get("range")
        if not isinstance(rng, list):
            continue
        span = rng[1] - rng[0]
        lo, hi = c < rng[0], c > rng[1]
        small = (lo & (c >= rng[0] - a.clamp_tol * span)) | (hi & (c <= rng[1] + a.clamp_tol * span))
        big = (lo | hi) & ~small
        if small.any():
            c[:] = np.clip(c, rng[0], rng[1]) * small + c * ~small; bump(f"{name}.clamped_values", int(small.sum()))
        if big.any():
            unrepaired.append(f"{name}: {int(big.sum())} values far outside range {rng} (not clamped)")

    # gaps
    period = int(np.median(np.diff(t))) if len(t) > 2 else None
    max_gap = spec["sampling"]["max_gap_ms"] * 1e6
    new_t, new_idx = [int(t[0])], [0.0]          # fractional source index for interpolation
    for i in range(1, len(t)):
        d = t[i] - t[i - 1]
        if d > max_gap:
            if d <= a.max_interp_ms * 1e6 and period:
                k = int(round(d / period)) - 1
                for j in range(1, k + 1):
                    new_t.append(int(t[i - 1] + d * j / (k + 1))); new_idx.append(i - 1 + j / (k + 1))
                bump("gaps_filled"); bump("rows_inserted", k)
            else:
                unrepaired.append(f"gap {d / 1e6:.1f} ms at t={t[i - 1]} (> max_interp_ms {a.max_interp_ms}): split or drop the episode")
        new_t.append(int(t[i])); new_idx.append(float(i))
    out_rows = []
    for tt, fi in zip(new_t, new_idx):
        lo_i = int(math.floor(fi)); w = fi - lo_i
        r = {key: tt}
        for name, f in fields.items():
            if name not in cols:
                src = rows[lo_i].get(name)
                if src is not None:
                    r[name] = src
                continue
            c = cols[name]
            if w == 0 or is_cmd[name]:
                v = c[lo_i]
            else:
                v = c[lo_i] * (1 - w) + c[lo_i + 1] * w
                if is_quat[name]:
                    v = v / np.linalg.norm(v)
            r[name] = float(v[0]) if f["shape"] == [] else v.reshape(f["shape"]).tolist()
        out_rows.append(r)
    return out_rows, log, unrepaired


def main(a):
    spec = load_spec(a)
    src_dir, out_dir = Path(a.episodes_dir), Path(a.out_dir)
    if src_dir.resolve() == out_dir.resolve():
        sys.exit("OUT_DIR must differ from EPISODES_DIR (repairs never overwrite sources)")
    eps = sorted(p for p in src_dir.iterdir() if (p / "telemetry.jsonl").exists())
    if a.only:
        eps = [p for p in eps if p.name in set(a.only.split(","))]
    summary = []
    for ep in eps:
        lines = [l for l in (ep / "telemetry.jsonl").read_text().splitlines() if l.strip()]
        header = {}
        if lines and '"t_ns"' not in lines[0] and spec["time"]["field"] not in lines[0]:
            header = json.loads(lines[0]); lines = lines[1:]
        frames = json.loads((ep / "frame_map.json").read_text())
        before_rows = []
        for l in lines:
            try:
                before_rows.append(json.loads(l))
            except json.JSONDecodeError:
                pass
        v0, e0, n0 = check(spec, header, before_rows, frames)
        rows, log, unrepaired = repair(spec, header, lines, a)
        v1, e1, n1 = check(spec, header, rows, frames)
        o = out_dir / ep.name; o.mkdir(parents=True, exist_ok=True)
        for f in ep.iterdir():
            if f.name in ("telemetry.jsonl", "meta.json") or not f.is_file():
                continue
            dst = o / f.name
            if dst.exists():
                dst.unlink()
            try:
                os.link(f, dst)
            except OSError:
                shutil.copy2(f, dst)
        (o / "telemetry.jsonl").write_text(("" if not header else json.dumps(header) + "\n") + "".join(json.dumps(r) + "\n" for r in rows))
        meta = json.loads((ep / "meta.json").read_text())
        meta["telemetry_repair"] = {"source": str(ep), "ops": log, "unrepaired": unrepaired, "tool": "vmodal-robot-telemetry-repair@1"}
        (o / "meta.json").write_text(json.dumps(meta, indent=1))
        rec = {"uid": ep.name, "before": v0, "before_errors": n0, "after": v1, "after_errors": n1,
               "ops": log, "unrepaired": unrepaired, "after_first_errors": e1}
        summary.append(rec)
        print(f"{ep.name:<16} before={v0}({n0} err) after={v1}({n1} err) ops={sum(log.values())} unrepaired={len(unrepaired)}"
              + (f" first_unrepaired={unrepaired[0]}" if unrepaired else ""), flush=True)
    (out_dir / "repair_report.json").write_text(json.dumps(summary, indent=1))
    print("wrote", out_dir / "repair_report.json", "- re-run vmodal-robot-qc-batch on", out_dir)
    return 0 if all(s["after"] == "pass" for s in summary) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("episodes_dir"); p.add_argument("out_dir")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec"); g.add_argument("--format_id")
    p.add_argument("--robot_dir", default=os.environ.get("MCP_ROBOT_DIR", str(ROOT / "ztmp/mcp_robot")))
    p.add_argument("--only", default="")
    p.add_argument("--max_nan_run", type=int, default=5)
    p.add_argument("--max_interp_ms", type=float, default=150)
    p.add_argument("--clamp_tol", type=float, default=0.02, help="fraction of range span that may be clamped")
    p.add_argument("--no_quat_continuity", action="store_true")
    sys.exit(main(p.parse_args()))
