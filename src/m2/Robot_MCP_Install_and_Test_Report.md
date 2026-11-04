# Robot MCP Install and Test Report

Nov 4, 2026

## Summary

The robot MCP server (`vmodal_mcp_robot` 0.2.0) is installed and registered in Claude Code. Every prompt in its README ran successfully against the VModal test API on 4 Nov 2026.

The two sample robot episodes are now uploaded to a new `robot_demo` collection, with search indexes for both cameras. Text search, image search and frame retrieval all returned results.

One code change was needed: the public `vmodal` SDK (1.0.0) is older than the code expects, so live uploads failed until a small compatibility fix was added to `robot.py`. Four other issues were found and are listed below.

## Setup

The package was installed with the repo's own `bash install.sh install`, inside a virtual environment so the system Python stayed untouched.

| Item | Detail |
| --- | --- |
| Package | `vmodal_mcp_robot` 0.2.0, editable install |
| Python | 3.14.4, virtual environment at `mcp_python_robot/.venv` |
| Main dependencies | `vmodal` 1.0.0, `mcp` 1.30.0, `pyarrow` 26.0.1, `pydantic` 2.14.2 |
| Video tools | `ffmpeg` and `ffprobe` from the system |
| API endpoint | `searchapi-test.v-modal.com` |
| Claude Code | MCP server `vmodal`, user scope, status Connected |
| Local storage | `mcp_python_robot/ztmp/mcp_robot` (episodes) and `ztmp/mcp_images` (frames), set as absolute paths |

Offline tests: 8 of 9 suites pass (`test_utils`, `test_main_mcp`, `test_cli`, `test_robot_format`, `test_robot`, `test_robot_similar`, `test_robot_mcp`, `test_telemetry_scan`). The ninth, `skills/vmodal-trend-radar/tests/test_trend_matrix.py`, is not in this checkout.

## README local walkthrough

All four local steps matched the results the README predicts. None of them needed the network.

| README step | Tool | Result |
| --- | --- | --- |
| 1. Register format | `update_json_format_specs_from_file` | `xarm6_gripper_100hz@1` created and bound to `robot_demo`; sample telemetry passed (201 rows, 100 Hz, no gaps) |
| 1. Check alignment | `telemetry_format_check` | Verdict pass; 60 of 60 frames decoded per camera at 30 fps; every frame has telemetry; oldest command 9.9 ms |
| 2. Dataset dry run | `robot_dataset_upload` | 2 episodes validated; `n_pass=2`, `n_flag=0`, `n_reject=0` |
| 3. Local retrieve | `robot_retrieve` | `frame_index=15` at `t_ns` 1761130004502034725; scene and wrist JPEGs; gripper 0.99, command 1.0; j2 current peaks at 9.0 A |

## README network prompts

Both episodes uploaded, both cameras indexed, and every search and retrieval returned results on index version 1.

| Prompt | Tool | Result |
| --- | --- | --- |
| Upload | `robot_dataset_upload`, `dry_run=false` | `ep_demo1` and `ep_demo2` uploaded, verdict pass |
| Index scene camera | `index_create`, `index_status` | `cam_scene` job finished with success |
| Index wrist camera | `index_create`, `index_status` | `cam_wrist` job finished with success, once the scene job was done |
| List collections | `collection_list` | `robot_demo` listed, mode `vid_file`, index versions v0 and v1 |
| List sub-collections | `collection_subcollections_list` | `cam_scene` and `cam_wrist` |
| Text search | `robot_find` "colorful test pattern", `cam_scene`, `robot_id=xarm_demo`, `success=false` | 1 hit: `ep_demo1` frame 0, relevance 0.684; `n_scanned=2`, `n_total=2`, `n_unmapped=0`, `page_cap_reached=false` |
| Retrieve hit | `robot_retrieve`, `image_source=auto`, both cameras | Both images served from the VModal index; index v1, `dataset_rev` r1; no errors |
| Image search | `robot_find` with the retrieved scene frame | 2 hits: `ep_demo1` (0.035) and `ep_demo2` (0.037) |
| Wrist text search | `robot_find` "colorful test pattern", `cam_wrist` | 2 hits: `ep_demo1` (0.684) and `ep_demo2` (0.694) |

The indexer kept one frame per 2-second sample clip, so every hit is frame 0. The `success=false` filter correctly dropped `ep_demo2` from the first search.

