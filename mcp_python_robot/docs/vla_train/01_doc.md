# MCP robot: episode upload with telemetry, frame+telemetry retrieval, similar-failure skill

Date: 2026-11-03
Version: 0.2 (draft, not built). 0.2: telemetry format is a user-provided JSON spec (C2),
registered with `update_json_format_specs_from_file` (P0) and used to check every upload
against the video frames (C2c, P1).
Input: `docs/vla_train/00_doc.md` (Casey Clark, M1 data stack, 2026-10-22)
Samples: `docs/vla_train/telemetry.jsonl` (10 rows), `docs/vla_train/gen_telemetry.py`

Labels: **Exists** = in `mcp_python_robot` / `sdk_python` today. **New** = proposed here.
**Backend** = needs a server change outside this package. **Open** = to agree.


## User Specs:

1. Data upload with telemetry as JSON.
2. Retrieve, for one search hit or one time point: image frame(s) + timestamp + telemetry JSON.
3. Skills for: "Finding similar failures in old data is slow for me now ... search for one
   failure, find all the episodes like it."
4. The telemetry data format is provided by the user as a JSON spec file, after the user has
   checked it. MCP tool `update_json_format_specs_from_file` registers/updates it in the MCP
   config (P0).
5. That JSON format spec is used to check each telemetry upload together with its video
   frames (P1, report C2c).

Customer context (from 00_doc.md): xArm 6 + gripper, scene cam (D415) + wrist cam (D405),
~1,000 episodes x ~150 s, 30 fps video, 100 Hz telemetry (joints, current, gripper, TCP pose,
command). Stable key = `episode_uid`. Time base = int64 `t_ns` (UTC, host clock, offset
corrected). Tags go to the 2f schema with `review_status = unreviewed`. Unreviewed search hits
must never remove data (Flow 2).


------------------------------------------------------------------------
## Scope:

- `uinterface/mcp_python_robot/src/mcp_server/` : new robot tools (upload, retrieve, robot search).
- `uinterface/mcp_python_robot/skills/` : new skill `vmodal-robot-similar` (+ catalog, scripts).
- `uinterface/mcp_python_robot/tests/`, `ztmptest/robot/` : fixtures + tests.
- `uinterface/mcp_python_robot/docs/` : `robot_contract.md`, update `tool_contract.md`.
- Out of scope for this package (listed as **Backend**): server-side telemetry storage/serving,
  metadata filters inside `/search`, per-frame telemetry in the index.

Not changed: `sdk_python` API contract. The MCP composes existing SDK calls; any new route goes
to `sdk_python` first (repo coupling rule), then MCP mirrors it.


## What exists today (relevant surface)

- `collection_video_upload` / `collection_video_upload_bulk`: signed upload of local mp4.
- `collection_upload_metadata`: JSONL upload. With `mode=vid_file` only `video` is required;
  `title` / `description` / `duration` are columns, every other key is packed into the row
  `info_json`. One row per video. Not designed for 15k telemetry rows per episode.
- `find`: text and/or one image query, `collection_name`, optional `sub_collection_name`,
  `limit`, `offset`, `save_images`. No metadata filters.
- Hits: `mode, group_name, stream_name, modality=vid_img, filename, ts_unix_13digits` + `score`.
  `ts_unix_13digits` < 1e12 = millisecond offset inside the video.
- `image_download_from_records`: 1..20 records -> JPEG at
  `{root}/{collection}/{stream}/{stem}_{ts13}.jpg`. Only indexed frames exist.
- Indexed frames observed on whole seconds, about 1 frame per second, with gaps
  (historical dashcam test 2026-10-13). A drop that lasts a few frames can fall
  between two indexed frames.
- Included skills: `vmodal-find` (verify on frames) and `vmodal-robot-similar`
  (failure catalog, telemetry scans and candidate tags). Review returned scene/wrist frames
  directly; this checkout does not include a contact-sheet helper.


## Critical invariant

1. `episode_uid` is the only cross-system key. On VModal: `filename` stem == `episode_uid`.
   The upload rejects an `episode_uid` that the filename sanitizer would change (no silent
   rename, no collision).
2. `t_ns` from the customer frame map is the time truth. A VModal offset is only used to find
   a `frame_index`; `t_ns` always comes from a frame-map lookup, never from `t0 + offset`.
   Chain: `ts_unix_13digits (ms offset)` -> `frame_index = round(offset_ms * fps / 1000)` ->
   `frame_map[frame_index].t_scene_ns`. Valid only because the uploaded clip is CFR and starts at
   the episode frame 0 (checked at upload, see P1). Exact formulas and the reverse direction:
   C9. `t0_ns + offset_ms * 1e6` is wrong by up to several frames (measured capture rate differs
   from the CFR position, C9 check 6).
3. The user format spec (C2) is the only source of truth for the telemetry layout. Field
   names, sub-names, units, shapes and ranges come from it, never from position and never
   guessed by the MCP (pain point: same vector length, different meaning). A header line in
   a data file is checked against the spec; it never overrides it.
4. Every hit and every tag carries `index_version` (`version_lancedb` returned by `find`) and
   `dataset_rev`. Without both, a hit is not reproducible.
5. Skills write tags only as `source=auto`, `review_status=unreviewed`, `confidence=null`
   (unless a versioned telemetry detector sets it). Skills never write `accepted` and never
   delete or exclude episodes.
6. Source of truth stays on the customer side (MCAP / LeRobot / frame map / sidecar).
   Everything uploaded to VModal is a derived copy, rebuildable from the source + `dataset_rev`.
7. A registered spec version is immutable. Any change = new `format_version`. Each uploaded
   episode records `format_id`, `format_version`, `format_sha256`, so old uploads stay
   checkable against the exact spec they passed.
8. No telemetry upload without a check against frames: an episode is uploaded only if its
   C2c report verdict is `pass` (or `flag` when the spec allows it). Videos and telemetry of
   one episode are uploaded together or not at all.


## Data Contract

### C1. Collection layout on VModal (New convention, existing storage)

- `collection_name` = dataset, e.g. `xarm_pick_r12` (one per `dataset_rev`, or one per dataset
  with `dataset_rev` in metadata: **Open**; default one per rev, simplest to reason about).
