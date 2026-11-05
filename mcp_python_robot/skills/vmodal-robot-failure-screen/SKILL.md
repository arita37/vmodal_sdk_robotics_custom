---
name: vmodal-robot-failure-screen
description: Screen robot demonstration episodes for outcome problems that pass format validation - misfires, too short, no grasp command, gripper not closing, slow or stuck release, not released, low motion, idle, end-pose outliers - with contact sheets, an empty human review sheet and an exclusions file built only from human decisions. Use before VLA training or upload, when asked which demos are bad/failed, or to cross-check success labels.
---

Format checks prove data is well formed, not that the demo succeeded (a 1.6 s misfire passes
everything). This screen turns hours of watching videos into reviewing a handful of flagged
episodes, each with its evidence and a contact sheet.

## Steps
1. From the MCP package root:
   `.venv/bin/python skills/vmodal-robot-failure-screen/scripts/failure_screen.py screen EPISODES_DIR OUT_DIR [--thresholds robot.json]`
   Field names default to `cmd_gripper`, `gripper`, `ee_pos`; override them and any limit in the thresholds JSON.
   Gripper polarity is inferred from the data and printed. If it contradicts the format's unit
   label, raise it (see **vmodal-robot-format-review**).
2. Open the PNGs in `OUT_DIR/contact_sheets/` (scene camera at 0/25/50/75/100%) and describe
   what each shows. That visual check is what turns a candidate into a finding.
   For tighter windows use MCP `robot_retrieve` on indexed collections, or
   **vmodal-robot-sync-audit** `event_strip` locally.
3. Present a table: episode, meta.success, flags with evidence, what the frames show,
   and the suggestion from `review_sheet.csv`. Call out disagreements with `meta.success`.
4. The human fills `decision` (keep | exclude | relabel_failure) and `note` in `review_sheet.csv`.
   Never fill decisions yourself, even when the evidence looks obvious.
5. `failure_screen.py review OUT_DIR/review_sheet.csv "<reviewer name>" OUT_DIR/exclusions.json`.
   It refuses while any flagged episode lacks a decision. `exclusions.json` feeds
   **vmodal-robot-norm-stats** and **vmodal-robot-staged-upload**.

## Rules and severities
| rule | severity | meaning |
|---|---|---|
| too_short / no_close_command / gripper_did_not_close / low_motion | high | likely not a valid demo |
| slow_or_stuck_release | medium | release slower than max(1 s, 3× collection median): stuck gripper or a retry inside the demo |
| closed_further_than_peers | medium | possible empty grasp |
| not_released / mostly_idle / end_pose_outlier | medium | ending or pacing unlike peers |
| duration_outlier | low | long or short but otherwise normal; usually keep |

- Candidates are `source=auto, review_status=unreviewed`. They are never accepted tags, and
  episodes are never deleted.
- A demo with a recovery (e.g. a stuck release, then a regrasp) can be valuable training
  data. Keep or exclude it is the reviewer's call, so present it neutrally.
