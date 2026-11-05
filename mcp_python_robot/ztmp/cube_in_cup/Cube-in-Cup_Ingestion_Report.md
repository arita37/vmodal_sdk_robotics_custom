# Cube-in-Cup Robot Dataset: Ingestion Report

Nov 4, 2026 · @Cody John Young

## Summary

All 24 demonstrations in the cube-in-cup dataset converted cleanly and passed validation with zero errors. A live upload of one episode through the vmodal SDK succeeded end to end.

- **Converted:** 24 of 24 takes, 6,220 synchronized frames (3.5 minutes at 30 fps), two cameras each.
- **Validated:** 24 of 24 passed the telemetry, timing and video-alignment checks (dry run, no data sent).
- **Live test:** one episode (take_19, 204 frames) uploaded in 26 seconds to a separate test collection; both camera streams are confirmed on the server.
- **Not yet done:** the full upload and search indexing. Both are waiting on two decisions from you, listed under Next steps.

## Source dataset

The source is [Bigenlight/cube_in_cup_raw](https://huggingface.co/datasets/Bigenlight/cube_in_cup_raw) on Hugging Face: 24 teleoperated demonstrations of a UR7e arm with a gripper putting a cube in a cup, recorded on 2026-07-20.

| Item | Detail |
| --- | --- |
| Takes | 24, numbered take_01 to take_26 (04 and 06 are not in the dataset) |
| Cameras | cam1 = fixed scene camera, cam2 = wrist camera |
| Robot streams | joint positions and efforts (6 joints), tool pose, joint commands, gripper position and command |
| Raw size | about 210 MB in total |
| Revision tag | bigenlight_cube_in_cup_raw_2026_07_20 |

## Conversion

Each raw take became one vmodal episode: two 30 fps video clips, a frame map that ties every video frame to a timestamp, the robot telemetry, and an episode metadata file.

1. **Video:** the scene camera sets the episode timeline. Both clips are re-encoded at a constant 30 fps so frame N in one clip lines up with frame N in the other.
2. **Wrist camera sync:** each scene frame is paired with the wrist frame closest in time. The largest offset across all 24 takes is 34.3 ms, about one frame.
3. **Start trim:** scene frames recorded before the robot's first telemetry sample are dropped (0 or 1 frame per take), so every frame has robot data behind it.
4. **Telemetry:** one row per joint-state sample, about 75 per second. Tool pose, commands and gripper readings use the latest value at each sample's time.
5. **Telemetry format:** the row layout is registered as `ur7e_gripper_raw_76hz` version 1, so every episode is checked against the same specification.

In total that is 19,968 telemetry rows and 95 MB of video.

## Validation results

All 24 episodes passed validation with zero errors and zero warnings. The checks cover telemetry layout, timestamps, gaps, coverage of every video frame, and video-to-telemetry alignment. Telemetry ran at 70.7 to 78.7 samples per second, and the longest gap was 43.7 ms (take_12).

| Take | Frames | Duration (s) | Telemetry rate (Hz, median) | Longest telemetry gap (ms) | Max wrist offset (ms) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| take_01 | 504 | 16.8 | 74.1 | 29.0 | 24.0 | pass |
| take_02 | 492 | 16.4 | 74.6 | 25.1 | 20.2 | pass |
| take_03 | 322 | 10.7 | 76.3 | 25.8 | 18.6 | pass |
| take_05 | 273 | 9.1 | 74.3 | 29.7 | 20.5 | pass |
| take_07 | 260 | 8.7 | 74.1 | 30.9 | 20.7 | pass |
| take_08 | 247 | 8.2 | 74.6 | 29.5 | 24.7 | pass |
| take_09 | 341 | 11.4 | 75.2 | 28.9 | 18.9 | pass |
| take_10 | 206 | 6.9 | 74.1 | 33.9 | 17.6 | pass |
| take_11 | 226 | 7.5 | 72.5 | 28.2 | 18.0 | pass |
| take_12 | 220 | 7.3 | 74.1 | 43.7 | 23.7 | pass |
| take_13 | 248 | 8.3 | 74.6 | 26.1 | 16.6 | pass |
| take_14 | 209 | 7.0 | 70.7 | 34.0 | 19.5 | pass |
| take_15 | 253 | 8.4 | 76.9 | 28.4 | 16.9 | pass |
| take_16 | 260 | 8.7 | 73.5 | 30.7 | 19.0 | pass |
| take_17 | 253 | 8.4 | 72.5 | 28.3 | 17.2 | pass |
| take_18 | 214 | 7.1 | 74.6 | 27.9 | 18.8 | pass |
| take_19 | 204 | 6.8 | 76.9 | 26.8 | 18.5 | pass |
| take_20 | 242 | 8.1 | 74.1 | 29.7 | 18.4 | pass |
| take_21 | 231 | 7.7 | 76.9 | 29.5 | 34.3 | pass |
| take_22 | 221 | 7.4 | 74.1 | 33.4 | 16.3 | pass |
| take_23 | 49 | 1.6 | 78.7 | 26.7 | 18.6 | pass (see Findings) |
| take_24 | 247 | 8.2 | 75.8 | 28.5 | 20.2 | pass |
| take_25 | 269 | 9.0 | 76.3 | 29.8 | 23.2 | pass |
| take_26 | 229 | 7.6 | 75.2 | 32.0 | 17.9 | pass |

This was a dry run: the checks ran locally and no data left the machine.

## Live SDK test

One real episode went through the full upload path on the vmodal test server, and the server shows it in place. To keep the production collection clean, it went to a separate test collection.

| Item | Result |
| --- | --- |
| Episode | take_19: 204 frames, 6.8 s, about 3.3 MB of video |
| Server | vmodal test environment (searchapi-test.v-modal.com) |
| Collection | cube_in_cup_sdk_test (throwaway) |
| Pre-upload check | passed, 0 errors |
| Upload | succeeded in 25.7 s: both camera clips plus episode metadata |
| Server-side check | collection listed, with sub-collections cam_scene and cam_wrist |
| Search index | not built yet, so the episode cannot be searched |

The production collection, cube_in_cup_raw_v2, holds no uploaded data yet.

## Findings and caveats

The data is clean, but a pass on our checks means the data is well formed, not that the demonstration succeeded.

- **take_23 is a recording misfire.** It lasts 1.6 s (49 frames), against 6.8 to 16.8 s for the other takes. Its metadata marks it as unsuccessful (success = false), but it passes every technical check because its data is well formed. It needs a decision before upload.
- **Time zone of the start times is unknown.** Episode start times come from the take folder names. We treated them as UTC, so absolute times may be off by a whole number of hours. Relative timing within each episode is not affected.
- **The telemetry format is a draft.** We drafted the `ur7e_gripper_raw_76hz` v1 specification from the dataset itself. It has not had a domain review yet.
- **Wrist camera offset.** In some frames the wrist camera repeats its previous image, because the two cameras were not hardware-synced. This happens in 1 to 29 frames per take, and the worst offset is 34.3 ms (take_21). That is normal for this setup and inside the validation limits.

## Next steps

We need two decisions from you; the full upload can start as soon as we have them.

- [ ] **Decision:** approve the `ur7e_gripper_raw_76hz` v1 telemetry format (or send corrections).
- [ ] **Decision:** for take_23, choose one: leave it out, upload it tagged as a failed attempt, or upload it as is.
- [ ] Optional: confirm the recording time zone so episode start times can be corrected.
- [ ] Upload the approved episodes to cube_in_cup_raw_v2. Based on the test, this takes about 10 to 15 minutes.
- [ ] Build the search index, then confirm that episodes can be found and retrieved frame by frame.
- [ ] Delete the test collection cube_in_cup_sdk_test.
