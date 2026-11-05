"""Gated, resumable robot episode upload: plan (offline) -> canary -> run -> verify.

usage (from the MCP package root):
  plan   COLLECTION EPISODES_DIR DATASET_REV OUT_DIR --qc QC_REPORT [--exclusions EXCL] [--include_flagged]
  canary CANARY_COLLECTION EPISODES_DIR DATASET_REV OUT_DIR --uid UID --yes
  run    COLLECTION EPISODES_DIR DATASET_REV OUT_DIR --plan OUT_DIR/upload_plan.json --yes [--max_failures 3]
  verify COLLECTION OUT_DIR

plan: no network. Requires a qc-batch report for the same collection/dataset_rev; every planned episode must be
      'pass' (or 'flag' with --include_flagged); exclusions.json (human-reviewed) removes episodes.
run:  uploads exactly the planned episodes, refuses if any input changed since the plan (sha mismatch);
      already-uploaded identical episodes are skipped by the server-side manifest logic (resume).
verify: local manifest statuses vs the server's collection and sub-collection listing.
SDK credentials: the process env (api_key / VMODAL_API_KEY ...) or, if absent, the vmodal MCP server's env block
in ~/.claude.json (secrets are never printed).
"""
import argparse, asyncio, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
CALLER_CWD = Path.cwd()
os.chdir(ROOT)          # SDK/MCP config may hold paths relative to the package root
KEYS = ("api_key", "VMODAL_API_KEY", "VMODAL_API_TOKEN", "TEST_CLIENT_CLERK_USER_API_TOKEN")


def ep_files(ep):
    files = {"video_scene": ep / "cam_scene.mp4", "telemetry_path": ep / "telemetry.jsonl",
             "frame_map_path": ep / "frame_map.json", "meta_path": ep / "meta.json"}
    if (ep / "cam_wrist.mp4").exists():
        files["video_wrist"] = ep / "cam_wrist.mp4"
    return files


def ep_sha(ep):
    h = hashlib.sha256()
    for k, p in sorted(ep_files(ep).items()):
        h.update(k.encode()); h.update(p.read_bytes())
    return h.hexdigest()


def load_env():
    if any(os.environ.get(k) for k in KEYS):
        return "process env"
    cfgp = Path.home() / ".claude.json"
    env = json.loads(cfgp.read_text()).get("mcpServers", {}).get("vmodal", {}).get("env", {}) if cfgp.exists() else {}
    if not env:
        sys.exit("no SDK credentials: set api_key in the environment or configure the vmodal MCP server")
    os.environ.update({k: str(v) for k, v in env.items()})
    return "~/.claude.json vmodal MCP env"


def mcp_cfg():
    src = load_env()
    from src.mcp_server.config import McpConfig
    cfg = McpConfig.from_env()
    if cfg.cfg_error:
        sys.exit(f"SDK config error: {cfg.cfg_error}")
    print(f"server={cfg.sdk.base_url} credentials_from={src} robot_dir={cfg.robot_dir}")
    return cfg


def manifest(robot_dir, coll):
    p = Path(robot_dir) / coll / "episodes.jsonl"
    return {r["episode_uid"]: r for r in (json.loads(l) for l in p.read_text().splitlines() if l.strip())} if p.exists() else {}


async def upload_one(cfg, client, coll, ep, rev, dry):
    from src.mcp_server.robot import robot_episode_upload
    f = {k: str(v) for k, v in ep_files(ep).items()}
    return await robot_episode_upload(cfg, coll, ep.name, f["video_scene"], f["telemetry_path"], f["frame_map_path"],
                                      f["meta_path"], rev, video_wrist=f.get("video_wrist"), dry_run=dry, client=client)


async def server_listing(client, coll):
    from src.mcp_server.utils import collection_listing
    groups = collection_listing(await client.collections.list_groups(), collection_name=coll)["data"]
    subs = collection_listing(await client.admin.user_stats(), subcollections=True, collection_name=coll)["data"]
    return groups, sorted({s["sub_collection_name"] for s in subs})


