# Format review: ? v1

24 episodes, 19968 rows. 0 errors, 10 warnings.

| severity | field | finding | suggested fix |
|---|---|---|---|
| warn | q | unit unknown | ask the data owner; never guess units |
| warn | current | unit unknown | ask the data owner; never guess units |
| warn | gripper | unit unknown | ask the data owner; never guess units |
| warn | ee_pos | unit unknown | ask the data owner; never guess units |
| warn | ee_quat | unit unknown | ask the data owner; never guess units |
| warn | ee_quat | 49 sign flips (q→-q) between consecutive samples | hemisphere-continuity fix (telemetry-repair) before computing action deltas |
| warn | cmd_q | unit unknown | ask the data owner; never guess units |
| warn | cmd_gripper | unit unknown | ask the data owner; never guess units |
| warn | cmd_q,cmd_gripper | no field has role=command; alignment checks treat none as commands | set role=command on these (suggested in the draft) if they are commands |
| warn | placeholders | 14 values still '?' in the suggested draft: fields[0].unit, fields[1].unit, fields[2].unit, fields[3].unit, fields[4].unit, fields[5].unit, fields[6].unit, format_id, time.time_base, video_align.cmd_max_age_ms, video_align.frame_tol_ms, video_align.max_frames_cmd_stale, video_align.max_frames_no_telemetry, video_align.on_fail | a human must fill these |
| info | sampling.rate_tol_pct | per-episode rates need ±6.3% (spec ?) | rate_tol_pct=10 |
| info | sampling.max_gap_ms | largest gap 43.7 ms vs spec ? ms (margin is thin or missing) | keep the limit, investigate the episode; widen only if the gap is real sensor behaviour |
| info | q | range undefined; observed [-3.752, 3.24] | range=[-4.4508, 3.9394] (or physical limits) |
| info | current | range undefined; observed [-7.084, 5.802] | range=[-8.3721, 7.0903] (or physical limits) |
| info | gripper | range undefined; observed [0.0118, 0.6314] | range=[-0.0502, 0.6934] (or physical limits) |
| info | ee_pos | range undefined; observed [-0.1455, 0.5974] | range=[-0.2198, 0.6717] (or physical limits) |
| info | ee_quat | range undefined; observed [-0.786, 0.8321] | range=[-0.9478, 0.9939] (or physical limits) |
| info | cmd_q | range undefined; observed [-3.752, 3.24] | range=[-4.4509, 3.9386] (or physical limits) |
| info | cmd_gripper | range undefined; observed [0, 0.9998] | range=[-0.1, 1.0998] (or physical limits) |
| info | cmd_q→q | state tracks command with ~87 ms lag (median over 24 episodes, corr 0.82) | controller tracking lag, not a format limit: use it when aligning actions to observations (vmodal-robot-norm-stats) |
| info | cmd_gripper→gripper | state tracks command with ~469 ms lag (median over 23 episodes, corr 0.30 — weak, treat as unreliable) | controller tracking lag, not a format limit: use it when aligning actions to observations (vmodal-robot-norm-stats) |
| info | cmd_gripper/gripper | when cmd_gripper is high, gripper is higher (median 0.502 vs 0.012 when low) |  |

Suggested draft: `ztmp/cube_in_cup/skill_runs/format_draft/new_format.v1.draft.json` (checked_by='?'; a human reviews, fills, then registers with `update_json_format_specs_from_file`, bumping format_version — registered versions are immutable).
