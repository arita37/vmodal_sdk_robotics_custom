# VModal Robot MCP

Upload robot episodes with user-specified telemetry, retrieve exact mapped timestamps and
frames, search episodes, and export similar-failure candidates for human review. Existing
VModal collection, image, and search tools remain available through the Python SDK.

Use Python 3.10+ in your existing environment, with `ffmpeg` and `ffprobe` on PATH. From this
directory:

```bash
bash install.sh install
export api_key=PUT_API_KEY_HERE
vmodal-mcp-robot run --transport stdio
```

Alternatively register from the checkout with `bash install_mcp.sh codex YOUR_API_KEY`
(also supports claude, cursor, copilot). The robot distribution is `vmodal_mcp_robot`;
its executable is `vmodal-mcp-robot`. The copied generic MCP bootstrap URLs are not used.
Both MCP variants use the historical `src` Python namespace, so install only the intended
variant into an existing interpreter. MCP configuration uses the registered interpreter.

The public `vmodal` 1.0.0 SDK is supported: robot uploads use a temporary, same-content
episode-named upload alias when the SDK lacks `video_filename`. Newer APIs receive
`video_filename` and `reduce_size=False`. No unpublished minimum SDK version is required.

Start by drafting telemetry with `telemetry_format_draft_from_file`, review all `?` values,
then register with `update_json_format_specs_from_file`. Bind a collection and run
`robot_episode_upload(dry_run=true)` before network upload. Local format/check/dry-run tools
work without credentials. Network operations require `api_key`.

See [robot contracts and examples](docs/robot_contract.md), [all tool contracts](docs/tool_contract.md),
[configuration](docs/env_vars.md), and [similar-failure skill](skills/vmodal-robot-similar/SKILL.md).
Telemetry and frame maps remain in the configured local robot directory in Phase A.

## Use case: inspect a robot episode and compare a successful grasp

Use the committed [data/robot](data/robot/README.md) samples to validate a two-camera
handoff and inspect telemetry around a suspected failure. Each episode has 60 frames
at encoded 30 fps and 100 Hz telemetry. Both episodes have a 9.0 A j2 current spike
at 500 ms. `ep_demo1` also has planted grasp-miss and gripper-opening events and
`success=false`; `ep_demo2` provides a steady-grasp comparison with `success=true`.
The gripper telemetry, not the shared current spike, distinguishes the episodes.
The task metadata is `put the cup in the bin`.
The videos are synthetic test patterns: use them to check frame alignment and retrieval,
not to establish visual evidence of a failed grasp.

Start the MCP server with `uinterface/mcp_python_robot` as its working directory, or
replace the paths below with absolute paths on the MCP server. These JSON objects show
MCP tool names and arguments; submit them through your connected assistant/client.

### 1. Register the sample telemetry format and check alignment

The supplied format is reviewed synthetic-fixture data, suitable for this demo collection.
Registration binds it locally to `robot_demo`; it does not upload data or create a remote
collection. These steps need no API key.

```json
{
  "tool": "update_json_format_specs_from_file",
  "arguments": {
    "path": "data/robot/xarm6_gripper_100hz.format.json",
    "collection_name": "robot_demo",
    "sample_path": "data/robot/ep_demo1/telemetry.jsonl"
  }
}
```

```json
{
  "tool": "telemetry_format_check",
  "arguments": {
    "collection_name": "robot_demo",
    "telemetry_path": "data/robot/ep_demo1/telemetry.jsonl",
    "frame_map_path": "data/robot/ep_demo1/frame_map.json",
    "video_paths": {
      "cam_scene": "data/robot/ep_demo1/cam_scene.mp4",
      "cam_wrist": "data/robot/ep_demo1/cam_wrist.mp4"
    }
  }
}
```

Expect `verdict=pass`, including frame-count, telemetry-coverage and command-age checks.
For your own data, first use `telemetry_format_draft_from_file`, resolve every `?` with
the data owner, and register the reviewed spec. Do not reuse synthetic reviewer provenance.

### 2. Validate both episodes from the packed LeRobot dataset

```json
{
  "tool": "robot_dataset_upload",
  "arguments": {
    "collection_name": "robot_demo",
    "dataset_dir": "data/robot/lerobot",
    "dataset_rev": "r1",
    "frame_map_path": "data/robot/frame_map.parquet",
    "telemetry_dir": "data/robot/telemetry",
    "meta_dir": "data/robot/meta",
    "dry_run": true
  }
}
```

Expect two `validated` episodes, `n_pass=2`, `n_flag=0`, and `n_reject=0`. This cuts the
packed clips at the episode-table boundaries and writes local artifacts and a manifest
without network calls. To validate just one episode from its separate camera files,
use the `robot_episode_upload` call in [robot_examples.md](docs/robot_examples.md).

