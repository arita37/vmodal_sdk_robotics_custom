# Testing report: `mcp_python_robot` (vmodal-robot MCP)

**Tester:** Magdalena Mišić
**Date:** 2026-11-06 / 2026-11-07
**Scope:** installation, connection to Claude Code, authenticated listing, and the local tools (format review, upload dry run, failure screen, telemetry repair) on the bundled sample episodes `ep_demo1` and `ep_demo2`.
**Not tested:** real uploads, indexing, search, MCAP files, LeRobot dataset dry run, video re-check with `vmodal-robot-qc-batch`.

## 1. Summary

The installation and connection are smooth: one command, no errors, and the first telemetry prompt returned a clear result in about 14 seconds. The local tools give consistent numbers with each other.

The main problems are around the edges of the tools:

- **Undocumented dependencies**: the review, failure-screen and repair scripts need `numpy` (and `fire`, `filelock`, `pillow` in the scratch environment) that the installer does not provide.
- **The checks miss real defects in the sample data**: the upload dry run passes with 0 warnings even though the sample has a 9.0 A current spike and a `start_time` that is a year off from the telemetry.
- **The failure screen finds only part of the planted failure** in `ep_demo1`, and raises a false positive on `ep_demo2`.
- **The stock repair fixture crashes** on the bundled demo episodes (it expects at least 520 rows; they have 201).
- **`collection_list`** returns very large output with no filtering or pagination.

Details, evidence and suggested fixes are below.

## 2. Environment

| Item | Value |
|---|---|
| OS | Ubuntu 24.04 (Lenovo ThinkBook 16 G6 ABP) |
| Python | 3.12.3 |
| Git | 2.43.0 |
| FFmpeg / ffprobe | 6.1.1 |
| Assistant | Claude Code 2.1.318 (Claude Pro) |
| Branch used | `docs/robot-mcp-beginner-readme` |
| Clone size | about 304 MiB (1236 objects, 2328 files) |

## 3. What was tested

| # | Step | Result |
|---|---|---|
| 1 | One-line install (`install_full.sh`) | Passed, local smoke test passed |
| 2 | Re-run of `install_full.sh` (retry) | Passed, idempotent |
| 3 | Connect to Claude Code | Passed, server listed as Connected |
| 4 | Telemetry draft prompt from the installer | Passed |
| 5 | Registration with `install_mcp.sh claude` and API key | Passed after correcting a key entry mistake on my side |
| 6 | `collection_list` | Passed (443 collections), see issues 4 and 5 |
| 7 | Format review skill on `ep_demo1` | 0 errors, 2 warnings, see issues 2, 3 |
| 8 | `robot_episode_upload(dry_run=true)` on `ep_demo1` | 0 errors, 0 warnings, see issue 6 |
| 9 | Failure screen skill on `ep_demo1` (with `ep_demo2` as peer) | 1 flag, see issue 7 |
| 10 | Telemetry repair fixture | Passed only after adapting the fixture, see issue 8 |

## 4. Walkthrough with results

### 4.1 Installation and connection

The one-line command from README step 1 cloned the branch and ran the installer. The installer created `.venv-robot`, installed the package, passed the local telemetry smoke test and printed a ready MCP configuration. Re-running `bash install_full.sh` is safe: it reuses the environment and does not delete anything.

![Install output](images/01_install.png)

The server was connected with:

```bash
claude mcp add-json vmodal-robot '{"command":".../.venv-robot/bin/python","args":["-m","src.mcp_server.main_mcp","run","--transport","stdio"]}'
claude mcp list
```

![claude mcp list](images/02_mcp_list.png)

### 4.2 Telemetry draft (first test)

Prompt: `telemetry_format_draft_from_file` on `ep_demo1/telemetry.jsonl`, no output, no upload.

The tool returned: JSONL, time field `t_ns` (int64, nanoseconds, must increase), 100 Hz, seven required float fields (`q`, `current`, `cmd_q` with 6 joints, `gripper`, `cmd_gripper`, `ee_pos` with 3, `ee_quat` with 4 in xyzw), and a list of unresolved `?` values (ranges, tolerances, video alignment settings). Clear and useful.

![Telemetry draft](images/03_draft.png)

### 4.3 Authentication and `collection_list`

Before the key was set correctly, the server returned a clear message:
`AuthError (401): Only Clerk API keys are supported. Provide Authorization: Bearer <ak_...>.` This message is good and made the cause easy to find.

With a valid key, `collection_list` returned 443 collections (440 video, 3 image). 366 of them are auto-named test collections; 57 have no index version.

![collection_list](images/04_collection_list.png)

### 4.4 Format review skill (`ep_demo1`)

The skill was run twice on `ep_demo1`. Both runs found no errors. The script first reported 2 warnings (the `cmd_*` fields were not marked as commands; the remaining `?` values were open). The screenshot below is from the second run.

Measured values (same in both runs): 201 rows at 100 Hz (2.0 s), every sample gap exactly 10.0 ms, 60 scene frames at 29.95 fps, nearest telemetry sample to a frame at most 4.94 ms away (median about 2.5 ms), oldest command 9.95 ms, 0 frames without telemetry, 0 frames with a stale command. Gripper polarity matches its label (state follows the command by about 50 ms, correlation 0.96).

