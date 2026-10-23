# M1 – Current flow / data stack schema

Casey Clark 2026-10-22

**Labels used below.** **Current** = how my stack works today. **Proposed** = a change for the SDK integration, not built yet. **Open** = something to agree with you.

- **Robot:** UFactory xArm 6 (6-DoF) + UFactory xArm Gripper. Cameras: fixed scene cam (RealSense D415) + wrist cam (RealSense D405).
- **Models trained on this data:** π0.5 (openpi), LingBot-VLA 2.0.
- **Also used:** public sim pools in LeRobot v3 – LIBERO (8D state / 7D action, 10 Hz) and AXIS Franka (9D / 9D absolute, 30 Hz, no video in the current release).

## 0. Volume (Current, approximate)

| Item | Estimate | Basis |
| --- | --- | --- |
| Episodes | ~1,000 | avg ~2.5 min, longest ~5 min |
| Footage | ~150,000 s (~41.7 h) | 1,000 × 150 s |
| Frames | ~4.5M per camera | 150,000 s × 30 fps, before drops and trimming |
| Telemetry | ~15M samples per 100 Hz topic | 150,000 s × 100 Hz; 5 topics incl. command |
| Disk | ~40 GB LeRobot v3 (2 cams, AV1) · ~450 GB raw MCAP (JPEG images) | |

Exact totals are in `meta/info.json` (`total_episodes`, `total_frames`); I'll send them with the M2 test set.

## 1. Prep flow

| Step | Current | Proposed change |
| --- | --- | --- |
| 1. Record | Teleop episodes to MCAP (ROS 2). Each device keeps its own timestamps; hosts are chrony-synced. | – |
| 2. Convert + align | MCAP -> LeRobot v3.0. Scene-camera time is the reference; telemetry and actions are put on it (3a, 3b). | Also write a frame map (2d) and a 100 Hz telemetry sidecar (2e). |
| 3. Quality check | Drop or flag: frame drops, frozen joints, NaN/inf, joint-limit hits, video that won't decode, too short for one action chunk. | Sync report stored as indexed fields. |
| 4. Tag | Task, success/fail, events. Mostly by hand. This is the slow part. | SDK search + candidate tags, human review of the uncertain ones. |
| 5. Filter | Tag rules -> episode list -> new dataset revision. | Rules run on a frozen tag snapshot (2f). |
| 6. Split, normalize, export | Split by episode, recompute stats on the filtered subset, export per model. | Split first, then stats on the train split only, after model transforms (3d). |
| 7. Feed back | Eval failures tagged by failure mode, next filter round. | – |

Most of my time goes into 3 and 4. That's where your SDK fits.

## 2. Data on disk

### 2a. Raw MCAP (Current)

```
raw/{fleet_id}/{robot_id}/{date}/{episode_uid}.mcap
```

| Topic | Message type | Content | Units | Rate |
| --- | --- | --- | --- | --- |
| `/xarm/joint_states` | `sensor_msgs/JointState` | 6 joint positions | rad | 100 Hz |
| `/xarm/joint_current` | `sensor_msgs/JointState` (effort field) | 6 joint currents | A | 100 Hz |
| `/xarm/gripper_state` | `std_msgs/Float32` | gripper position, raw 0 (closed) .. 850 (open) | normalized on convert: `g = (850 − pos) / 850`, 0 open .. 1 closed | 100 Hz |
| `/xarm/ee_pose` | `geometry_msgs/PoseStamped` | TCP pose | m + quaternion | 100 Hz |
| `/teleop/joint_cmd` | `sensor_msgs/JointState` | commanded 6 joints + gripper (= action) | rad, 0..1 | 100 Hz nominal |
| `/cam_scene`, `/cam_wrist` | `sensor_msgs/CompressedImage` (JPEG) | 640×480 | – | 30 fps nominal, with jitter |

The xArm ROS 2 driver runs with `report_type=dev`; the default `normal` reports at only 5 Hz. Joint current is the controller's estimate, not a torque sensor.

### 2b. Episode metadata json (Current)

```
meta_raw/{episode_uid}.json
{ "episode_uid": "...", "fleet_id": "...", "robot_id": "...", "operator_id": "...",
  "start_time": "ISO-8601 UTC", "duration_s": 152.3, "task": "put the cup in the bin",
  "success": true, "mcap_file": "raw/.../xxx.mcap", "lerobot_episode_index": 412 }
```