def cmd_plan(a):
    qc = json.loads(Path(a.qc).read_text())
    s = qc["summary"]
    if s["collection"] != a.collection or s["dataset_rev"] != a.dataset_rev:
        sys.exit(f"qc report is for {s['collection']}@{s['dataset_rev']}, not {a.collection}@{a.dataset_rev}: re-run qc-batch")
    verdict = {e["uid"]: e["verdict"] for e in qc["episodes"]}
    excl = {}
    if a.exclusions:
        ex = json.loads(Path(a.exclusions).read_text())
        excl = {e["episode_uid"]: e for e in ex.get("excluded", [])}
        print(f"exclusions by {ex.get('reviewer')} at {ex.get('reviewed_at')}: {sorted(excl) or 'none'}")
    from src.mcp_server.robot_format import spec_load
    from types import SimpleNamespace
    robot_dir = os.environ.get("MCP_ROBOT_DIR", str(ROOT / "ztmp/mcp_robot"))
    try:
        spec = spec_load(SimpleNamespace(robot_dir=robot_dir), None, a.collection)
    except Exception as exc:
        sys.exit(f"collection {a.collection} has no bound format: {exc}")
    if str(spec.get("checked_by", "?")) in ("?", "") or "pending" in str(spec.get("checked_by")):
        print(f"WARNING format {spec['format_id']}@{spec['format_version']} checked_by={spec.get('checked_by')!r}: not human-approved")
    man = manifest(robot_dir, a.collection)
    plan, blocked = [], []
    for ep in sorted(p for p in Path(a.episodes_dir).iterdir() if (p / "telemetry.jsonl").exists()):
        uid, v = ep.name, verdict.get(ep.name)
        if uid in excl:
            blocked.append((uid, "excluded by review")); continue
        if v is None:
            blocked.append((uid, "not in qc report")); continue
        if v != "pass" and not (v == "flag" and a.include_flagged):
            blocked.append((uid, f"qc verdict {v}")); continue
        state = man.get(uid, {}).get("status", "new")
        size = sum(p.stat().st_size for k, p in ep_files(ep).items() if k.startswith("video"))
        plan.append({"uid": uid, "sha": ep_sha(ep), "server_state": state, "video_bytes": size})
    total = sum(p["video_bytes"] for p in plan)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    doc = {"collection": a.collection, "dataset_rev": a.dataset_rev, "episodes_dir": str(Path(a.episodes_dir).resolve()),
           "format": f"{spec['format_id']}@{spec['format_version']}", "format_checked_by": spec.get("checked_by"),
           "created_at": datetime.now(timezone.utc).isoformat(), "episodes": plan, "blocked": blocked, "video_bytes": total}
    (out / "upload_plan.json").write_text(json.dumps(doc, indent=1))
    todo = [p for p in plan if p["server_state"] != "uploaded"]
    print(f"PLAN {a.collection}: upload {len(todo)} episodes ({total / 1e6:.1f} MB video total incl. {len(plan) - len(todo)} already uploaded), "
          f"blocked {len(blocked)}")
    for uid, why in blocked:
        print(f"  blocked {uid}: {why}")
    print(f"wrote {out / 'upload_plan.json'}; next: canary on a throwaway collection, then `run --plan ... --yes` after user approval")
    return 0


async def cmd_canary(a):
    if not a.yes:
        sys.exit("canary uploads to the server: re-run with --yes after the user approves")
    if not a.uid:
        sys.exit("--uid required (pick the smallest passing episode)")
    from vmodal import Client
    cfg = mcp_cfg()
    ep = Path(a.episodes_dir) / a.uid
    dry = await upload_one(cfg, None, a.collection, ep, a.dataset_rev, True)
    print(f"dry run: {dry['status']} verdict={dry['check_report']['verdict']}")
    if dry["check_report"]["verdict"] == "reject":
        return 1
    async with Client(cfg=cfg.sdk) as client:
        t = time.time()
        r = await upload_one(cfg, client, a.collection, ep, a.dataset_rev, False)
        dt = time.time() - t
        groups, subs = await server_listing(client, a.collection)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    rec = {"collection": a.collection, "uid": a.uid, "status": r["status"], "seconds": round(dt, 1),
           "server_collection": bool(groups), "server_subcollections": subs, "at": datetime.now(timezone.utc).isoformat()}
    (out / "canary.json").write_text(json.dumps(rec, indent=1))
    print(f"CANARY {a.uid} -> {a.collection}: {r['status']} in {dt:.1f}s; server collection={'yes' if groups else 'NO'} sub-collections={subs}")
    ok = r["status"] in ("uploaded", "skipped") and groups and {"cam_scene"} <= set(subs)
    return 0 if ok else 1


