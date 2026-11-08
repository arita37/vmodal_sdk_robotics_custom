# VModal Robot MCP

Connect an MCP-compatible assistant to robot videos and telemetry. You can inspect local
episodes, retrieve aligned camera frames, and upload/search episodes with VModal.

Start with the local test below: **no API key or network upload is needed**.

## Install

### 1. Run the one-line installer

On **macOS/Linux (Bash)**, install Git, **Python 3.10+**, and **FFmpeg** first.
FFmpeg must provide both `ffmpeg` and `ffprobe` on PATH. For example, use
`brew install ffmpeg` on macOS or `sudo apt-get install ffmpeg python3-venv`
on Debian/Ubuntu. The installer never uses sudo or modifies system packages.
Windows users should use WSL; native Windows is not supported by this installer.

From a directory where you want to keep the project, copy this single line:

```bash
git clone --branch main --single-branch https://github.com/arita37/vmodal_sdk_robotics_custom.git vmodal-robot && bash vmodal-robot/mcp_python_robot/install_full.sh
```

This targets the maintained `main` branch. Keep the checkout in place: the
package is installed in editable mode. Git authentication is required if your account
needs it to access the repository.

**Already cloned it?** From an up-to-date `main` checkout's `mcp_python_robot` directory:

```bash
bash install_full.sh
```

This is also the retry command. It reuses `.venv-robot` and safely regenerates its
credential-free configuration. It does not pull Git changes, delete an existing folder,
overwrite assistant settings, or upload data. If `vmodal-robot` already exists, the
clone command stops without touching it; use the existing-checkout command instead.

The installer checks Python and FFmpeg, creates a dedicated `.venv-robot`, installs the
package and dependencies, checks dependency consistency, tests the bundled telemetry
locally, and prints a ready-to-use **absolute-path MCP configuration and test prompt**.
No environment activation or API key is needed. The package is `vmodal_mcp_robot`;
the executable is `.venv-robot/bin/vmodal-mcp-robot`.

### Local skill dependencies

The installer includes NumPy for the local review, failure-screen, repair, sync-audit
and normalization skills. Fire, filelock, Pillow and the VModal SDK are also installed
as package dependencies, including the repair validator's imports. No separate scratch
Python environment or manual dependency installation is needed.

Run skill commands from `mcp_python_robot` with `.venv-robot/bin/python`, the same
interpreter used by the MCP server. For example:

```bash
.venv-robot/bin/python skills/vmodal-robot-telemetry-repair/scripts/telemetry_repair.py --help
```

`install_full.sh` checks the review, failure-screen and repair entry points without
processing or uploading episodes. Rerun it to update an existing installation.

### 2. Connect your assistant

Installation prepares the server; your assistant still needs to enable it.
Import or merge the generated `.venv-robot/mcp-config.json` into your client's MCP
settings. Do not replace an existing configuration wholesale. The JSON uses this shape,
with the actual checkout path already filled in by the installer:

```json
{
  "mcpServers": {
    "vmodal-robot": {
      "command": "/absolute/path/to/vmodal-robot/mcp_python_robot/.venv-robot/bin/python",
      "args": ["-m", "src.mcp_server.main_mcp", "run", "--transport", "stdio"]
    }
  }
}
```

Configuration location/format varies by client (for example, Codex uses TOML rather
than this JSON). Transfer the same `command` and `args` when your client has its own
format. Enable/reconnect the server and confirm its tools include
`telemetry_format_draft_from_file`. The client launches the stdio server; you do not
need to run a separate server terminal. The installer does not automatically register
clients or change existing credentials.

For **authenticated upload and search**, from `mcp_python_robot`, you can use the
existing registration helper with the dedicated interpreter. In a trusted **Bash**
terminal, paste this block, enter your key at the hidden prompt, and press Enter.
Replace `codex` with `claude`, `cursor`, or `copilot` as appropriate; the matching
client CLI must be installed.

