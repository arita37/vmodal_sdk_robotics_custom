# Format review: ur7e_gripper_raw_76hz v1

24 episodes, 19968 rows. 1 errors, 3 warnings.

| severity | field | finding | suggested fix |
|---|---|---|---|
| error | cmd_gripper/gripper | polarity in unit strings (normalized_grip_cmd normalized_grip_pos_0_closed) contradicts the data | fix the unit label, e.g. normalized_grip_pos_0_open; failure detectors key on it |
| warn | sampling.max_gap_ms | largest gap 43.7 ms vs spec 50 ms (margin is thin or missing) | keep the limit, investigate the episode; widen only if the gap is real sensor behaviour |
| warn | current | unit 'ur_effort_unverified' is marked unverified | confirm with the robot vendor/dataset owner |
| warn | ee_quat | 49 sign flips (q→-q) between consecutive samples | hemisphere-continuity fix (telemetry-repair) before computing action deltas |
| info | cmd_q→q | state tracks command with ~87 ms lag (median over 24 episodes, corr 0.82) | controller tracking lag, not a format limit: use it when aligning actions to observations (vmodal-robot-norm-stats) |
| info | cmd_gripper→gripper | state tracks command with ~469 ms lag (median over 23 episodes, corr 0.30 — weak, treat as unreliable) | controller tracking lag, not a format limit: use it when aligning actions to observations (vmodal-robot-norm-stats) |
| info | cmd_gripper/gripper | when cmd_gripper is high, gripper is higher (median 0.502 vs 0.012 when low) |  |

Suggested draft: `ztmp/cube_in_cup/skill_runs/format_review/ur7e_gripper_raw_76hz.v2.draft.json` (checked_by='?'; a human reviews, fills, then registers with `update_json_format_specs_from_file`, bumping format_version — registered versions are immutable).