async def cmd_run(a):
    if not a.yes:
        sys.exit("run uploads every planned episode: re-run with --yes after the user approves the plan")
    plan = json.loads(Path(a.plan).read_text())
    if plan["collection"] != a.collection or plan["dataset_rev"] != a.dataset_rev:
        sys.exit("plan is for a different collection/dataset_rev")
    changed = [p["uid"] for p in plan["episodes"] if ep_sha(Path(a.episodes_dir) / p["uid"]) != p["sha"]]
    if changed:
        sys.exit(f"inputs changed since the plan: {changed}. Re-run qc-batch and plan.")
    from vmodal import Client
    cfg = mcp_cfg()
    results, fails_in_row = [], 0
    async with Client(cfg=cfg.sdk) as client:
        for i, p in enumerate(plan["episodes"], 1):
            t = time.time()
            try:
                r = await upload_one(cfg, client, a.collection, Path(a.episodes_dir) / p["uid"], a.dataset_rev, False)
                st, err = r["status"], ""
                fails_in_row = 0 if st in ("uploaded", "skipped") else fails_in_row + 1
            except Exception as exc:
                st, err = "error", f"{type(exc).__name__}: {str(exc)[:160]}"
                fails_in_row += 1
            results.append({"uid": p["uid"], "status": st, "seconds": round(time.time() - t, 1), "error": err})
            print(f"[{i}/{len(plan['episodes'])}] {p['uid']:<12} {st:<9} {time.time() - t:5.1f}s {err}", flush=True)
            if fails_in_row >= a.max_failures:
                print(f"STOP after {fails_in_row} consecutive failures; re-run the same command to resume")
                break
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "upload_run.json").write_text(json.dumps(results, indent=1))
    n = {s: sum(r["status"] == s for r in results) for s in sorted({r["status"] for r in results})}
    print("RUN", json.dumps(n), "-> verify next")
    return 0 if set(n) <= {"uploaded", "skipped"} else 1


async def cmd_verify(a):
    from vmodal import Client
    cfg = mcp_cfg()
    man = manifest(cfg.robot_dir, a.collection)
    async with Client(cfg=cfg.sdk) as client:
        groups, subs = await server_listing(client, a.collection)
    counts = {}
    for r in man.values():
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
    partial = sorted(u for u, r in man.items() if r.get("status") == "partial")
    issues = []
    if counts.get("uploaded") and not groups:
        issues.append("manifest says uploaded but the server has no such collection")
    cams = sorted({c for r in man.values() if r.get("status") == "uploaded" for c in (r.get("video_paths") or {})})
    missing = [c for c in cams if c not in subs]
    if missing:
        issues.append(f"sub-collections missing on server: {missing}")
    if partial:
        issues.append(f"partial uploads (re-run `run` to resume): {partial}")
    idx = groups[0].get("lancedb_versions") if groups else []
    rec = {"collection": a.collection, "manifest_status_counts": counts, "server_collection": bool(groups),
           "server_subcollections": subs, "index_versions": idx, "issues": issues}
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "verify.json").write_text(json.dumps(rec, indent=1))
    print(f"VERIFY {a.collection}: manifest={counts} server_collection={'yes' if groups else 'no'} sub-collections={subs} "
          f"index_versions={idx or 'none (not searchable yet)'}")
    for i in issues:
        print("ISSUE", i)
    return 1 if issues else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan"); [s.add_argument(x) for x in ("collection", "episodes_dir", "dataset_rev", "out_dir")]
    s.add_argument("--qc", required=True); s.add_argument("--exclusions"); s.add_argument("--include_flagged", action="store_true")
    s = sub.add_parser("canary"); [s.add_argument(x) for x in ("collection", "episodes_dir", "dataset_rev", "out_dir")]
    s.add_argument("--uid"); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("run"); [s.add_argument(x) for x in ("collection", "episodes_dir", "dataset_rev", "out_dir")]
    s.add_argument("--plan", required=True); s.add_argument("--yes", action="store_true"); s.add_argument("--max_failures", type=int, default=3)
    s = sub.add_parser("verify"); s.add_argument("collection"); s.add_argument("out_dir")
    a = p.parse_args()
    for k in ("episodes_dir", "out_dir", "qc", "exclusions", "plan"):
        if getattr(a, k, None):
            setattr(a, k, str((CALLER_CWD / getattr(a, k)).resolve()))
    if a.cmd == "plan":
        sys.exit(cmd_plan(a))
    sys.exit(asyncio.run({"canary": cmd_canary, "run": cmd_run, "verify": cmd_verify}[a.cmd](a)))
