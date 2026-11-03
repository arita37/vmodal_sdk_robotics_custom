# Robot tool examples

Tool arguments are relative to the MCP process working directory. Start from the robot MCP
package root. Register the synthetic fixture only for the sample collection:

```json
{"tool":"update_json_format_specs_from_file","arguments":{"path":"data/robot/xarm6_gripper_100hz.format.json","collection_name":"robot_demo","sample_path":"data/robot/ep_demo1/telemetry.jsonl"}}
```

Validate a complete episode without network calls:

```json
{"tool":"robot_episode_upload","arguments":{"collection_name":"robot_demo","episode_uid":"ep_demo1","video_scene":"data/robot/ep_demo1/cam_scene.mp4","video_wrist":"data/robot/ep_demo1/cam_wrist.mp4","telemetry_path":"data/robot/ep_demo1/telemetry.jsonl","frame_map_path":"data/robot/ep_demo1/frame_map.json","meta_path":"data/robot/meta/ep_demo1.json","dataset_rev":"r1","dry_run":true}}
```

Or validate both episodes from packed LeRobot v3 video:

```json
{"tool":"robot_dataset_upload","arguments":{"collection_name":"robot_demo","dataset_dir":"data/robot/lerobot","dataset_rev":"r1","frame_map_path":"data/robot/frame_map.parquet","telemetry_dir":"data/robot/telemetry","meta_dir":"data/robot/meta","dry_run":true}}
```

Retrieve local exact frames and a telemetry window (no API key needed):

```json
{"tool":"robot_retrieve","arguments":{"collection_name":"robot_demo","episode_uid":"ep_demo1","t_ns":1761130005002869449,"image_source":"local_decode","window_before_ms":100,"window_after_ms":100}}
```

For real upload, supply `api_key` and use `dry_run=false`. On an indexed real collection,
call `robot_find(collection_name=...,query_text="empty gripper above table")`, then pass
its `data` objects to `robot_retrieve(records=...)` unchanged. Preserve the robot directory
between sessions; Phase A telemetry storage is local.

The failure helpers run from the same package root:

```bash
python skills/vmodal-robot-similar/scripts/telemetry_scan.py robot_demo grasp_miss ztmp/ztests/scan.json
```

Review actual camera views before producing candidate tags. Synthetic test-pattern videos
are not visual evidence that a grasp failed.
