---
name: vmodal-robot-telemetry-repair
description: Repair common robot telemetry defects (out-of-order rows, duplicate timestamps, short NaN runs, off-norm or sign-flipping quaternions, small range overshoots, short gaps) into a new episode folder with a repair log and before/after validator verdicts. Use when vmodal-robot-qc-batch rejects episodes for timestamps/NaN/range/unit_norm errors, or before computing VLA action statistics.
---

Fixes the mechanical defects people otherwise patch by hand in notebooks, and refuses to
invent data beyond tight limits. Sources are never modified; every change is counted in
`meta.json → telemetry_repair` and `OUT_DIR/repair_report.json`.

## Steps
1. Know the format: `--format_id NAME@V` (registered) or `--spec FILE`. If the reject is a spec
   problem (wrong unit/range), use **vmodal-robot-format-review** instead; do not "repair" data
   to fit a wrong spec.
2. From the MCP package root:
   `.venv-robot/bin/python skills/vmodal-robot-telemetry-repair/scripts/telemetry_repair.py EPISODES_DIR OUT_DIR --format_id NAME@V [--only uid,...]`
3. Report per episode: before/after verdict, ops applied (counts), and every `unrepaired` item.
4. Re-run **vmodal-robot-qc-batch** on `OUT_DIR` (it re-checks video alignment too). Only
   repaired episodes that pass go forward; point uploads at `OUT_DIR`, not the source folder.

## What it does / refuses
| Defect | Action | Limit (flag) |
|---|---|---|
| unparseable row, row without int time | dropped, counted | - |
| rows out of order | sorted | - |
| duplicate timestamps | keep last | - |
| non-finite values | state: linear interpolation; commands: hold last | run ≤ `--max_nan_run` (5) |
| quaternion norm ≠ 1 | renormalize | - |
| quaternion q→−q flips | negate to keep sign continuity | `--no_quat_continuity` to skip |
| value slightly outside range | clamp | ≤ `--clamp_tol` (2%) of range span |
| gap > `max_gap_ms` | fill at nominal rate (state linear, commands hold) | ≤ `--max_interp_ms` (150) |

Anything beyond a limit is listed under `unrepaired` (e.g. "gap 328.8 ms: split or drop the
episode") and the episode stays `reject`. Ask the user to drop, split or re-export it; never raise
the limits silently. Interpolated rows are real-looking data: mention the inserted row count
when the episode is used for training.

## Test fixture
`.venv-robot/bin/python skills/vmodal-robot-telemetry-repair/tests/make_corrupt.py EPISODES_DIR OUT uid [uid2]`
builds `<uid>_corrupt` (planted defects are all repairable) and `<uid2>_broken`
(two planted `unrepaired` items). With otherwise valid input, the first ends `pass`
and the second stays `reject`. Existing source defects are not removed: the bundled
demo1 current spike still rejects under the strict current range. Regression tests
use a temporary fixture-only current range of [-10, 10] to isolate mechanical
repair behavior; do not use that permissive range as a production safety limit.

The fixture expects clean, uniformly sampled 100 Hz input with at least 80 telemetry
rows (not counting an optional JSONL header). Defect positions scale with episode
length; runs remain long enough to exercise each repair limit. Smaller or differently
sampled inputs fail with a clear error before output is written rather than silently
omitting defects. Removing 6 samples creates a **70 ms** neighbor-to-neighbor gap;
removing 30 creates a **310 ms** gap. JSONL headers are preserved with the new UID.
The bundled 201-row demos can be used directly, including their sibling `meta/` files.

Regression tests (from the MCP package root):
`.venv-robot/bin/python -m unittest discover -s tests -p test_repair_fixture.py`