`lerobot_episode_index` is valid for one dataset revision only; LeRobot renumbers episodes in every subset. Proposed: replace it with the per-revision frame map (2d). `episode_uid` is the stable ID everywhere.

### 2c. LeRobot v3.0 dataset (Current)

v3.0 packs many episodes into each file (up to ~100 MB parquet / ~500 MB mp4). An episode is found through the episode table, not by file name.

```
dataset/
  meta/info.json                               fps=30, features + names, shapes, dtypes, codec, path templates
  meta/stats.json                              min/max/mean/std/count + quantiles, whole dataset
  meta/tasks.parquet                           task_index -> task string
  meta/episodes/chunk-000/file-000.parquet     per episode: length, tasks, data/video file + offsets
  data/chunk-000/file-000.parquet              frame rows, many episodes per file
  videos/observation.images.cam_scene/chunk-000/file-000.mp4
  videos/observation.images.cam_wrist/chunk-000/file-000.mp4
```

| Column | Type | Content | Units |
| --- | --- | --- | --- |
| `index`, `episode_index`, `frame_index`, `task_index` | int64 | row ids (`episode_index` changes per revision) | – |
| `timestamp` | float32 | measured scene-cam frame time minus episode start (not `frame_index / fps`) | s |
| `observation.state` | float32[7] | `j1..j6`, `gripper` | rad; 0 open .. 1 closed |
| `observation.ee_pose` | float32[6] | `x, y, z`, `roll, pitch, yaw` | m; rad (extrinsic XYZ Euler) |
| `action` | float32[7] | `j1..j6` commanded, `gripper` | rad absolute; 0..1 |

Video: 640×480, 30 fps, AV1, constant frame rate on encode. Episode table: `episode_index`, `length`, `tasks`, `dataset_from_index`, `dataset_to_index`, `data/chunk_index`, `data/file_index`, and per camera `videos/{key}/chunk_index`, `file_index`, `from_timestamp`, `to_timestamp`. Joint current is not stored here (see 2e).

### 2d. Time base and frame map (Proposed)

Clock convention: every source time is int64 `t_ns`, nanoseconds since UTC epoch, in the recording host clock, after the per-device offset correction (3a). Tags and search hits use `t_ns`, never frame numbers.

```
revisions/{rev}/frame_map.parquet
episode_uid | episode_index | frame_index | t_scene_ns | t_wrist_ns | wrist_dt_ms | wrist_repeated
```

- **Time -> frame:** take the row with the nearest `t_scene_ns`; accept only if within ±16.7 ms (half a frame), else "no frame" (drop or gap).
- **Time range -> frames:** all rows with `t_start_ns <= t_scene_ns < t_end_ns`. A lookup, not arithmetic, so jitter, dropped frames and trimming are handled.
- **Frame -> video:** file from the episode table; position in the shared mp4 = `from_timestamp + frame_index / fps` (videos are encoded at constant fps).
- **Wrist camera:** nearest wrist frame to each scene frame, accepted within ±16.7 ms. The two cameras are not hardware-synced, so up to half a frame of offset between views is expected. Per-episode max and mean `wrist_dt_ms` go in the sync report.
- **Missing wrist frame (Current):** the previous wrist frame is repeated and the row is flagged (`wrist_repeated`). More than 3 missing in a row drops the episode.

### 2e. Telemetry sidecar (Proposed)

Joint current is not a LeRobot column, so current-spike searches need the raw MCAP topic or this sidecar at native rate:

```
telemetry/{episode_uid}.parquet   (100 Hz)
t_ns | q[6] (rad) | current[6] (A) | gripper (0..1) | ee_pos[3] (m) | ee_quat[4] | cmd_q[6] (rad) | cmd_gripper (0..1)
```

### 2f. Tags (Proposed – SDK output)

```
tags/tags.parquet
tag_id | episode_uid | t_start_ns | t_end_ns | tag | source (human/auto/model) | tagger | tagger_version
       | relevance | confidence | review_status | supersedes | created_at
```

- `relevance`: search score for the query. Ranks hits; not a probability that the event happened. Scale: Open.
- `confidence`: probability-like score that the event occurred, set by a detector (e.g. the gripper/current rules in section 5). Search-made tags have `confidence = null` until a detector or a reviewer sets it.
- `review_status`: `unreviewed` / `accepted` / `rejected` / `corrected`. A human row with `supersedes = <tag_id>` overrides that auto tag.
- `t_end_ns` is exclusive; both times null = whole episode.
- Outcome from 2b is also written as a human tag (`success` / `fail`).
- Filtering runs on a frozen copy, `tags/snapshots/{tag_rev}.parquet`. Each dataset revision records the `tag_rev` and tagger versions it used.

