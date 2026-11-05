"""Review a telemetry format spec (registered, drafted, or with '?' placeholders) against real episodes.

usage (from the MCP package root):
  .venv/bin/python skills/vmodal-robot-format-review/scripts/format_review.py SPEC_JSON EPISODES_DIR OUT_DIR

SPEC_JSON: a spec file (e.g. from MCP telemetry_format_draft_from_file, or MCP_ROBOT_DIR/formats/<id>/v<N>.json).
Writes OUT_DIR/format_review.md (findings with evidence) and OUT_DIR/<format_id>.v<N+1>.draft.json
(suggested spec; checked_by='?' so it cannot be mistaken for a human-approved version). Never registers anything.
"""
import argparse, copy, json, math, sys
from pathlib import Path
import numpy as np

SEV = {"error": 0, "warn": 1, "info": 2}


def load_rows(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return [r for r in rows if "t_ns" in r]  # drop an optional header line


def arr(rows, name):
    vals = [r.get(name) for r in rows]
    try:
        return np.array(vals, dtype=float)
    except (TypeError, ValueError):
        return None


def nice_range(lo, hi, margin=0.1):
    span = max(hi - lo, 1e-6)
    return [round(lo - margin * span, 4), round(hi + margin * span, 4)]


def lag_ms(t_ns, cmd, state, max_lag=40):
    """Lag (ms) at which state velocity best follows command velocity (positive = state trails command)."""
    dc, ds = np.diff(cmd, axis=0), np.diff(state, axis=0)
    dc, ds = dc.reshape(len(dc), -1), ds.reshape(len(ds), -1)
    best, best_k = -1e9, 0
    for k in range(0, max_lag):
        a, b = dc[: len(dc) - k], ds[k:]
        if len(a) < 20:
            break
        c = float(np.sum(a * b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        if c > best:
            best, best_k = c, k
    dt = np.median(np.diff(t_ns)) / 1e6
    return best_k * dt, best


def main(a):
    spec = json.loads(Path(a.spec).read_text())
    eps = sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "telemetry.jsonl").exists())
    data = {p.name: load_rows(p / "telemetry.jsonl") for p in eps}
    find, new = [], copy.deepcopy(spec)
    add = lambda sev, field, msg, fix="": find.append({"sev": sev, "field": field, "msg": msg, "fix": fix})
    fields = {f["name"]: f for f in spec["fields"]}
    newf = {f["name"]: f for f in new["fields"]}

    # --- columns present vs spec
    seen = set().union(*[set(r[0]) for r in data.values() if r]) - {"t_ns", "frame_index"}
    for extra in sorted(seen - set(fields)):
        add("error", extra, "column in data but not in spec (extra_fields=reject will fail every row)", "add a field entry")
    for missing in sorted(set(fields) - seen):
        if fields[missing].get("required"):
            add("error", missing, "required in spec but absent from data", "mark required=false or fix the export")

    # --- timing
    rates, gaps = [], []
    for uid, rows in data.items():
        t = np.array([r["t_ns"] for r in rows], dtype=np.int64)
        d = np.diff(t) / 1e6
        if (d <= 0).any():
            add("error", "t_ns", f"{uid}: {int((d <= 0).sum())} non-increasing steps", "vmodal-robot-telemetry-repair")
        rates.append(1000 / np.median(d)); gaps.append(float(d.max()))
    s = spec["sampling"]
    rmin, rmed, rmax = min(rates), float(np.median(rates)), max(rates)
    if s.get("rate_hz") in (None, "?") or abs(rmed / float(s["rate_hz"]) - 1) * 100 > 3:
        add("warn", "sampling.rate_hz", f"spec {s.get('rate_hz')} Hz vs observed median {rmed:.1f} Hz (episodes {rmin:.1f}-{rmax:.1f})",
            f"rate_hz={round(rmed)}")
        new["sampling"]["rate_hz"] = round(rmed)
    tol_needed = max(abs(rmin / new["sampling"]["rate_hz"] - 1), abs(rmax / new["sampling"]["rate_hz"] - 1)) * 100
    if s.get("rate_tol_pct") in (None, "?") or tol_needed > float(s["rate_tol_pct"]) * 0.8:
        add("warn" if s.get("rate_tol_pct") not in (None, "?") and tol_needed > float(s["rate_tol_pct"]) else "info",
            "sampling.rate_tol_pct", f"per-episode rates need ±{tol_needed:.1f}% (spec {s.get('rate_tol_pct')})",
            f"rate_tol_pct={math.ceil(tol_needed + 3)}")
        if s.get("rate_tol_pct") in (None, "?") or tol_needed > float(s["rate_tol_pct"]):
            new["sampling"]["rate_tol_pct"] = math.ceil(tol_needed + 3)
    gmax = max(gaps)
    if s.get("max_gap_ms") in (None, "?") or gmax > float(s["max_gap_ms"]) * 0.85:
        add("warn" if s.get("max_gap_ms") not in (None, "?") else "info", "sampling.max_gap_ms",
            f"largest gap {gmax:.1f} ms vs spec {s.get('max_gap_ms')} ms (margin is thin or missing)",
            "keep the limit, investigate the episode; widen only if the gap is real sensor behaviour")
        if s.get("max_gap_ms") in (None, "?"):
            new["sampling"]["max_gap_ms"] = int(math.ceil(gmax * 1.5 / 10) * 10)

    # --- per-field values
    for name, f in fields.items():
        if name not in seen:
            continue
        vals = [arr(rows, name) for rows in data.values()]
        if any(v is None for v in vals):
            continue
        allv = np.concatenate([v.reshape(len(v), -1) for v in vals])
        n_nan = int((~np.isfinite(allv)).sum())
        if n_nan:
            add("error", name, f"{n_nan} non-finite values", "vmodal-robot-telemetry-repair (short runs) or drop episodes")
        fin = allv[np.isfinite(allv).all(1)]
        lo, hi = float(fin.min()), float(fin.max())
        rng = f.get("range")
        if rng in (None, "?"):
            if rng == "?":
                newf[name]["range"] = nice_range(lo, hi)
                add("info", name, f"range undefined; observed [{lo:.4g}, {hi:.4g}]", f"range={newf[name]['range']} (or physical limits)")
        else:
            out = int(((fin < rng[0]) | (fin > rng[1])).sum())
            if out:
                add("error", name, f"{out} values outside spec range {rng} (observed [{lo:.4g}, {hi:.4g}])", "fix units or widen range")
            elif (hi - lo) < 0.05 * (rng[1] - rng[0]) and f.get("unit") not in ("rad",):
                add("info", name, f"observed span [{lo:.4g}, {hi:.4g}] uses <5% of range {rng}", "a tighter range catches unit errors earlier")
        unit = str(f.get("unit", "?"))
        if unit == "?":
            add("warn", name, "unit unknown", "ask the data owner; never guess units")
        if unit == "rad" and max(abs(lo), abs(hi)) > 2 * math.pi + 0.1:
            add("error", name, f"|value| up to {max(abs(lo), abs(hi)):.2f} > 2π for unit rad", "degrees? check the export")
        if unit == "m" and max(abs(lo), abs(hi)) > 3:
            add("error", name, f"|value| up to {max(abs(lo), abs(hi)):.2f} for unit m", "millimetres? check the export")
        if "unverified" in unit:
            add("warn", name, f"unit '{unit}' is marked unverified", "confirm with the robot vendor/dataset owner")
        if f.get("check") == "unit_norm" or "quat" in name:
            norms = np.linalg.norm(fin, axis=1)
            flips = sum(int((np.sum(v[1:] * v[:-1], 1) < 0).sum()) for v in vals)
            if np.abs(norms - 1).max() > 1e-3:
                add("error", name, f"quaternion norm off by up to {np.abs(norms - 1).max():.3g}", "renormalize (telemetry-repair)")
            if flips:
                add("warn", name, f"{flips} sign flips (q→-q) between consecutive samples", "hemisphere-continuity fix (telemetry-repair) before computing action deltas")
            order = (f.get("unit") or "") + " " + " ".join(f.get("names", []))
            wcol = 3 if "xyzw" in order or (f.get("names") or [""])[-1] == "qw" else 0
            if np.median(np.abs(fin[:, wcol])) < 0.05 and np.median(np.abs(fin).max(1)) > 0.9:
                add("info", name, f"w component (col {wcol}) is ~0 for most samples; orientation is near a 180° flip, so the order cannot be confirmed from data alone",
                    "confirm quaternion order (xyzw vs wxyz) with the source documentation")

    # --- command/state pairs: polarity and lag
    if not any(f.get("role") == "command" for f in fields.values()):
        guessed = [n for n in fields if n.startswith("cmd_")]
        if guessed:
            add("warn", ",".join(guessed), "no field has role=command; alignment checks treat none as commands",
                "set role=command on these (suggested in the draft) if they are commands")
            for n in guessed:
                newf[n]["role"] = "command"
    for name, f in fields.items():
        if f.get("role") != "command" and not (name.startswith("cmd_") and not any(x.get("role") == "command" for x in fields.values())):
            continue
        state = name[4:] if name.startswith("cmd_") else None
        if state not in fields or state not in seen:
            add("info", name, "command has no matching state field; lag/polarity not checked")
            continue
        lags, cors, hi_state, lo_state = [], [], [], []
        for rows in data.values():
            c, st = arr(rows, name), arr(rows, state)
            t = np.array([r["t_ns"] for r in rows])
            if len(rows) > 60 and np.ptp(c) > 1e-6:
                lm, cor = lag_ms(t, c, st); lags.append(lm); cors.append(cor)
            if c.ndim == 1:
                mid = (c.min() + c.max()) / 2
                if c.max() - c.min() > 0.5:
                    hi_state.append(float(np.median(st[c > mid][-max(1, (c > mid).sum() // 2):])))
                    lo_state.append(float(np.median(st[c <= mid])))
        if lags:
            lag_med = float(np.median(lags))
            weak = " — weak, treat as unreliable" if np.median(cors) < 0.5 else ""
            add("info", f"{name}→{state}", f"state tracks command with ~{lag_med:.0f} ms lag (median over {len(lags)} episodes, corr {np.median(cors):.2f}{weak})",
                "controller tracking lag, not a format limit: use it when aligning actions to observations (vmodal-robot-norm-stats)")
        if hi_state:
            closes_up = np.median(hi_state) > np.median(lo_state)
            u = str(f.get("unit", "")) + " " + str(fields[state].get("unit", ""))
            says_zero_closed = "0_closed" in u or "1_open" in u
            says_zero_open = "0_open" in u or "1_closed" in u
            add("info", f"{name}/{state}", f"when {name} is high, {state} is {'higher' if closes_up else 'lower'} "
                f"(median {np.median(hi_state):.3f} vs {np.median(lo_state):.3f} when low)")
            if (closes_up and says_zero_closed) or (not closes_up and says_zero_open):
                add("error", f"{name}/{state}", f"polarity in unit strings ({u.strip()}) contradicts the data",
                    "fix the unit label, e.g. normalized_grip_pos_0_open; failure detectors key on it")
                for k in (name, state):
                    if closes_up:
                        newf[k]["unit"] = newf[k]["unit"].replace("0_closed", "0_open").replace("1_open", "1_closed")

    # --- placeholders left
    def holes(o, p=""):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from holes(v, f"{p}.{k}".strip("."))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from holes(v, f"{p}[{i}]")
        elif o == "?":
            yield p
    left = [h for h in holes(new) if h not in ("checked_by", "checked_at")]
    if left:
        add("warn", "placeholders", f"{len(left)} values still '?' in the suggested draft: {', '.join(left)}", "a human must fill these")

    new["format_version"] = int(spec.get("format_version", 0) or 0) + 1 if spec.get("checked_by") not in (None, "?") else spec.get("format_version", 1)
    new["checked_by"], new["checked_at"] = "?", "?"
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    fid = spec.get("format_id") if spec.get("format_id") not in (None, "?") else "new_format"
    draft = out / f"{fid}.v{new['format_version']}.draft.json"
    draft.write_text(json.dumps(new, indent=1))
    find.sort(key=lambda x: SEV[x["sev"]])
    md = [f"# Format review: {spec.get('format_id')} v{spec.get('format_version')}", "",
          f"{len(eps)} episodes, {sum(len(r) for r in data.values())} rows. "
          f"{sum(x['sev'] == 'error' for x in find)} errors, {sum(x['sev'] == 'warn' for x in find)} warnings.", "",
          "| severity | field | finding | suggested fix |", "|---|---|---|---|"]
    md += [f"| {x['sev']} | {x['field']} | {x['msg']} | {x['fix']} |" for x in find]
    md += ["", f"Suggested draft: `{draft}` (checked_by='?'; a human reviews, fills, then registers with "
           "`update_json_format_specs_from_file`, bumping format_version — registered versions are immutable)."]
    (out / "format_review.md").write_text("\n".join(md) + "\n")
    for x in find:
        print(f"{x['sev'].upper():5} {x['field']}: {x['msg']}" + (f"  -> {x['fix']}" if x["fix"] else ""))
    print("wrote", out / "format_review.md", "and", draft)
    return 1 if any(x["sev"] == "error" for x in find) else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("spec"); p.add_argument("episodes_dir"); p.add_argument("out_dir")
    sys.exit(main(p.parse_args()))