## Additional local prompts

The README's last five prompts all completed, and the manifest kept both episodes as uploaded.

| Prompt | Tool | Result |
| --- | --- | --- |
| Draft a format | `telemetry_format_draft_from_file` | 7 fields inferred (`q`, `current`, `gripper`, `ee_pos`, `ee_quat`, `cmd_q`, `cmd_gripper`) at 100 Hz; 18 values left as `?` for review; no file written |
| List formats | `telemetry_format_list` | `xarm6_gripper_100hz` v1; `robot_demo` bound to `xarm6_gripper_100hz@1` |
| Single-episode dry run | `robot_episode_upload` for `ep_demo2` | Validated, verdict pass; both cameras planned as `ep_demo2.mp4` |
| Frame 15 comparison | `robot_retrieve` on both episodes | See the table below |
| Rebuild manifest | `robot_manifest_build` | 2 episodes; both still `uploaded` |

At frame 15 the gripper telemetry separates the two episodes (0 = open, 1 = closed):

| Episode | Gripper | Command | Reading |
| --- | --- | --- | --- |
| `ep_demo1` | 0.99 | 1.0 | Closed fully on nothing: grasp miss |
| `ep_demo2` | 0.5 | 1.0 | Stopped by an object: grasp held |

This is telemetry evidence only. The sample videos are synthetic test patterns and show neither grasp.

## Issues found

Five issues came up. Only the first one blocked the run, and it was fixed in code.

| # | Issue | Effect | Action taken |
| --- | --- | --- | --- |
| 1 | `robot.py` passes `video_filename` and `reduce_size` to the SDK's `video_upload`; `vmodal` 1.0.0, the newest on PyPI, accepts neither | Live uploads failed before any network call | Added a `video_upload` helper in `src/mcp_server/robot.py`: it passes both arguments when the SDK supports them, otherwise it uploads a hard link named `{episode_uid}.mp4`. SDK 1.0.0 never resizes, so the remote result is the same. Robot and MCP tests still pass |
| 2 | `install.sh` runs `claude mcp add --scope … --env api_key=… vmodal -- …`; in Claude Code 2.1 the `--env` option swallows the server name | `bash install_mcp.sh claude KEY` fails | Ran the same command with the server name first; `install.sh` left unchanged |
| 3 | A second `index_create` on the same collection while a job is running returns 409 | Indexing both cameras at once fails | Ran the two index jobs one after the other |
| 4 | `skills/vmodal-trend-radar`, `skills/vmodal-incident` and the CI workflow named in the README are not in this checkout | `bash test.sh test` exits with an error on its last step; the contact-sheet step of the similar-failure skill cannot run | None |
| 5 | README says only `ep_demo1` has the j2 current spike; `data/generate.py` line 26 puts the 9.0 A spike at 500 ms in both episodes | Current comparisons between the two episodes show the same spike | None |

## What changed

One source file was edited; everything else added is environment, data or configuration.

| Where | Change |
| --- | --- |
| `mcp_python_robot/.venv` | New virtual environment with the package and its dependencies |
| `mcp_python_robot/ztmp` | Test output, the local episode store and downloaded frames |
| `mcp_python_robot/src/mcp_server/robot.py` | The `video_upload` compatibility helper (issue 1) |
| `~/.claude.json` | MCP server entry `vmodal`, including the API key in plain text |
| VModal account linked to the API key | New collection `robot_demo` (`vid_file`) with sub-collections `cam_scene` and `cam_wrist` |
| Same collection | 4 clips (2 episodes × 2 cameras), one metadata row per clip, index versions v0 and v1 |

The `robot_demo` collection can be removed with the `collection_delete` tool if it is not needed.

## Next steps

The SDK mismatch is the one item that affects anyone installing this package from scratch.

- [ ] Publish the newer `vmodal` SDK to PyPI, or raise the `pyproject.toml` requirement to the version that has `video_filename`
- [ ] Put the server name before `--env` in the `claude mcp add` commands in `install.sh`
- [ ] Add the missing `vmodal-trend-radar` and `vmodal-incident` skills to the source distribution, or remove their references
- [ ] Note in the README that index jobs for one collection must run one at a time
- [ ] Fix the sample data or the README so they agree on which episode has the current spike
- [ ] Rotate the API key, since it was shared in chat and is stored in plain text
- [ ] Decide whether to keep or delete the robot\_demo collection
