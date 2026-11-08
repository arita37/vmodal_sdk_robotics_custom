---
name: vmodal-robot-qc-batch
description: Validate a whole folder of robot episodes against the vmodal telemetry format in one dry run, with one line per episode, metadata completeness checks and collection-level outlier flags. Use before any robot upload, after conversion or repair, or when asked "are these episodes valid / ready".
---

Batch replacement for calling the `robot_episode_upload` MCP tool once per episode: that tool
returns every frame (~30k tokens per episode). This script calls the same validator from Python
with `dry_run=True` and no SDK client, so nothing leaves the machine.

## Inputs
- `COLLECTION` with a bound format (`telemetry_format_list` shows bindings), or pass `--format_id NAME@V`.
  No format yet → run **vmodal-robot-format-review** first, then have the user register it.
- `EPISODES_DIR/<uid>/` with `cam_scene.mp4`, optional `cam_wrist.mp4`, `frame_map.json`, `telemetry.jsonl`, `meta.json`.
- `DATASET_REV`: one collection holds one dataset revision (the validator returns 409 otherwise).

## Steps
1. Confirm the binding: MCP `telemetry_format_list(format_id=...)`. Never silently re-bind a collection.
2. From the MCP package root run:
   `.venv-robot/bin/python skills/vmodal-robot-qc-batch/scripts/qc_batch.py COLLECTION EPISODES_DIR DATASET_REV OUT_DIR`
   (`--only take_01,take_02` for a subset). Note: a dry run writes local check reports and a
   `validated` manifest row under `MCP_ROBOT_DIR/COLLECTION/`; it never downgrades an uploaded row.
3. Read `OUT_DIR/qc_report.json` → `summary`. Report a table: uid, frames, verdict, first error,
   outliers, meta errors (`qc_table.md` is ready to paste).
4. Triage:
   - `reject`/`exception` → fix input (format mismatch → format-review; timestamps/NaN/quaternions →
     **vmodal-robot-telemetry-repair**; video length/CFR → **vmodal-robot-sync-audit**).
   - `flag` → alignment limits exceeded; run sync-audit before deciding.
   - `outliers` → valid but unlike siblings (duration, gaps, sync). Hand them to
     **vmodal-robot-failure-screen**; an outlier is a question, not a verdict.
   - `meta_errors` → VLA training needs `task` (instruction text), `success`, `robot_id`, `length`.
5. State plainly that `pass` means well-formed, not a successful demonstration.

## Rules
- Exit code 1 when any episode is not `pass`; quote the counts, never round them away.
- Do not edit episodes in place; corrections go to a new folder and get re-checked.
