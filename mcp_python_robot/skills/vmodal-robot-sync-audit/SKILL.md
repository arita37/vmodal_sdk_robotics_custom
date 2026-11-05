---
name: vmodal-robot-sync-audit
description: Audit camera and telemetry synchronization of robot episodes - decoded frames vs frame map, 30 fps CFR, wrist-camera offsets and frozen frames, telemetry coverage, and a motion-based video-to-telemetry lag estimate with confidence intervals - plus visual gripper-event strips to verify suspects and a controlled time-shift correction. Use when episodes are flagged for alignment, before VLA training, or when observations and actions may be out of step.
---

Misaligned observations and actions train a policy on the wrong pairs, yet every format check
passes. This skill measures alignment, separates real problems from estimator noise, and only
corrects with explicit confirmation.

## Steps
1. Audit (from the MCP package root):
   `.venv/bin/python skills/vmodal-robot-sync-audit/scripts/sync_audit.py audit EPISODES_DIR OUT_DIR`
   One line per episode, then `AGGREGATE` and `RECOMMEND` lines; details in `OUT_DIR/sync_audit.json`.
2. Structural issues (hard facts, act on them): decoded frames ≠ frame map, non-CFR video,
   video outside telemetry coverage by more than half a frame, wrist camera frozen ≥ 3 frames.
3. Motion lag (an estimate, treat as evidence only): `lag_ms` maximizes correlation between
   image motion energy and robot speed; `lag_ci_ms` is the plateau within 0.05 of the peak.
   With smooth teleoperation the resolution is about ±80 ms, so it catches **gross** desync
   (hundreds of ms or more, wrong clock, time zone), not single-frame offsets.
4. Verify every motion-lag outlier visually before saying "desync":
   `sync_audit.py event_strip EPISODES_DIR OUT_DIR --only uid[,uid]` → per camera a 5-frame strip at
   −600/−300/0/+300/+600 ms around the first gripper change in telemetry. Open the PNGs: the
   fingers should start moving between the 0 and +300 ms frames. Show the strips to the user.
5. Correct only a confirmed, consistent offset, with user approval:
   `sync_audit.py shift EPISODES_DIR OUT_DIR --offset_ms X [--only ...]` (telemetry `t_ns += X`, the rest
   hard-linked, `meta.sync_correction` records it). Then re-run **vmodal-robot-qc-batch** on OUT_DIR.

## Rules
- Never shift a whole collection on the motion estimate alone; `RECOMMEND` only proposes it
  when the median lag exceeds both half a frame and the resolution, and episodes agree (MAD < resolution).
- Clips under 3 s get no lag estimate (too little motion).
- Report outliers as "flagged for visual check", and the event-strip result as the verdict.