- `sub_collection_name` = camera: `cam_scene`, `cam_wrist`.
- `filename` = `{episode_uid}.mp4`, one clip per episode per camera, 30 fps CFR, frame 0 =
  episode frame 0, frame count == episode `length`. ffprobe `avg_frame_rate` must be exactly
  `30/1` (not 30000/1001): the backend samples every `int(fps)` frames, so 29.97 gives a step of
  29 frames and timestamps off whole seconds (C9).
- `episode_uid` must match `[A-Za-z0-9_]+`: the backend sanitizer
  (`frame_sampler.frame_sample_video`) maps every other character to `_` and collapses `__`, so
  a UUID with `-` would not round-trip (invariant 1).
- Upload in offset mode: no `start_datetime_user`. Then `ts_unix_13digits` = offset in the clip.
  Epoch mode is possible but adds a rounded start (C9 check 5) and gives nothing the frame map
  does not already give.
- Wrist clip is row-aligned with scene (one wrist frame per dataset row, as in LeRobot), so the
  same offset means the same `frame_index` in both streams.

### C2. Telemetry format spec (New, provided and checked by the user)

The user owns the telemetry format. It is one JSON file per format, written or approved by
the user, then registered with `update_json_format_specs_from_file` (P0). MCP does not ship
a fixed telemetry schema; `vmodal_robot_telemetry/1` below is only the sample for this
customer.

Example `xarm6_gripper_100hz.format.json` (matches `telemetry.jsonl`):

```json
{
  "format_id": "xarm6_gripper_100hz",
  "format_version": 1,
  "description": "xArm 6 + gripper, /xarm/* + /teleop/joint_cmd at 100 Hz (00_doc.md 2a, 2e)",
  "checked_by": "casey",
  "checked_at": "2026-11-03",
  "file": {"type": "jsonl", "header_line": "optional", "compression": ["none", "gzip"]},
  "time": {"field": "t_ns", "dtype": "int64", "unit": "ns",
           "time_base": "t_ns_utc_host_offset_corrected", "order": "strictly_increasing"},
  "sampling": {"mode": "time", "rate_hz": 100, "rate_tol_pct": 10, "max_gap_ms": 20},
  "fields": [
    {"name": "q",           "dtype": "float", "shape": [6], "names": ["j1","j2","j3","j4","j5","j6"], "unit": "rad", "required": true, "range": [-6.3, 6.3]},
    {"name": "current",     "dtype": "float", "shape": [6], "names": ["j1","j2","j3","j4","j5","j6"], "unit": "A",   "required": true, "note": "controller estimate"},
    {"name": "gripper",     "dtype": "float", "shape": [],  "unit": "0_open_1_closed", "required": true, "range": [0, 1]},
    {"name": "ee_pos",      "dtype": "float", "shape": [3], "names": ["x","y","z"], "unit": "m", "required": true},
    {"name": "ee_quat",     "dtype": "float", "shape": [4], "names": ["qx","qy","qz","qw"], "unit": "quat_xyzw", "required": true, "check": "unit_norm"},
    {"name": "cmd_q",       "dtype": "float", "shape": [6], "names": ["j1","j2","j3","j4","j5","j6"], "unit": "rad", "required": true, "role": "command"},
    {"name": "cmd_gripper", "dtype": "float", "shape": [],  "unit": "0_open_1_closed", "required": true, "range": [0, 1], "role": "command"}
  ],
  "extra_fields": "reject",
  "nan_policy": "reject",
  "video_align": {"ref_camera": "cam_scene", "frame_tol_ms": 16.7, "cmd_max_age_ms": 20,
                  "coverage": "full", "max_frames_no_telemetry": 0,
                  "max_frames_cmd_stale": 0, "on_fail": "reject"}
}
```

Spec rules (checked at registration, P0):
- `format_id` matches `[a-z0-9_]+`; `format_version` int >= 1.
- `fields[].name` unique; `shape` [] = scalar; `names` length == shape product when given.
- Every field has a `unit` (`quat_xyzw`, `0_open_1_closed`, `none` are valid units). No `"?"`
  left anywhere: the draft tool writes `"?"` for what it cannot infer, so a spec is only
  registrable after the user has filled and checked it.
- `sampling.mode`:
  - `time`: rows keyed by `time.field` (`t_ns`), own rate, aligned to frames by time.
  - `frame`: one row per video frame, keyed by `frame_index` (0..n_frames-1, contiguous),
    for 30 fps state exports such as LeRobot `observation.state` + `action`.
- `role: command` marks fields aligned with the zero-order-hold rule (00_doc.md 3b):
  latest row with `t_ns <= t_scene_ns`, age <= `cmd_max_age_ms`.
- `video_align.on_fail`: `reject` (episode not uploaded) or `flag` (uploaded, flagged in C4).

### C2b. Telemetry data file (New, upload input, must conform to a registered C2 spec)

Accepted input: `.json` (array of rows, or `{"header":..,"rows":[..]}`), `.jsonl`,
`.jsonl.gz`. Also `.parquet` (2e sidecar), read with the same field names. Canonical stored
form: JSONL.gz, line 1 = header, lines 2.. = rows.

Header line in the input is optional (`file.header_line`). If present it must not contradict
the spec: same field names, sub-names and units, and `format_id` / `format_version` equal
to the spec bound to the collection (legacy `schema` key accepted as `format_id`). The
stored header is always rewritten from the spec:
`{"format_id", "format_version", "format_sha256", "episode_uid"}`.

Sample input header in `telemetry.jsonl` (customer format, before registration):

```
line 1 (header):
{"schema": "vmodal_robot_telemetry/1",
 "episode_uid": "ep_000412", "time_base": "t_ns_utc_host_offset_corrected",
 "rate_hz": 100,
 "fields": [
   {"name": "q",           "names": ["j1","j2","j3","j4","j5","j6"], "unit": "rad"},
   {"name": "current",     "names": ["j1","j2","j3","j4","j5","j6"], "unit": "A", "note": "controller estimate"},
   {"name": "gripper",     "unit": "0_open_1_closed"},
   {"name": "ee_pos",      "names": ["x","y","z"], "unit": "m"},
   {"name": "ee_quat",     "names": ["qx","qy","qz","qw"]},
   {"name": "cmd_q",       "names": ["j1","j2","j3","j4","j5","j6"], "unit": "rad"},
   {"name": "cmd_gripper", "unit": "0_open_1_closed"}]}
line 2..:
{"t_ns": 1761130000123456789, "q": [...6], "current": [...6], "gripper": 0.0,
 "ee_pos": [...3], "ee_quat": [...4], "cmd_q": [...6], "cmd_gripper": 0.0}
```