## 3. Pipeline / feature engineering

### 3a. Sync (Current)

- Hosts are chrony-synced. Per device, the clock offset is estimated per episode as the median of (receive time − header stamp) and subtracted before alignment.
- Scene-camera time = reference. 1 dataset row = 1 `cam_scene` frame.
- State: joints linearly interpolated to frame time, gripper hold-last. Frame rejected if no telemetry within ±16.7 ms.
- Sync report per episode: max/mean offset ms, dropped frames (gap > 1.5 frames), duplicates, frames per camera vs rows. Flag if offset > 33 ms.

### 3b. Action alignment (Current)

At 100 Hz commands and 30 fps frames there are ~3.3 commands per frame interval, so the rule is explicit:

- `action[t]` = latest command with stamp `<= t_scene_ns` (zero-order hold: the command in effect when the image was taken). `cmd_age_ms` is kept in the sync report.
- Missing data: no command within 20 ms (2 periods) -> `action_valid = false`; chunks containing invalid rows are not used as training samples. A gap over 200 ms splits the episode; pieces shorter than one action chunk are dropped.
- Command-to-state latency is measured per episode (cross-correlation of command vs joint position) and reported. No shift is applied to the data; the number is there to catch episodes where it drifts.

### 3c. Cleaning (Current)

- Drop: frame drops, frozen joints (state flat while action moves), NaN/inf, joints out of limits, empty task, truncated episodes.
- Trim idle frames at start/end. With the frame map (Proposed), trimming removes rows and tags keep their `t_ns`.

### 3d. Split and normalization

- Split by original `episode_uid` before computing any statistics. Clips cut from the same episode always stay in the same split.
- Trainer stats are fitted on the train split only, after model-specific transforms (e.g. arm deltas). `meta/stats.json` is descriptive only; it covers the whole dataset and absolute values.
- Saved with each export: dataset rev, `tag_rev`, split lists, seed, norm-stats file. Norm stats ship with the checkpoint.

### 3e. Model export (Current)

| | openpi π0.5 | LingBot-VLA 2.0 |
| --- | --- | --- |
| Dataset format read | LeRobot **v2.1** (openpi pins an older lerobot). Each export writes a v2.1 copy of the revision (per-episode parquet + mp4) with a small in-house script | LeRobot v3.0, read directly |
| Mapping | openpi data config (inputs/outputs transforms) | robot config yaml mapping my keys into its unified state/action vector |
| Actions | `DeltaActions`, mask `make_bool_mask(6, -1)`: arm delta, gripper absolute | `subtract_state: True` for arm, `False` for gripper |
| Norm stats | quantile (q01/q99) via `compute_norm_stats.py`, on the train split | `compute_norm_stats.py` pointed at the train split |
| Images | `ResizeImages(224, 224)` with padding; scene + wrist into the model's image slots | 224×224 with padding; scene + wrist |
| Horizon | `action_horizon = 10` (0.33 s at 30 fps) | 10 |

One dataset revision feeds both models; only the export differs.

## 4. Pain points / where time goes

| Pain point | Cost when missed | What would help |
| --- | --- | --- |
| Finding past events in video, tagging by hand ("grasp failed", "object dropped", "occlusion", "operator hesitated") | Curation can't keep up with collection | Text/image search over video + candidate tags; review only the uncertain ones |
| Camera vs telemetry out of sync | Actions and images disagree in time | Per-episode offset as an indexed field I can filter on |
| Failed episodes mixed into training | Model imitates failed grasps | Outcome tag + rule-based exclusion |
| Same vector length, different meaning (xArm 7D absolute on disk / delta after export, LIBERO 7D at 10 Hz, AXIS 9D absolute without video) | Policy trains fine, then moves the wrong joints | Reader takes names and joint order from `info.json`, never by index |
| Norm stats from the wrong data or the wrong file | Checkpoint scores collapse | Stats tied to a revision, a split and a transform |
| Finding similar episodes, near-duplicates | Unbalanced dataset, wasted GPU time | Similarity search with metadata filters |

## 5. Interface (no change to my stack)

```
[My data: MCAP / LeRobot v3 / meta json / frame map] --> your reader adapter --> your index
[Your Python SDK] --> called from my prep scripts
```

**Reader inputs (my side)**