```bash
(
  set +x  # Do not trace commands containing the key.
  IFS= read -r -s -p 'VModal api_key (hidden): ' api_key || exit 1
  printf '\n'
  if [ -z "$api_key" ]; then
    printf 'No key entered; registration cancelled.\n' >&2
    exit 1
  fi
  export api_key
  PYTHON_BIN="$PWD/.venv-robot/bin/python" bash install_mcp.sh codex
)
```

The prompt keeps the key out of terminal echo and shell command history. The
subshell discards the key variable it read when registration finishes or fails;
it does not remove a key already saved in client configuration. Do not type a
literal key into a command or run the helper with shell tracing (`bash -x`).

All registration helpers use the same `vmodal-robot` name as the generated config.
If your client refuses to add an existing entry, edit that entry to add `api_key`
rather than registering a second name. Keep the same client scope as the original
entry. Older helpers registered `vmodal`; inspect its command and interpreter before
manually removing a duplicate, since it may be an unrelated generic VModal server.
The helpers do not remove existing servers.

Registration stores the key in client configuration, not an encrypted secret vault.
The existing helpers pass it through subprocess environments and client command-line
arguments, which local process inspection may expose. Cursor opens an install link
containing the key in a base64-encoded (not encrypted) configuration; treat that URL
and browser history as secrets. Use a trusted machine, protect client configuration
and backups, and never paste keys into chat, commit them, or share that link.
Reconnect the client after registration. See [configuration](docs/env_vars.md) before
enabling network operations.

### If installation fails

- **Python missing/too old:** install Python 3.10+; select it with
  `PYTHON_BIN=/absolute/path/to/python3 bash install_full.sh`.
- **FFmpeg/ffprobe missing or broken:** install/repair FFmpeg, then rerun.
- **venv/ensurepip missing:** install your operating system's Python venv package.
  If `.venv-robot` is incomplete, inspect it and move it aside manually; the installer
  never deletes it. A symlink or non-venv at that location is refused.
- **pip missing:** run `.venv-robot/bin/python -m ensurepip --upgrade` and retry.
- **Download, SDK compatibility, or pip failure:** read the original error immediately
  above the stage summary. Check network/proxy/package-index access, disk space, and
  permissions. Fix the cause and rerun; success is reported only after validation.
- **Smoke-test/import failure:** do not connect the client yet. Use the error to repair
  dependencies, and keep this dedicated environment separate from the generic MCP,
  which also uses the Python `src` namespace.
- **Client cannot start the server:** use the generated absolute Python path, keep the
  checkout where it was installed, and reconnect. If you move it, recreate the venv
  and import the regenerated configuration.

## One test Prompt

Paste this into your connected assistant. Use the exact prompt printed by the installer, or replace the sample path below
with your checkout’s absolute path:

```text
Use telemetry_format_draft_from_file to inspect this local sample:
 /absolute/path/to/vmodal-robot/mcp_python_robot/data/robot/ep_demo1/telemetry.jsonl

Do not write a file, register a format, or upload anything.
Show the inferred telemetry fields, their shapes and sampling rate.
List all unresolved ? values that a person must review.
```

**Expected result:** a draft telemetry format and a list of unresolved values, not an
authentication request. This checks that your assistant can call the robot MCP and read
the bundled sample. It does not test upload, indexing, search, or robot control.

If the tool is missing, reconnect the MCP server and check its startup logs. If the sample
cannot be found, verify the absolute path is on the machine running the MCP server.
If an import fails, confirm the MCP configuration uses the same Python interpreter you
installed into.

## Details

### Supported inputs and MCAP

**MCAP is not directly supported.** This checkout has no MCAP reader or bundled
MCAP converter; do not pass a `.mcap` recording to telemetry or upload tools.
Telemetry inputs support JSON arrays, `{header,rows}` JSON, JSONL, gzip JSONL
(`.jsonl.gz`), and Parquet. Episode uploads use separate camera videos, telemetry,
frame maps and metadata; dataset uploads read the documented LeRobot v3 layout.