Row rules all come from the spec: time field dtype + order, every `required` field present
with the declared shape, `range` and `check` (e.g. `unit_norm` for the quaternion, tol 1e-3),
`nan_policy`, `extra_fields`. Size: 15k rows x ~40 floats ~ 6 MB raw, ~1.5 MB gzip.

### C2c. Upload check report: telemetry vs video frames (New, MCP output per episode)

Written to `{MCP_ROBOT_DIR}/{collection}/checks/{episode_uid}.json` and summarized in C4/C5.
Inputs: telemetry file (C2b), registered spec (C2), frame map (C3), decoded clip(s).

```json
{"episode_uid": "ep_000412", "format_id": "xarm6_gripper_100hz", "format_version": 1,
 "format_sha256": "…", "verdict": "pass",
 "file":   {"n_rows": 15230, "header": "match", "n_bad_rows": 0, "errors": []},
 "time":   {"t_first_ns": 1761130000000000000, "t_last_ns": 1761130152300000000,
            "rate_hz_median": 100.0, "n_gaps": 0, "gap_ms_max": 10.2, "gaps": []},
 "video":  {"cam_scene": {"n_frames_decoded": 4569, "fps": 30.0, "cfr": true},
            "cam_wrist": {"n_frames_decoded": 4569, "fps": 30.0, "cfr": true},
            "n_frames_frame_map": 4569},
 "align":  {"coverage_ok": true, "lead_ms": 3.1, "tail_ms": 6.8,
            "n_frames_no_telemetry": 0, "dt_ms_max": 5.0, "dt_ms_mean": 2.5,
            "rows_per_frame_mean": 3.33, "n_frames_cmd_stale": 0, "cmd_age_ms_max": 9.9},
 "errors": [], "warnings": []}
```

Checks, in order (first failing group sets `verdict`):
1. **File vs spec**: parse, header match, per-row field/shape/dtype/range/NaN/extra (C2b).
2. **Time vs spec**: order, median rate within `rate_tol_pct` of `rate_hz`, gaps > `max_gap_ms`
   listed with start/end `t_ns` (never interpolated over).
3. **Video**: decoded frame count per camera == frame map rows == episode `length`; CFR at
   the spec / dataset fps (issue 1).
4. **Telemetry vs frames** (`sampling.mode=time`):
   - coverage: `t_first_ns <= t_scene_ns[0] + frame_tol` and `t_last_ns >= t_scene_ns[-1] - frame_tol`;
   - per frame: nearest telemetry row, `|dt| <= frame_tol_ms`, count misses -> `n_frames_no_telemetry`;
   - per frame, `role=command` fields: latest row `<= t_scene_ns`, age `<= cmd_max_age_ms`,
     count -> `n_frames_cmd_stale`;
   - `rows_per_frame_mean` (expected `rate_hz / fps`, 3.33 here) as a sanity value.
   (`sampling.mode=frame`): `frame_index` set == `0..n_frames-1`, no duplicates.
5. **Verdict**: `pass` if all within spec limits; else `video_align.on_fail` -> `reject` or `flag`.

Side output: `{MCP_ROBOT_DIR}/{collection}/frame_index/{episode_uid}.jsonl.gz`, one row per frame
`frame_index, t_scene_ns, tel_row, tel_dt_ms, cmd_row, cmd_age_ms`. P2 retrieve reads it instead
of searching telemetry again.

### C3. Frame map JSON (New, upload input)

Per episode, from `revisions/{rev}/frame_map.parquet` (2d) or JSON with the same columns:
`frame_index, t_scene_ns, t_wrist_ns, wrist_dt_ms, wrist_repeated`. Required to resolve hits
to `t_ns` (invariant 2). Stored next to telemetry, same canonical JSONL.gz form.

### C4. Episode metadata row (Exists route, new keys)

One `vid_file` JSONL row per clip via `collection_upload_metadata`:
`video` = `{episode_uid}.mp4`, `title` = task, `duration` = `duration_s`; packed into
`info_json`: `episode_uid, fleet_id, robot_id, operator_id, start_time, success, task_index,
dataset_rev, fps, n_frames, t0_ns, telemetry_ref, frame_map_ref, info_json_sha256` and the sync
report fields from 3a/3b: `sync_offset_ms_max, sync_offset_ms_mean, wrist_dt_ms_max,
wrist_dt_ms_mean, n_dropped, cmd_age_ms_max, cmd_latency_ms`, plus the format and check
summary: `format_id, format_version, format_sha256, check_verdict, n_frames_no_telemetry,
n_frames_cmd_stale, telemetry_gap_ms_max`.

### C5. Local episode manifest + MCP robot config (New, MCP side)

`{MCP_ROBOT_DIR}/{collection}/episodes.jsonl`: same keys as C4 + local paths of telemetry,
frame map, check report and frame index. Written by upload, read by retrieve/search. Needed
because no SDK read path for `info_json` is known today (**Open**). Rebuildable from the dataset
folder (`robot_manifest_build`).

Format registry (the "config" updated by P0):

```
{MCP_ROBOT_DIR}/formats/{format_id}/v{format_version}.json     registered spec, immutable
{MCP_ROBOT_DIR}/formats/index.json                             format_id -> versions, sha256, checked_by/at, registered_at
{MCP_ROBOT_DIR}/{collection}/collection.json                   {"telemetry_format": "xarm6_gripper_100hz@1", "fps": 30, "cameras": [...]}
```

The collection binding selects the spec used by uploads into that collection. Rebinding a
collection to a new version only affects later uploads; existing episodes keep their recorded
version (invariant 7). Phase B (**Backend**, **Open**): store the spec in VModal collection
metadata so every machine and teammate checks against the same file.

### C6. Robot search hit (New, MCP output) = 00_doc.md section 5 contract

```
query_id, episode_uid, t_start_ns, t_end_ns, t_ns, frame_index, relevance, modality,
index_version, dataset_rev, camera, record (raw VModal selector, unchanged)
```

`t_start_ns / t_end_ns` = hit time +/- half the indexed sampling step (about +/- 0.5 s), exclusive end.
`relevance` = the VModal `score`, rank only, not a probability (scale **Open**, Casey Q2).

### C7. Retrieve result (New, MCP output)

