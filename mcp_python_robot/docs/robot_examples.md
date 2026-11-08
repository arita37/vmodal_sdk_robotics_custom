# Robot tool examples

**The bundled episodes are synthetic negative test fixtures, not real robot demos.**
Their videos are color-bar/test patterns, every `q` and `cmd_q` joint stays at 0.1 rad,
and their `success` labels are authored test metadata. Format/alignment checks and
failure-screen flags do not prove task success, physical realism, or training usefulness.
See [sample limitations and diagnostics](../data/robot/README.md).

Tool arguments are relative to the MCP process working directory. Start from the robot MCP
package root. Register the synthetic fixture only for the sample collection, without
`sample_path` (the planted current spike would fail registration-time sample validation):

```json
{"tool":"update_json_format_specs_from_file","arguments":{"path":"data/robot/xarm6_gripper_100hz.format.json","collection_name":"robot_demo"}}
```

Validate a complete episode without network calls:

```json
{"tool":"robot_episode_upload","arguments":{"collection_name":"robot_demo","episode_uid":"ep_demo1","video_scene":"data/robot/ep_demo1/cam_scene.mp4","video_wrist":"data/robot/ep_demo1/cam_wrist.mp4","telemetry_path":"data/robot/ep_demo1/telemetry.jsonl","frame_map_path":"data/robot/ep_demo1/frame_map.json","meta_path":"data/robot/meta/ep_demo1.json","dataset_rev":"r1","dry_run":true}}
```

With the current bundled format, expect `status=rejected`, a current range error at
row 50, and warnings for the current spike and metadata/telemetry start-time mismatch.
No upload is planned. This is the intended negative-test result, not a real task verdict.

Or validate both episodes from packed LeRobot v3 video:

```json
{"tool":"robot_dataset_upload","arguments":{"collection_name":"robot_demo","dataset_dir":"data/robot/lerobot","dataset_rev":"r1","frame_map_path":"data/robot/frame_map.parquet","telemetry_dir":"data/robot/telemetry","meta_dir":"data/robot/meta","dry_run":true}}
```

Expect `n_pass=0`, `n_flag=0`, `n_reject=2`. Rejected episodes do not create validated
manifest entries. Older immutable registered formats may give different verdicts;
inspect the bound spec and warnings rather than treating a pass as approval.

The retrieval example below requires an existing validated manifest entry from a
separately prepared fixture. On a fresh store after the negative dry runs above,
expect `episode_not_available`, not image paths. Do not weaken limits just to bypass
the planted failures. Local retrieval itself needs no API key:

```json
{"tool":"robot_retrieve","arguments":{"collection_name":"robot_demo","episode_uid":"ep_demo1","t_ns":1761130005002869449,"image_source":"local_decode","window_before_ms":100,"window_after_ms":100}}
```

For real upload, first dry-run representative real inputs against owner-reviewed
limits and resolve any defects. Supply `api_key` and use `dry_run=false` only after
validation; the unchanged bundled fixtures are rejected in upload mode too.
On an indexed real collection,
call `robot_find(collection_name=...,query_text="empty gripper above table")`, then pass
its `data` objects to `robot_retrieve(records=...)` unchanged. Preserve the robot directory
between sessions; Phase A telemetry storage is local.

The failure helpers run from the same package root:

```bash
python skills/vmodal-robot-similar/scripts/telemetry_scan.py robot_demo grasp_miss ztmp/ztests/scan.json
```

Review actual camera views before producing candidate tags. Synthetic test-pattern videos
are not visual evidence that a grasp failed.