For MCAP recordings, use an external converter appropriate to your message schemas
to extract telemetry into a supported format and create the camera clips, frame map
and episode metadata. Preserve integer nanosecond capture timestamps, units, field
shapes and camera alignment; renaming the file is not conversion. The clips must
meet the decoded 30 fps and frame-map requirements in the
[robot episode contract](docs/robot_contract.md). Review/register the converted
telemetry format, then run a local dry run before any upload. Successful format and
alignment checks do not verify that an external converter preserved every source
message correctly.

### What to do next

1. Review a draft's `?` values with the data owner.
2. Register the reviewed format with `update_json_format_specs_from_file` and bind a collection.
3. Run `robot_episode_upload(dry_run=true)` or the dataset dry run below before uploading.
4. Configure `api_key` only when you are ready for network upload and search.

Local draft/check/dry-run tools work without credentials. Dry runs can write local
artifacts; they do not upload data. Network operations require `api_key`.
Telemetry and frame maps remain in the configured local robot directory in Phase A.

A checkout can already contain a locally registered demo v1 under `ztmp/mcp_robot`;
the installer and format review do not register it. Before the walkthrough, see
[registry provenance and a fresh isolated demo](docs/env_vars.md#local-format-registry-why-a-demo-format-may-already-exist),
especially if registration reports an immutable-version conflict. Preserve existing state.

The public `vmodal` 1.0.0 SDK is supported: robot uploads use a temporary, same-content
episode-named upload alias when the SDK lacks `video_filename`. Newer APIs receive
`video_filename` and `reduce_size=False`. No unpublished minimum SDK version is required.
Both MCP variants use the historical `src` Python namespace, so install only the intended
variant into an interpreter. The copied generic MCP bootstrap URLs are not used.

See [robot contracts and examples](docs/robot_contract.md), [all tool contracts](docs/tool_contract.md),
[configuration](docs/env_vars.md), and [similar-failure skill](skills/vmodal-robot-similar/SKILL.md).

### Walkthrough: inspect synthetic robot fixtures

Use the committed [data/robot](data/robot/README.md) samples to exercise two-camera
checks and inspect deliberately planted telemetry defects. **These are synthetic test
fixtures, not recordings of a robot task or evidence of training-data quality.**
Each episode has 60 frames
at encoded 30 fps and 100 Hz telemetry. Both episodes have a 9.0 A j2 current spike
at 500 ms. `ep_demo1` also has planted grasp-miss and gripper-opening events and
`success=false`; `ep_demo2` simulates a steady grasp with `success=true`.
Both `q` and `cmd_q` stay at 0.1 rad for every joint in both episodes. These success
labels are authored fixture metadata, not independently verified task outcomes.
The gripper telemetry, not the shared current spike, distinguishes the episodes.
The task metadata is `put the cup in the bin`.
The videos are synthetic test patterns: use them to check frame alignment and retrieval,
not to establish visual evidence of a grasp, drop, or task completion. A format/alignment
pass or a failure-screen flag cannot establish whether an episode is useful for training,
physically realistic, or safe. Review real footage, task outcomes, representative motion,
and owner-approved limits before making those judgments.

Start the MCP server with `mcp_python_robot` as its working directory, or
replace the paths below with absolute paths on the MCP server. These JSON objects show
MCP tool names and arguments; submit them through your connected assistant/client.

#### 1. Register the sample telemetry format and check alignment

The supplied format has fixture-only sign-off (`checked_by=synthetic_fixture`),
not production approval. Its current bound is [-1, 1] A for this negative test.
Registration binds it locally to `robot_demo`; it does not upload data or create a remote
collection. These steps need no API key.

```json
{
  "tool": "update_json_format_specs_from_file",
  "arguments": {
    "path": "data/robot/xarm6_gripper_100hz.format.json",
    "collection_name": "robot_demo"
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

Register without `sample_path`: this intentionally defective sample would fail the
registration-time sample check. Check it separately as above. With the current bundled
format, expect `verdict=reject` and `row 50 current: outside range`, plus a current-spike
warning. Inspect the frame-count, telemetry-coverage and command-age results separately.
A passing alignment check does not cancel a telemetry range failure.
For your own data, first use `telemetry_format_draft_from_file`, resolve every `?` with
the data owner, and register the reviewed spec. Do not reuse synthetic reviewer provenance.

#### 2. Validate both episodes from the packed LeRobot dataset

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

With the current bundled format, expect two `rejected` episodes, `n_pass=0`,
`n_flag=0`, and `n_reject=2`. Both contain the planted 9 A spike. This cuts the packed
clips at the episode-table boundaries and writes local check reports without network
calls. The reports also warn about the deliberately incorrect metadata start time.
Rejected episodes are not added to the manifest; no uploads are planned.
To validate just one episode from its separate camera files,
use the `robot_episode_upload` call in [robot_examples.md](docs/robot_examples.md).

#### 3. Retrieve both camera frames and named telemetry locally (conditional)

**Stop here for the unmodified negative fixtures.** On a fresh local store the rejected
episodes above have no manifest entry, so this call returns `episode_not_available`.
The example below describes retrieval only if `ep_demo1` already has a validated
manifest entry from a separately prepared fixture. Keep any corrected test copies and
their provenance separate; do not relax limits merely to hide a defect or overwrite the
committed negative samples. A pre-existing entry is not proof that this run validated it.

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

#### 4. Upload, index and search through the connected assistant (conditional)

The unmodified bundled episodes are rejected with `dry_run=false` too; an API key
does not bypass validation. Do not run the prompts below after the expected rejection.
They apply only after separately prepared inputs have passed a dry run and the paths,
collection and revision have been updated accordingly. For a network demo, configure
`api_key` and use one collection per dataset revision. Require `uploaded` status
before searching. Index jobs must run serially within a collection: call `index_create`
for `cam_scene`, poll its returned job with `index_status` until it succeeds, then create
and wait for the `cam_wrist` index. Do not start the second job while the first is
running: the API returns HTTP 409. If a job fails, inspect its error before continuing. See the
[configuration guide](docs/env_vars.md) and [live validation example](docs/live_api_validation.md).

For a validated synthetic copy only, adapt these prompts in order. The search query describes
the actual test-pattern footage; semantic failure searches need real robot videos.

```text
Upload the separately prepared dataset that passed its dry run, using its reviewed
paths, collection and revision with robot_dataset_upload and dry_run=false.
Do not upload the unmodified data/robot negative fixtures. Report each episode's
upload status; stop if any episode is rejected. Substitute the chosen collection
and revision for robot_demo/r1 in the following prompts.
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

Only if ep_demo2 has a validated manifest entry, retrieve it locally at the
t_scene_ns of frame 15 in its frame_map.json. Otherwise report episode_not_available.
Compare its gripper and cmd_gripper values with ep_demo1 frame 15, using both
camera views and 100 ms telemetry windows. Distinguish telemetry from visual evidence.

Rebuild robot_demo's local manifest with robot_manifest_build from its preserved
episode artifacts. Report n_episodes and manifest_path; preserve recorded statuses.
```

For similar-failure triage on real footage, follow the
[similar-failure skill](skills/vmodal-robot-similar/SKILL.md). Review both camera views
before exporting candidate tags; candidates remain unreviewed until explicit human review.

### Verification

Run all offline tests:

```bash
PATH="$PWD/.venv-robot/bin:$PATH" bash test.sh test
```

The runner executes the offline suites included in this checkout, including telemetry
scanning and checkout-reference checks. Authenticated validation is available explicitly
with `bash test.sh live`, `live_mcp`, `initial`, and `robot_live`; these commands require
configured credentials and may create remote test collections.

This checkout does not include a GitHub Actions release workflow. Run the commands above
locally; the [live validation record](docs/live_api_validation.md) describes earlier runs,
not a workflow available to dispatch from this checkout.