```
{"episode_uid", "t_ns", "frame_index", "t_scene_ns", "t_wrist_ns", "wrist_dt_ms",
 "wrist_repeated", "images": {"cam_scene": "/abs/path.jpg", "cam_wrist": "/abs/path.jpg"},
 "image_source": "vmodal_index" | "local_decode",
 "telemetry": {"format": {"format_id", "format_version", "fields": [...C2 spec fields...]},
               "t_from_ns", "t_to_ns", "rate_hz", "rows": [...]},
 "telemetry_summary": {"current_abs_max": {"j1":..}, "gripper_min", "gripper_max",
                       "tcp_speed_max_mps", "cmd_vs_state_gripper_max"},
 "state_at_t": {"q": {...by name...}, "gripper": .., "ee_pos": {...}},
 "sync": {...C4 sync fields...}, "dataset_rev", "index_version", "errors": []}
```

A `.json` sidecar with the same content is written next to each saved JPEG.

### C9. Time conversion `t_ns` <-> `ts_unix_13digits` (verified 2026-11-03)

Backend sources read:
- `vmx_avideo/embed/src/processors/frame_sampler.py` (decord path, default 1 fps):
  `frame_interval = max(1, int(fps / frame_per_sec))`, indices `0, interval, 2*interval, …`,
  `ts_ms = int((idx / fps) * 1000)` (float, truncated), `fps = decord get_avg_fps()`.
  The ffmpeg fallback uses `ts_ms = int((k / frame_per_sec) * 1000)` on the k-th output frame.
  Near-duplicate frames (SSIM / gray-similar / single-color) are dropped, so idle robot periods
  have fewer indexed frames.
- `os_frame_paths_rebase_user_timestamp`: epoch mode only, `ts = start_ms + offset_ms`.
- `eglobals/src/data_metadata.py::str_cctv_datetime_normalize`:
  `start_ms = int(round(datetime.fromisoformat(iso).timestamp() * 1000))`.
- Search API (`frontui_search.py`) returns `ts_unix_13digits` as a string zero-padded to 13 digits;
  image fetch (`apionly_serve_img.py`) accepts at most 13 digits and matches the frame exactly.

Formulas (MCP side, offset mode):

```
hit -> frame:   offset_ms   = int(ts_unix_13digits)                 # string, 13 digits, < 1e12
                frame_index = round(offset_ms * fps / 1000)          # fps = 30 (clip, checked == 30/1)
                t_ns        = frame_map[frame_index].t_scene_ns      # int64, lookup, never arithmetic
                t_start_ns, t_end_ns from neighbor indexed frames (C6)
frame -> ts:    ts_ms       = int((frame_index / fps) * 1000)        # exact backend formula, float
                ts_unix_13digits = str(ts_ms).zfill(13)
                only valid for frames the sampler kept; else "image not found" -> local decode (P2)
t_ns -> frame:  frame_index = nearest t_scene_ns in frame map, |dt| <= 16.7 ms (2d), else no_frame
ns -> ms (display / epoch only): ms = t_ns // 1_000_000              # integer floor, never float
```

Checks run (`scratchpad check_ts.py`, `check_ts2.py`, 4,569 frames = 152 s at 30 fps):
1. `1761130004001200000 // 1_000_000 = 1761130004001`, 13 digits. Floor and round differ by 1 ms
   for sub-ms fractions >= 0.5; use floor (integer) everywhere; never `round(t_ns / 1e6)`.
2. `float(t_ns)` is not exact (ulp 256 ns; round trip gives +128 ns). Python `json` keeps int64
   exact; jq / JavaScript / a pandas column with NaN turn `t_ns` into float. Keep `t_ns` int64 in
   every reader; frame-map joins on `t_ns` must be nearest-within-tolerance, never equality.
3. Backend `int((idx / 30.0) * 1000)` differs from exact `idx * 1000 // 30` for 10 frames
   (969, 1923, …, 3921: e.g. 32299.99… -> 32299). None is a multiple of 10 or 30, so 1 fps and
   3 fps sampled frames are exact. MCP must still replicate the float formula, not integer math,
   when it builds a `ts` to fetch a frame.
4. Inverse `round(offset_ms * 30 / 1000)` recovers all 4,569 frame indices (max error 1 ms << 16.7 ms).
5. Epoch mode: `start_ms` is rounded from an ISO string with microseconds, so it can be
   `t0_ns // 1e6 + 1` (sub-ms 0.7 ms -> +1 ms); seconds-only ISO loses the fraction. If epoch mode
   is ever used, store the `start_ts_unix_user_ms` returned by the upload and use
   `offset_ms = ts - start_ts_unix_user_ms`; never recompute start from `t0_ns`.
6. Drift: if the real capture rate is 29.95 fps, frame 4500 is at 150.25 s measured vs 150.00 s
   CFR position: 250 ms = 7.5 frames. `t0_ns + offset` is wrong; the frame map lookup is right.
7. `avg_fps` 29.97 or 29.9999 -> step 29, `ts` = 0, 967/966, 1935/1933 …: not whole seconds,
   but the inverse with fps 30 still recovers the index. Fix at upload: require `30/1`.
8. MCP `trim._str_timestamp`: `"0000000004000"` ok; `ts_unix: 4000` (int) padded ok; but
   `ts_unix_13digits: 4000` (int, unpadded) is returned as `"4000"` -> `invalid_timestamp`.
   The search API sends strings, so no live impact today; `robot_retrieve` must zero-pad its
   own inputs. A 19-digit `t_ns` passed as `ts` is rejected (`invalid_timestamp`), not truncated: correct.

### C8. Tag rows (customer 2f schema, skill output)

`tag_id | episode_uid | t_start_ns | t_end_ns | tag | source=auto | tagger=vmodal-robot-similar |
tagger_version={skill_ver}+idx{index_version} | relevance | confidence=null | review_status=unreviewed |
supersedes=null | created_at`. Written to a new file, never appended to the customer
`tags/tags.parquet` directly: `{out}/tags_candidates_{query_id}.parquet` (+ `.jsonl`).


## Folder Tree