In the second run 13 of the 18 `?` values were filled from the data (format_id, time base, sampling tolerance and gap, ranges of `current`, `gripper`, `cmd_gripper`, `ee_pos`, `ee_quat`, and the four video alignment values). Five still need a person: `q.range` and `cmd_q.range` (every value in this sample is exactly 0.1, so the measured range would be [0.1, 0.1] and any real motion would fail), `video_align.on_fail` (a policy choice) and the sign-off fields `checked_by` and `checked_at`. The skill also states that the sample is a synthetic 2-second fixture, so ranges taken from it would reject normal real data.

The first run additionally pointed out two data problems: a single current spike (j2 reads 9.0 A at row 50, all other samples 0.3 A) and a `start_time` in the meta file that is one year off from the telemetry (2026 against 2025). The second run mentioned neither (see issue 12).

![Format review, part 1](images/05a_format_review.png)

![Format review, part 2](images/05b_format_review.png)

### 4.5 Upload dry run (`ep_demo1`)

`robot_episode_upload(dry_run=true)` with `robot_demo`, `dataset_rev=r1`: 0 errors, 0 warnings. Validated format, 201 rows with 0 bad rows, 100 Hz timing with no gaps, both cameras (60 frames, steady 30 fps), frame-to-telemetry alignment, command freshness. Nothing was uploaded; the dry run made no network calls and wrote local check files under `ztmp/mcp_robot/...` (this folder shows up as untracked in `git status`, see issue 13). The assistant also noted that the format used for the pass is a synthetic test fixture (`checked_by=synthetic_fixture`), so the pass shows that the pipeline works, not that a production format is approved, and that `success: false` in the meta file does not affect the verdict.

![Dry run](images/06_dry_run.png)

### 4.6 Failure screen (`ep_demo1`, `ep_demo2` as peer)

The screen flagged one item on `ep_demo1`: `not_released [medium]` (gripper still commanded closed in the last 0.5 s), with the suggestion `check` because it disagrees with `meta.success = False`.

The telemetry shows the planted failure more clearly than the screen does: the gripper closes almost fully at 150 ms (state 0.99, which suggests nothing between the fingers, a missed grasp), then opens to 0.70 at 800 ms while still commanded closed (a drop). The screen caught neither. The contact sheet of the scene camera cannot confirm it, because the videos are synthetic colour-bar test patterns.

![Failure screen](images/07_failure_screen.png)

### 4.7 Telemetry repair fixture

After adapting the fixture (see issue 8), the result was as designed:

| Episode | Before | After | Changes | Unrepaired |
|---|---|---|---|---|
| `ep_demo1_corrupt` | reject (27 errors) | pass (0 errors) | 61 | 0 |
| `ep_demo2_broken` | reject (20 errors) | reject (20 errors) | 0 | 2 |

Repairs in `ep_demo1_corrupt`: out-of-order rows re-sorted, 5 duplicate timestamps dropped, 3 rows of missing `q` interpolated, 20 quaternions renormalized, 10 sign flips corrected, 4 `cmd_gripper` values clamped to 1, and one gap of about 70 ms filled with 6 inserted rows. The inserted rows look like real data and should be mentioned if the episode is used for training. In `ep_demo2_broken` the script correctly refused to repair: a run of 20 non-finite gripper values (limit 5) and a 310 ms gap (limit 150 ms).

![Repair result](images/08_repair.png)

## 5. Issues