| Input | Where | Notes |
| --- | --- | --- |
| Episode ID | `episode_uid` | stable; `episode_index` only within one revision |
| Video | LeRobot mp4 + episode table offsets, or MCAP image topics | 640×480, 30 fps, AV1 (LeRobot) / JPEG (MCAP) |
| Frame times | `frame_map.parquet` (Proposed) | `t_ns` per frame, both cameras |
| Telemetry, 30 fps | LeRobot `observation.state`, `observation.ee_pose`, `action` | names, shapes, units: 2c |
| Telemetry, 100 Hz incl. current | MCAP topics or sidecar (2e) | units: 2a / 2e |
| Metadata | meta json (2b) | fleet, robot, operator, task, success |
| Schema | `meta/info.json` | names, shapes, dtypes |

**Outputs I need from the SDK** (format Open)

- Search hit: `query_id, episode_uid, t_start_ns, t_end_ns, relevance, modality, index_version, dataset_rev`. Frame range derived from the frame map.
- Tag: the 2f schema, `review_status = unreviewed` on write.

**Flow 1 – candidate tags** (pseudocode; your actual API Open)

```python
hits = sdk.search(text="gripper drops object", filters={"robot_id": "..."}, dataset_rev="r12")
# each hit: episode_uid, t_start_ns, t_end_ns, relevance, index_version
sdk.tag(hits, tag="drop", source="auto", min_relevance=0.6)
# -> tags/tags.parquet: review_status = unreviewed, confidence = null
```

Reviewers then accept, reject or correct these in batches, sorted by relevance.

**Flow 2 – filter by rules** (my side, DuckDB, on a frozen tag snapshot)

```sql
WITH t AS (
  SELECT * FROM 'tags/snapshots/tagrev_0007.parquet'
  WHERE review_status <> 'rejected'
    AND tag_id NOT IN (SELECT supersedes FROM 'tags/snapshots/tagrev_0007.parquet'
                       WHERE supersedes IS NOT NULL)
)
SELECT episode_uid FROM t WHERE tag = 'success'
EXCEPT
SELECT episode_uid FROM t
WHERE tag IN ('drop', 'occlusion')
  AND (source = 'human'
       OR review_status IN ('accepted', 'corrected')
       OR confidence >= 0.8)
```
A tag excludes an episode only if a human wrote it, a reviewer accepted it, or a detector is confident. Unreviewed search hits alone never remove data.

-> episode list -> new revision + frame map -> split -> stats on train split -> export -> train

**Search types I'd use**

- text -> video segments ("gripper closes on nothing")
- image -> similar frames/segments
- telemetry -> pattern (current spike, joint near limit, arm idle > 3 s, velocity spike during transport)
- combined, with metadata filters (fleet, robot, operator, task, date)

**Candidate events worth detecting** (each versioned and recomputable; none is ground truth)

- Grasp candidate: gripper command 0 -> 1. Position stopping short of fully closed suggests an object in hand; closing fully suggests a miss. Heuristic only, needs review.
- Phases: approach / grasp / transport / place / release, from gripper events + TCP speed.
- Motion: idle segments, velocity/accel spikes, joint-limit proximity, current spikes (per-joint thresholds; current is an estimate).
- Video quality: frame drops, blur, exposure, wrist-cam occlusion.

## 6. Open questions for you

Each one has my working assumption, so a short "yes" or a correction is enough. None of them blocks this milestone; they shape M2.

1. **Reader input.** Since your reader adapts to my data on disk, I'd point it at LeRobot v3 + the frame map + the 100 Hz sidecar, and keep MCAP as a fallback for raw frames. Does that work, or is MCAP easier for you to start from?
2. **Score meaning.** I've assumed `relevance` only ranks hits and there is no calibrated confidence yet (2f). What does your score mean, and what is its range?
3. **Hit granularity.** I've assumed free time ranges (`t_start_ns`, `t_end_ns`). If your index works on fixed segments, what length?
4. **Telemetry search.** Can the SDK query telemetry patterns directly (e.g. a current spike on joint 2), or does telemetry come in only through tags for now?
5. **Index versioning.** When the SDK or the embedding model changes, does the index get a version ID I can record with each dataset revision?

## 7. Next

**M2:** run your SDK on a ~100-episode test set from my data. Index it, run Flow 1 and Flow 2, build one curated revision, and write a short report: what worked, what broke, search quality, tag accuracy, gaps ranked by impact. Proposed: $300, about 1 week after SDK access.

**Then:** iteration rounds as you update the SDK, each one a small milestone with a re-test report.