```
uinterface/mcp_python_robot/
  src/mcp_server/
    robot.py                  New: episode build, telemetry+frame map IO, hit resolve
    robot_format.py           New: format spec draft/validate/register, row + frame-align checks (C2, C2c)
    registry.py               edit: robot_* tool entries
    main_mcp.py               edit: handlers for SDK-helper style robot tools
    config.py                 edit: MCP_ROBOT_DIR default (derived from MCP_IMAGE_DIR parent)
  skills/
    vmodal-robot-similar/
      SKILL.md                New: "find all episodes like this failure"
      reference.md            New: failure catalog, telemetry signatures, worked example
      scripts/telemetry_scan.py   New: rule detectors over telemetry (no video needed)
      scripts/telemetry_sig.py    New: anchor signature + distance for re-rank
      scripts/tags_write.py       New: C8 rows -> parquet/jsonl
      tests/test_telemetry_scan.py
  tests/
    test_robot.py             New
    test_robot_format.py      New
  ztmptest/robot/             New: 2 tiny episodes (reuse assets/test_video_20_frames.mp4)
    xarm6_gripper_100hz.format.json   sample spec (C2)
  docs/
    robot_contract.md         New: C1..C8 for users
    tool_contract.md          edit: robot tools section
    vla_train/telemetry.jsonl, gen_telemetry.py   Exists: sample data + generator
```


## List of potential failures issues

1. **LeRobot v3 packs many episodes per mp4.** A per-episode clip must be cut by
   `from_timestamp/to_timestamp`. AV1 stream copy does not cut on a frame boundary -> frame 0
   shifts and invariant 2 breaks silently. Fix: re-encode the cut (H.264, CFR 30) and assert
   decoded frame count == episode `length`; else reject the episode.
2. **1 fps index vs few-frame events.** A drop/slip lasting 3-5 frames may have no indexed
   frame. Fix: telemetry scan (P4) produces candidates independently of the index; retrieve
   can decode the exact frame locally.
3. **Hit time precision.** Offset is ms and frames sit on whole seconds (only with fps exactly
   30/1, C9 check 7) or fewer after near-duplicate removal, so a hit is a ~1 s window, not a frame. Report the window (C6); exact frame only via telemetry/frame map.
4. **Filename sanitizer.** `episode_uid` with characters the backend rewrites -> two episodes
   map to one filename, or no reverse mapping. Reject at upload (invariant 1).
5. **No metadata filters in `/search`.** Filtering by robot/operator/task after the search
   with `limit=50` misses hits beyond the page. Fix (MCP): page until `n_total` or a page cap,
   report `n_scanned` / `n_total`. Fix (**Backend**): filter on `info_json` server side.
6. **Re-upload of a revision.** Same `episode_uid` in a new `dataset_rev` with a trimmed start
   -> old frame map no longer matches the clip. Fix: one collection per rev (C1) or key the
   manifest by (`dataset_rev`, `episode_uid`); refuse to overwrite a clip whose `n_frames`
   or `t0_ns` changed.
7. **Wrist not row-aligned** (MCAP source instead of LeRobot). Then wrist offset != scene
   offset. Build the wrist clip from the frame map (nearest wrist frame per scene row, repeats
   flagged) so C1 holds.
8. **Telemetry clock.** Sidecar `t_ns` must be on the same corrected clock as the frame map;
   check telemetry covers `[t_scene_ns[0], t_scene_ns[-1]]` and record gaps > 20 ms in the
   manifest instead of interpolating over them.
9. **Index version drift.** A re-index changes `version_lancedb`; old tags then reference an
   old index. Always carry `index_version` (invariant 4); never compare relevance across versions.
10. **Units confusion.** Raw gripper 0..850 vs normalized 0..1; joint current is an estimate.
    Units are mandatory in the spec (C2); `range` [0, 1] on `gripper` catches raw 0..850 data.
11. **Upload volume.** 1,000 episodes x 2 cams ~ 40 GB (H.264 larger than AV1). Bulk upload must
    be resumable per episode (manifest status per episode), not all-or-nothing.
12. **Spec edited in place after uploads.** Old episodes then fail or silently pass a different
    check. Fix: registered versions immutable; same `format_id` + `format_version` with a
    different sha256 -> 409 conflict, user must bump `format_version` (invariant 7).
13. **Spec draft registered unchecked.** Inferred units/ranges from a sample can be wrong
    (e.g. quaternion order, gripper polarity). Fix: draft writes `"?"` for anything not
    inferable; registration requires no `"?"` plus `checked_by`; MCP never fills them itself.
14. **Header and spec disagree** (e.g. sample header has no unit for `ee_quat`, spec says
    `quat_xyzw`). The spec wins only if the header does not contradict it; a missing value in
    the header is fine, a different value is a `file` error.
15. **Check passes on the spec, fails on frames.** A clean 100 Hz file can still start after the
    first video frame (recording started late) or be on an uncorrected clock (offset ~ constant).
    Fix: coverage + per-frame `dt` checks (C2c step 4); a constant `dt_ms_mean` near the
    tolerance is a warning to look at the clock offset (3a).
16. **Spec too strict for real data.** `max_frames_no_telemetry: 0` may reject many real
    episodes. Fix: run `robot_dataset_upload(dry_run=true)` first; it returns the per-episode
    verdict table so the user can tune the spec (new version) before uploading anything.


------------------------------------------------------------------------
## List of files to be changed:

- `src/mcp_server/robot.py` : New. Episode validation, clip cut, telemetry/frame-map normalize,
  manifest, hit resolve, telemetry window + summary.
- `src/mcp_server/robot_format.py` : New. Spec draft from sample, spec validation, registry
  (C5 formats), row checks (C2b), telemetry-vs-frames checks + frame index (C2c).
- `src/mcp_server/registry.py` : add `telemetry_format_draft_from_file`,
  `update_json_format_specs_from_file`, `telemetry_format_list`, `telemetry_format_check`,
  `robot_episode_upload`, `robot_dataset_upload`, `robot_find`, `robot_retrieve`,
  `robot_manifest_build`.
- `tests/test_robot_format.py` : New.
- `src/mcp_server/main_mcp.py` : handlers for the robot tools (same pattern as
  `image_download_from_records`, SDK-helper tools not mirrored from routes).
- `src/mcp_server/config.py` : `MCP_ROBOT_DIR` derived default.
- `tests/test_main_mcp.py` : test9 allowlist of non-route targets gets the robot tools.
- `tests/test_robot.py` : New.
- `skills/vmodal-robot-similar/*` : New skill + scripts + test.
- `skills/README.md` : add the skill.
- `docs/robot_contract.md`, `docs/tool_contract.md`, `prompts.md` : docs.


## Implementation step

### P0 — User telemetry format spec: draft, check, register (User spec 4)