| # | Severity | Where | Issue | Suggested fix |
|---|---|---|---|---|
| 1 | Medium | README step 2 and `install_mcp.sh` | README example names the server `vmodal-robot`, while `install_mcp.sh` registers `vmodal`. Following both steps leaves two servers pointing at the same program. | Use one name in both places, or make `install_mcp.sh` detect an existing entry. |
| 2 | High | Review, failure-screen and repair scripts | `numpy` is not installed by `install_full.sh`, and is not mentioned in the README. Neither `.venv-robot` nor the system Python has it. The repair run also needed `fire`, `filelock` and `pillow` in its scratch environment. The skills call `.venv/bin/python`, while the installer creates only `.venv-robot` (checked with `ls -d .venv*` in `mcp_python_robot`: only `.venv-robot` exists), so the command in the skill does not work after a fresh install. The assistant confirmed this in the second repair run ("The skill's .venv/bin/python doesn't exist"), and also that the repair script imports the project validator, which needs `vmodal` and `fire`, while `numpy` is missing from `.venv-robot`. | Add the dependencies to the package or an optional extra, and fix the interpreter path in the skills. |
| 3 | Medium | Format review script | For an episode where no joint moves, the suggested range for `q`/`cmd_q` was `[0.1, 0.1]`, which would reject any episode with real motion. A ±0.1 margin was also added to the gripper range. | Use the format header or the physical unit limits when the data has no variation. |
| 4 | Medium | `collection_list` | Output is too large to read directly (443 collections), with no filter or pagination. The assistant had to count them with shell commands. | Add filters (prefix, type, has index) and pagination. |
| 5 | Medium | `collection_list` | Some collections show a newest version higher than the number of listed versions (for example, one lists 2 versions with newest v12, another 14 with newest v15). The key also lists many collections whose names suggest unrelated projects. | Check version counting, and confirm that a user key should see only its own collections. (Names are left out of this report on purpose.) |
| 6 | High | Upload dry run | The dry run passes with 0 warnings even though `ep_demo1` has a single current spike (j2 reads 9.0 A at row 50, others 0.3 A) and the meta `start_time` (2026-10-22) is one year off from the telemetry (2025-10-22). The registered v1 format has no range for `current`, and the meta file is accepted as is. | Add a default range for `current`, and validate `start_time` against the first telemetry timestamp. |
| 7 | Medium | Failure screen | Only one weak flag on `ep_demo1`. The missed grasp is not caught because `closed_further_than_peers` needs more than two episodes. Nothing detects a gripper opening while it is commanded closed. `ep_demo2` (a steady successful grasp that starts already holding) gets a false `gripper_did_not_close [high]`. Also, the repo episode folders have no `meta.json`, which the script expects, so scratch copies were needed. | Add a rule for "opens while commanded closed", require the open state before the close command for `gripper_did_not_close`, and ship `meta.json` in the demo folders. |
| 8 | Medium | Repair fixture `make_corrupt.py` | Crashed with `IndexError` on the bundled demos in the first run, because it expects at least 520 telemetry rows and they have 201 (the summary of the second run does not mention it). A comment says the planted gap is about 400 ms, but it is 310 ms. | Pick defect positions as fractions of the episode length, and fix the comment. |
| 9 | Low | Dry run and review | The dry run reports using an "already registered" `xarm6_gripper_100hz` v1, while the format review says nothing was registered. It is not clear where v1 comes from. | Document where bundled formats are registered. |
| 10 | Low | README | MCAP is mentioned in the task description but is not covered in the README. The README also does not show a step-by-step way to set `api_key` (for example `read -s`), which is easy to get wrong. | Add an MCAP note (or say it is unsupported) and an `api_key` example. |
| 11 | Low | Sample data | The sample videos are synthetic colour-bar test patterns, so frames cannot confirm a grasp. `ep_demo1` is a fixture (`success: false`, joints stay at 0.1 rad). Tools check format and alignment but cannot judge whether an episode is useful. | State this clearly in the docs, or include one real short episode. |
| 12 | Medium | Format review skill | Results differ between runs on the same episode. In the first run the review pointed out the 9.0 A current spike and the one-year `start_time` mismatch. In the second run it set `current.range` to [-0.79, 9.89] ("observed 0.1-9, plus 10%"), which silently includes the spike, and mentioned neither problem. The number of values left open also differed (3 in the first run, 5 in the second). | Make the script itself flag outliers and meta/telemetry mismatches, so the result does not depend on how the assistant summarises it. |
| 13 | Low | Dry run | Dry-run artifacts are written inside the repository checkout (`ztmp/mcp_robot/...`), and this folder appears as untracked in `git status`. | Add `ztmp/` to `.gitignore`. |

## 6. Suggestions

1. Make the setup self-contained: dependencies included, one registered server name, one interpreter path.
2. Make the dry run stricter: default range for `current`, check `start_time` against telemetry, optional warning for "no motion in the episode".
3. Improve `collection_list`: filtering, pagination, and a check of what a user key may list.
4. Extend the failure screen with the two rules in issue 7 and a short test with three or more episodes.
5. Make test fixtures independent of episode length.

## 7. Not tested

- Real upload, indexing and search (only `collection_list` was called against the server).
- MCAP files, LeRobot dataset dry run, `update_json_format_specs_from_file` registration.
- Re-checking repaired episodes with `vmodal-robot-qc-batch` (including video alignment).
- Windows (the installer targets macOS and Linux).

## 8. Appendix: commands used

```bash
git clone --branch docs/robot-mcp-beginner-readme --single-branch \
  https://github.com/arita37/vmodal_sdk_robotics_custom.git vmodal-robot
bash vmodal-robot/mcp_python_robot/install_full.sh
claude mcp add-json vmodal-robot '{...}'
claude mcp list
PYTHON_BIN="$PWD/.venv-robot/bin/python" bash install_mcp.sh claude   # with api_key set
```

Prompts given to the assistant:

- `Use telemetry_format_draft_from_file to inspect .../ep_demo1/telemetry.jsonl. Do not write a file, register a format, or upload anything.`
- `Using the vmodal MCP, call collection_list and show me the result. Do not upload, create or delete anything.`
- `Use the vmodal-robot-format-review skill on the bundled sample episode ep_demo1 ... Do not register a format and do not upload anything.`
- `Run robot_episode_upload with dry_run=true on ep_demo1. Do not upload anything.`
- `Run the vmodal-robot-failure-screen skill on ep_demo1. Do not register or upload anything.`
- `Use the vmodal-robot-telemetry-repair skill. Run its test fixture ... Do not register or upload anything.`
