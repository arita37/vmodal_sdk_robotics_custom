# Skills

Agent skills for working with VModal. Each folder is one skill (`SKILL.md` + helpers).

| Skill | What it does |
|---|---|
| [vmodal-robot-similar](vmodal-robot-similar/SKILL.md) | Find similar robot failures using frames and local telemetry; export candidate tags and explicit human review rows. |
| [vmodal-find](vmodal-find/SKILL.md) | Search a collection, group hits into scenes, and verify every detail of the query on the frames (PASS / PARTIAL / FAIL) |

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