User flow:
1. User gives one sample file (e.g. `telemetry.jsonl`) to `telemetry_format_draft_from_file`.
2. MCP returns a draft spec (C2) + writes it to a path the user chooses. Inferred: field names,
   dtypes, shapes, `names` and `unit` from a header line if present, rate from median `dt`.
   Not inferable -> `"?"` (units missing in header, ranges, `video_align` limits, `checked_by`).
3. User checks/edits the JSON (their responsibility; MCP never fills `"?"` values).
4. User calls `update_json_format_specs_from_file(path, collection_name=None, sample_path=None,
   dry_run=False)`. MCP:
   - validates the spec rules (C2), rejects any `"?"`, missing `checked_by`;
   - if `sample_path` given: runs the C2b row checks on it and returns the report (the user's
     last check before it becomes binding);
   - computes `format_sha256` on the canonical JSON (sorted keys);
   - new (`format_id`, `format_version`) -> stores `formats/{id}/v{n}.json`, updates `index.json`;
     same version + same sha -> no-op; same version + different sha -> 409, bump version;
   - if `collection_name` given: writes the binding in `{collection}/collection.json`;
   - returns `{format_id, format_version, format_sha256, status: created|unchanged,
     bound_collection, diff_vs_previous_version, sample_report}`.
   `dry_run=true` validates and returns the same output without writing.

Other tools:
- `telemetry_format_list(format_id=None)`: registered specs, versions, bindings.
- `telemetry_format_check(telemetry_path, format_id=None, collection_name=None,
  frame_map_path=None, video_paths=None)`: standalone C2c check for one episode, no upload.
  Without frame map / video, only checks 1-2 run.

- Files to edit/create: `robot_format.py`, `registry.py`, `main_mcp.py`, `config.py`.
- New tests to create: `tests/test_robot_format.py` test1..test6.
- How to test: draft from `docs/vla_train/telemetry.jsonl`, fill `"?"`, register into a
  `ztmp_sandbox` `MCP_ROBOT_DIR`, re-register (unchanged), edit + re-register (409).

#### Test Cases:
- test1: draft from `telemetry.jsonl` -> 7 fields with right shapes, `rate_hz` 100,
  `ee_quat.unit == "?"` (no unit in the sample header).
- test2: register with a `"?"` left -> 422 naming the JSON path (`fields[4].unit`).
- test3: register valid spec -> `created`; same file again -> `unchanged`; edited range with the
  same version -> 409; with `format_version` 2 -> `created` + diff lists the field.
- test4: bind to collection -> `collection.json` has `xarm6_gripper_100hz@1`.
- test5: `sample_path=telemetry.jsonl` -> sample report `pass`, 10 rows.
- test6: spec rules: duplicate field name, `names` length != shape, bad `sampling.mode` -> 422.


### P1 — Episode upload with telemetry JSON, checked against frames (User specs 1, 5)

New tools:

- `robot_episode_upload(collection_name, episode_uid, video_scene, video_wrist=None,
  telemetry_path, frame_map_path, meta_path, dataset_rev, format_id=None, fps=30, dry_run=False)`
- `robot_dataset_upload(collection_name, dataset_dir, dataset_rev, frame_map_path,
  telemetry_dir, meta_dir, format_id=None, episodes=None, limit=None, dry_run=False)`: LeRobot
  v3 reader; iterates the episode table, cuts clips (issue 1), calls the single-episode path.
  Resumable: skips episodes whose manifest status is `uploaded` with the same `n_frames`,
  `t0_ns` and `format_sha256`. Dry run returns a verdict table (episode | verdict | first error)
  and counts `n_pass / n_flag / n_reject` (issue 16).

`format_id` defaults to the collection binding (C5); no binding and no `format_id` -> 422
"register a telemetry format first (update_json_format_specs_from_file)".

Steps (single episode):
1. Validate `episode_uid` against the filename sanitizer (invariant 1).
2. Load the registered spec (bound version, or `format_id@version`).
3. Read frame map rows for the episode; `t0_ns = t_scene_ns[frame_index=0]`; `n_frames`.
4. Video: if source is a packed LeRobot file, cut + re-encode CFR; decode frame count per camera.
5. Run the C2c checks with the spec: file vs spec, time vs spec, video, telemetry vs frames.
   Write the report + frame index. `reject` -> stop, nothing uploaded for this episode.
6. Normalize telemetry to the canonical stored form (C2b), header from the spec.
7. Upload clips with `collection_video_upload` (stream = camera).
8. Upload telemetry + frame map JSONL.gz. Phase A: kept local in `MCP_ROBOT_DIR` and
   referenced by path in the manifest. Phase B (**Backend**): stored next to the video as a raw
   asset via the signed upload flow (`r2_presign_upload_file`), `telemetry_ref` = object key.
9. Upload the C4 metadata row (incl. format + check summary) with
   `collection_upload_metadata(mode=vid_file)`.
10. Write/update the C5 manifest line; optionally `index_create` after the bulk run.
    Run one index job per collection at a time: wait for `index_status` success before
    starting the next camera index. Overlapping jobs return HTTP 409.