### 3. Retrieve both camera frames and named telemetry locally

```json
{
  "tool": "robot_retrieve",
  "arguments": {
    "collection_name": "robot_demo",
    "episode_uid": "ep_demo1",
    "t_ns": 1761130004502034725,
    "image_source": "local_decode",
    "window_before_ms": 100,
    "window_after_ms": 100,
    "telemetry_fields": ["current", "gripper", "cmd_gripper"]
  }
}
```

This timestamp is frame 15's exact `t_scene_ns` from the supplied map, near the planted
500 ms current spike. Expect scene/wrist JPEG paths, `frame_index=15`, named `state_at_t`
(including `current.j2`), telemetry rows and a summary. Nanosecond timestamps must remain
integers. Capture times use 29.95 fps while encoded clips use 30 fps, so always resolve
through the frame map. Preserve the configured `MCP_ROBOT_DIR` and local clips for later
retrieval; Phase A telemetry and maps remain local.

### 4. Upload, index and search through the connected assistant

For a network demo, configure `api_key` and repeat the dataset upload with
`dry_run=false`, using one collection per dataset revision. Require `uploaded` status
before searching. Index jobs must run serially within a collection: call `index_create`
for `cam_scene`, poll its returned job with `index_status` until it succeeds, then create
and wait for the `cam_wrist` index. Do not start the second job while the first is
running: the API returns HTTP 409. If a job fails, inspect its error before continuing. See the
[configuration guide](docs/env_vars.md) and [live validation example](docs/live_api_validation.md).

Paste these prompts in order after the local walkthrough. The search query describes
the actual test-pattern footage; semantic failure searches need real robot videos.

```text
Upload the same data/robot/lerobot dataset to robot_demo, revision r1, with
robot_dataset_upload and dry_run=false. Use data/robot/frame_map.parquet,
data/robot/telemetry and data/robot/meta. Report each episode's upload status.
Create the cam_scene image-embedding index and poll index_status until it succeeds.
Only then create the cam_wrist index and wait for success. Run only one index job
at a time in robot_demo; report any failure before proceeding to search.

List my collections, then show the sub-collections of robot_demo in a table.
Use collection_list and collection_subcollections_list.

Use robot_find in robot_demo, dataset_rev r1, to find "colorful test pattern"
in cam_scene. Filter robot_id=xarm_demo and success=false. Use limit=10 and
max_pages=2. Show episode IDs, mapped times, index version, n_scanned, n_total,
n_unmapped and page_cap_reached.

Use robot_retrieve with up to 5 unchanged data objects from that robot_find
response, image_source=auto, both cameras, and 100 ms before/after each hit.
Show the images, telemetry summary, dataset/index versions and per-camera sources.

Use the returned cam_scene image path as image_path in robot_find to find similar
frames in robot_demo, dataset_rev r1. Then search cam_wrist with the same text
query. Keep results from different index versions separate.
```

Additional local prompts cover format discovery, single-episode handoff and recovery:

```text
Draft a telemetry format from data/robot/ep_demo1/telemetry.jsonl using
telemetry_format_draft_from_file, without writing a file. Show inferred fields,
shapes and rate, and list all unresolved ? values for review. Do not register it.

Use telemetry_format_list to show xarm6_gripper_100hz versions and collection
bindings. Confirm robot_demo is bound to xarm6_gripper_100hz@1.

Dry-run robot_episode_upload for ep_demo2 in robot_demo, revision r1. Use
data/robot/ep_demo2/cam_scene.mp4, cam_wrist.mp4, telemetry.jsonl and frame_map.json,
and data/robot/meta/ep_demo2.json. Show the check verdict and planned uploads.

Retrieve ep_demo2 locally at the t_scene_ns of frame 15 in its frame_map.json.
Compare its gripper and cmd_gripper values with ep_demo1 frame 15, using both
camera views and 100 ms telemetry windows. Distinguish telemetry from visual evidence.

Rebuild robot_demo's local manifest with robot_manifest_build from its preserved
episode artifacts. Report n_episodes and manifest_path; preserve recorded statuses.
```

For similar-failure triage on real footage, follow the
[similar-failure skill](skills/vmodal-robot-similar/SKILL.md). Review both camera views
before exporting candidate tags; candidates remain unreviewed until explicit human review.

## Verification

Run all offline tests:

```bash
bash test.sh test
```

The runner executes the offline suites included in this checkout, including telemetry
scanning and checkout-reference checks. Authenticated validation is available explicitly
with `bash test.sh live`, `live_mcp`, `initial`, and `robot_live`; these commands require
configured credentials and may create remote test collections.

This checkout does not include a GitHub Actions release workflow. Run the commands above
locally; the [live validation record](docs/live_api_validation.md) describes earlier runs,
not a workflow available to dispatch from this checkout.
