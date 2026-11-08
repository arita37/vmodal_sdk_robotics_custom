---
name: vmodal-robot-norm-stats
description: Build frame-aligned (30 fps) state/action pairs from vmodal robot episodes and compute VLA normalization statistics (LeRobot-style mean/std/min/max/q01/q99), plus training-readiness checks - zero-variance dims, action discontinuities, gripper binarization threshold, quaternion sign flips, action-to-state lag - with optional per-episode npz export. Use when preparing a robot dataset for VLA/policy training or when asked for norm stats.
---

Normalization stats computed from unchecked data are a classic silent training bug (a single
spike stretches q99; a flipped quaternion doubles a range). This skill computes the stats from
the exact frame/action alignment training will use, after excluding reviewed failures.

## Steps
1. Prerequisites: episodes pass **vmodal-robot-qc-batch**. Failures are reviewed with
   **vmodal-robot-failure-screen** (`exclusions.json`). Quaternions are repaired with
   **vmodal-robot-telemetry-repair** if you use them as features.
2. From the MCP package root:
   `.venv-robot/bin/python skills/vmodal-robot-norm-stats/scripts/norm_stats.py EPISODES_DIR OUT_DIR --format_id NAME@V --exclusions exclusions.json [--state q,gripper] [--action cmd_q,cmd_gripper] [--export OUT_DIR/export]`
   Choose `--state`/`--action` with the user: field names come from the format spec, and
   dimension names come from its `names`.
3. Report: episodes/frames used and excluded, q01–q99 per dimension, zero-variance dims,
   action jumps (episode, frame, dim, delta), gripper threshold, lag result, warnings.
4. Act on findings before training:
   - **action jumps:** inspect the episode (retrieve frames around that frame). Repair or exclude
     it; never let a spike set q99.
   - **zero variance:** drop the dim or use min/max normalization.
   - **quaternion sign flips:** repair, or use another orientation representation.
   - **gripper:** binarize at the suggested threshold if the policy predicts open/close.
5. Hand over `norm_stats.json` (keys `observation.state`, `action`, `action_delta`, each with
   `names`; `_meta` records the format, fields, episodes and alignment rule).

## Alignment used (state it in reports)
- state(frame) = telemetry row nearest the scene-camera timestamp;
- action(frame) = latest command at or before that timestamp (what the controller was executing);
- action_delta = action − matching state dims (`cmd_X` vs `X`).
If the lag is "unresolved at 30 fps", quote the telemetry-rate estimate from
**vmodal-robot-format-review** instead of inventing a frame offset.

## Notes
- `--jump_k` (3) × the 99th percentile of per-frame change, with a floor of `--jump_min`
  (0.05 per frame), defines a jump. Gripper commands are steps by design and are excluded.
- `--export` writes `<uid>.npz` (t_ns, frame_index, state, action as float32) plus `names.json`
  for custom loaders.