Any failure in 7-9 marks the episode `partial` in the manifest; the next run re-uploads it
(invariant 8: video and telemetry together or not at all from the user's view).

Dry run: does 1-6 and returns the planned upload list + C2c report, no network.

- Files to edit/create: `robot.py`, `robot_format.py`, `registry.py`, `main_mcp.py`, `config.py`.
- Existing tests touched: `tests/test_main_mcp.py::test9` (registry targets), `::test3` (schemas).
- New tests to create: `tests/test_robot.py` test1..test5, `tests/test_robot_format.py` test7..test9.
- How to test: CLI `python -m src.mcp_server.main_mcp` tool call with `dry_run=True` on
  `ztmptest/robot/`, then one live episode upload to a dev collection.

#### Test Cases:
- test1: fake telemetry JSON + JSONL + parquet, same spec -> same canonical rows.
- test2: non-monotonic `t_ns`, wrong vector length, gripper 850 (range), NaN -> `file`/`time`
  errors with field name and row number.
- test3: `episode_uid` that the sanitizer changes -> rejected.
- test4: clip frame count != frame map length -> rejected (use the 20-frame asset with a
  21-row frame map).
- test5: dry run on 2 fixture episodes -> manifest lines with `t0_ns`, `n_frames`, sync fields,
  `format_id/version/sha256`, `check_verdict`.
- test_robot_format test7: telemetry starting 50 ms after frame 0 -> `coverage_ok=false`, reject.
- test_robot_format test8: 30 ms telemetry gap mid-episode -> gap listed, frame inside the gap
  counted in `n_frames_no_telemetry`; with `on_fail=flag` -> verdict `flag`.
- test_robot_format test9: `sampling.mode=frame` spec, missing `frame_index` 7 -> reject; no
  collection binding and no `format_id` -> 422 with the register hint.


### P2 — Retrieve frame + timestamp + telemetry JSON (User spec 2)

New tool: `robot_retrieve(records=None, episode_uid=None, t_ns=None, collection_name,
cameras=["cam_scene","cam_wrist"], window_before_ms=1000, window_after_ms=1000,
telemetry_fields=None, telemetry_rate_hz=None, image_source="auto", root_folder=None)`

Input is either robot/VModal search records (1..20, like `image_download_from_records`) or
explicit (`episode_uid`, `t_ns`) points.

Steps:
1. Resolve each input to (`episode_uid`, `frame_index`, `t_ns`) with invariant 2. Explicit
   `t_ns` -> nearest `t_scene_ns`, accepted within +/- 16.7 ms, else `errors=["no_frame"]`.
2. Images:
   - `vmodal_index`: copy the record per camera, keep `ts_unix_13digits` (row-aligned clips),
     call `image_download_from_records`. For an explicit `t_ns`, build `ts` with the C9
     frame -> ts formula (float, zero-padded to 13). Only indexed seconds; a miss is reported, not guessed.
   - `local_decode`: decode `frame_index` from the source clip if present locally (exact frame).
   - `auto`: index first, local decode on miss.
3. Telemetry window `[t_ns - before, t_ns + after)` from the stored C2b file, row lookup via
   the C2c frame index, fields by name from the episode's recorded spec version, optional
   downsample (take nearest row per step, no interpolation across gaps).
4. `state_at_t`: telemetry row nearest `t_ns` (+/- 10 ms) as named dict.
5. `telemetry_summary` (C7) computed on the window.
6. Return C7; write the `.json` sidecar next to each JPEG.

- Files to edit/create: `robot.py`, `registry.py`, `main_mcp.py`.
- New tests to create: `tests/test_robot.py` test6..test9.
- How to test: fake record pointing at a fixture episode; live: `robot_find` then `robot_retrieve`
  on the top 3 hits.

#### Test Cases:
- test6: offset 1000 ms at 30 fps -> `frame_index` 30 -> `t_ns` == frame map row 30 (not t0 + 1 s).
- test6b (C9): all frames 0..4568 at 30 fps: frame -> ts (backend float formula) -> frame
  round-trips; frame 969 -> `"0000000032299"` (not 32300); `t_ns` 1761130004001999999 -> ms
  1761130004001 (floor); int `ts` input zero-padded; 19-digit `ts` rejected.
- test7: explicit `t_ns` 20 ms from any frame -> `no_frame`.
- test8: window rows all inside bounds, names/units equal header, downsample keeps gaps.
- test9: summary values on a synthetic current spike on j2 (known max).


### P3 — Robot search with episode-level hits

New tool: `robot_find(collection_name, query_text=None, image_path=None, camera="cam_scene",
filters=None, limit=50, max_pages=10, dataset_rev=None)`

1. Call `find` (text and/or image, existing), page with `offset` up to `max_pages` or `n_total`.
2. Map `filename` -> `episode_uid`; drop hits not in the manifest (reported as `n_unmapped`).
3. Apply `filters` (`robot_id`, `operator_id`, `task`, `success`, `date_from/to`,
   `sync_offset_ms_max<=`) from the manifest. Report `n_scanned`, `n_total`, `n_kept`.
4. Convert to C6 rows; also return `episodes`: one row per episode, best relevance, hit count,
   merged windows (hits <= 3 s apart merged, as in vmodal-find scenes).

- New tests: `tests/test_robot.py` test10 (fake `find` pages -> C6 rows, filters, merge).
- **Backend** follow-up: push `filters` into `/search` on `info_json` keys (issue 5).


### P4 — Skill `vmodal-robot-similar` (User spec 3)

Trigger: "find episodes like this failure", "similar failures", "where else did the grasp
miss", "tag all drops like episode 412 at 4.0 s". Requires vmodal MCP robot tools + vmodal-find.

Inputs (any one is the anchor): (`episode_uid`, `t_ns` or time range); a frame image path;
a failure name from the catalog; or free text. Plus collection, optional filters.

Steps:
1. **Anchor.** `robot_retrieve` on the anchor: scene + wrist frames, telemetry window, summary.
   View the frames. Pick the catalog failure type (reference.md) and write a two-part
   signature: visual (2-4 things seen, e.g. "gripper closed, cup still on table") and
   telemetry (rule from the catalog, e.g. "gripper reaches > 0.95 within 0.5 s of close
   command" = grasp miss). Show both to the user before searching.
2. **Search wide, in parallel** (`robot_find`, limit 50, max_pages 10):
   image search with the anchor scene frame; image search with the wrist frame (stream
   `cam_wrist`; often more telling for grasps); the catalog text phrases for the type; one
   user-phrased text query.
3. **Telemetry scan** (`scripts/telemetry_scan.py`, local, over all stored C2b files of the
   collection): run the catalog detector for the type -> candidate windows with a detector
   `confidence`. Each detector declares the fields + units it needs (e.g. `gripper` in
   `0_open_1_closed`, `cmd_gripper` with `role=command`); the scan checks them against each
   episode's registered spec and skips (and reports) episodes whose spec lacks them. Episodes
   with `check_verdict=flag` are scanned but gaps from their C2c report are masked. This covers
   events between indexed frames (issue 2) and answers Casey Q4 for now (telemetry search runs
   client-side).
4. **Fuse.** Group all candidates per episode into windows (<= 3 s merge, <= 15 s max).
   Score = rank fusion of visual hits (reciprocal rank over the searches) + telemetry
   distance to the anchor signature (`scripts/telemetry_sig.py`: named fields only, each
   window resampled to fixed length, z-scored per field with stats from the scanned set).
   Keep visual relevance and detector confidence as separate columns; do not merge them into
   one "probability".
5. **Triage** in batches of 10 by inspecting returned `robot_retrieve` image paths directly:
   for each candidate show the scene frame at the window peak + wrist frame. PASS / PARTIAL /
   FAIL against the catalog visual rule. Stop after two batches without a new PASS, or 40
   candidates, and say which rule stopped it.
6. **Write candidate tags** (`scripts/tags_write.py`) for PASS and PARTIAL: C8 rows,
   `relevance` = fused score, `confidence` = detector confidence when the telemetry rule fired,
   else null. FAIL rows are not written. Nothing is marked accepted.
7. **Report** (markdown): anchor + signature, searches run, `n_scanned` / `n_total`
   episodes, table episode | window | verdict | relevance | detector, reviewed frame paths,
   tag file path, and the follow-up the reviewer must do (accept/reject in batches, then
   snapshot a `tag_rev` before Flow 2).

reference.md failure catalog (first version, each detector versioned, none is ground truth):

- `grasp_miss`: phrases "gripper closes on nothing", "empty gripper above table";
  telemetry: cmd_gripper 0 -> 1 and gripper reaches > 0.95 (no object stop); visual PASS:
  closed gripper with object not in it.
- `object_drop`: phrases "object falls from gripper", "cup dropped during transport";
  telemetry: gripper position rises (opens) > 0.1 while cmd_gripper stays 1, or object-in-hand
  stop followed by full close during transport (TCP speed > threshold); visual: object below
  gripper / on table away from target.
- `slip`: gripper creep toward closed > 0.05 in < 0.3 s while holding.
- `collision_contact`: |current| spike above per-joint threshold with TCP speed drop.
- `joint_limit`: q within margin of xArm limits.
- `hesitation_idle`: TCP speed < threshold for > 3 s mid-episode (operator hesitated).
- `occlusion_wrist`: visual only (wrist frame dark/blocked); phrase "camera view blocked by
  hand or object".
- `correction`: episode tagged correction (00_doc.md comments) -> excluded from anchors by default.

Thresholds are per robot in reference.md and recorded in `tagger_version`.

- Files to edit/create: `skills/vmodal-robot-similar/{SKILL.md, reference.md, scripts/*,
  tests/test_telemetry_scan.py}`, `skills/README.md`.
- How to test: fixture telemetry with planted events; live on the M2 ~100-episode test set:
  plant = pick 5 known drops, use one as anchor, measure how many of the other 4 come back.

#### Test Cases:
- `test_telemetry_scan.py` test1: planted `grasp_miss` and `object_drop` found at the right
  `t_ns` (+/- 50 ms); clean episode returns nothing.
- test2: detector reads fields by name; header with reordered fields gives the same result.
- test3: `tags_write.py` rows match C8 columns and values (`unreviewed`, `auto`, null confidence
  when no detector).
- test4: `telemetry_sig.py` distance anchor vs itself = 0, vs planted similar < vs clean.


### P5 — Flow 1 batch tagging + review queue (after P4)

- Same skill, mode "tag from text": `robot_find` -> windows -> C8 rows with `min_relevance`,
  no anchor needed (00_doc.md Flow 1).
- Review queue: sorted by relevance, scene/wrist frame paths per candidate, reviewer answers
  accept / reject / correct per candidate; the skill writes human rows with `supersedes=<tag_id>` (human decision,
  so `source=human`, `tagger=<reviewer>`).


### P6 — Backend follow-ups (not in this package)

1. Store telemetry + frame map as raw assets next to the video; signed GET for them (same
   pattern as `image_get_url`) so retrieve works from any machine.
2. Metadata filters in `/search` on `info_json` keys.
3. Optional: higher index sampling for robot collections (e.g. 5 fps) or index at event
   candidates from the telemetry scan.
4. Optional: telemetry embedding index (windowed) so `robot_find` can search telemetry
   pattern server-side.
5. Read path for a video's `info_json` (removes the need for the local manifest C5).


------------------------------------------------------------------------
## Answers draft for 00_doc.md open questions

1. Reader input: LeRobot v3 + frame map + 100 Hz sidecar works; MCAP fallback not needed for P1.
2. Score meaning: `score` ranks hits only, not calibrated (range: **Open**, to confirm with backend).
3. Granularity: indexed frames about 1 per second; hits returned as +/- 0.5 s windows in `t_ns` (C6).
4. Telemetry search: client-side detectors in the skill now (P4 step 3); server-side is P6.4.
5. Index versioning: yes, each search returns `version_lancedb`; record it as `index_version`.


------------------------------------------------------------------------
## Test Critical List:
   `uinterface/mcp_python_robot/tests/test_robot_format.py` : spec draft/register/versioning (P0), telemetry-vs-frames checks (C2c).
   `uinterface/mcp_python_robot/tests/test_robot.py` : upload validation, time resolve (invariant 2), retrieve window, robot_find mapping.
   `uinterface/mcp_python_robot/skills/vmodal-robot-similar/tests/test_telemetry_scan.py` : detectors, signature distance, tag rows.
   `uinterface/mcp_python_robot/tests/test_main_mcp.py` : registry targets + schemas incl. robot tools.


## Test for Data Contract List:
   `tests/test_robot_format.py::test1..test6` : C2 spec rules, `"?"` rejection, immutable versions, collection binding.
   `tests/test_robot_format.py::test7..test9` : C2c coverage, gaps, stale commands, frame mode, verdicts.
   `tests/test_robot.py::test1,test2` : C2b telemetry normalize + rejects against the spec.
   `tests/test_robot.py::test3,test4` : C1 filename == episode_uid, clip frame count == frame map.
   `tests/test_robot.py::test6,test7` : C6/C7 `t_ns` from frame map lookup only.
   `skills/vmodal-robot-similar/tests/test_telemetry_scan.py::test3` : C8 tag rows.


------------------------------------------------------------------------
## Implementation Order

0. P0 format spec: draft from `telemetry.jsonl`, user checks, `update_json_format_specs_from_file`,
   fixtures `ztmptest/robot/xarm6_gripper_100hz.format.json`.
1. P1 upload: `robot_dataset_upload(dry_run=true)` verdict table on the M2 set, tune spec
   (new version) if needed, then upload.
2. P2 retrieve (local telemetry + frame map), invariant 2 tests.
3. P3 `robot_find` with manifest filters.
4. P4 `vmodal-robot-similar` skill: telemetry scan + fusion + triage + candidate tags.
5. M2 run on ~100 episodes, report (search quality, recall on planted failures, gaps).
6. P5 review queue, then P6 backend items ranked by the M2 report.
