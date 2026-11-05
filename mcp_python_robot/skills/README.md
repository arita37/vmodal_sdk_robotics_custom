# Skills

Agent skills for working with VModal. Each folder is one skill (`SKILL.md` + helpers).

| Skill | What it does |
|---|---|
| [vmodal-robot-similar](vmodal-robot-similar/SKILL.md) | Find similar robot failures using frames and local telemetry; export candidate tags and explicit human review rows. |
| [vmodal-find](vmodal-find/SKILL.md) | Search a collection, group hits into scenes, and verify every detail of the query on the frames (PASS / PARTIAL / FAIL) |

### Robot data preparation (VLA training)

Run in this order; each step's output gates the next. All scripts run from the MCP package root with `.venv/bin/python`.

| Skill | What it does |
|---|---|
| [vmodal-robot-qc-batch](vmodal-robot-qc-batch/SKILL.md) | Dry-run validate a whole episode folder in one pass: verdicts, metadata completeness, collection outliers. |
| [vmodal-robot-format-review](vmodal-robot-format-review/SKILL.md) | Check a telemetry format against the data (ranges, rates, units, gripper polarity, quaternions, command lag); draft the next version. |
| [vmodal-robot-telemetry-repair](vmodal-robot-telemetry-repair/SKILL.md) | Repair order/duplicates/short NaN runs/quaternions/overshoot/short gaps into a new folder with a repair log. |
| [vmodal-robot-sync-audit](vmodal-robot-sync-audit/SKILL.md) | Camera/telemetry alignment audit, motion-based lag with confidence intervals, gripper-event frame strips, controlled time shift. |
| [vmodal-robot-failure-screen](vmodal-robot-failure-screen/SKILL.md) | Flag misfires and bad demos that pass validation; contact sheets; human review sheet → exclusions.json. |
| [vmodal-robot-norm-stats](vmodal-robot-norm-stats/SKILL.md) | 30 fps state/action normalization stats for VLA training plus jump, gripper and lag checks; npz export. |
| [vmodal-robot-staged-upload](vmodal-robot-staged-upload/SKILL.md) | Gated, resumable upload: offline plan → canary → run → server verify → index + search smoke test. |

Requires the robot MCP: see [the package README](../README.md).

## Use

Only the two skills listed above are included. No automatic `.claude/skills/` links
are supplied in this checkout. To make them available in Claude Code, run from the
MCP package directory and link them into your personal skills:

  ```bash
  mkdir -p ~/.claude/skills
  ln -s "$(pwd)/skills/vmodal-find" ~/.claude/skills/vmodal-find
  ln -s "$(pwd)/skills/vmodal-robot-similar" ~/.claude/skills/vmodal-robot-similar
  ```

  Restart Claude Code afterwards.
