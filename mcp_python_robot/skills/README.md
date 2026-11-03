# Skills

Agent skills for working with VModal. Each folder is one skill (`SKILL.md` + helpers).

| Skill | What it does |
|---|---|
| [vmodal-robot-similar](vmodal-robot-similar/SKILL.md) | Find similar robot failures using frames and local telemetry; export candidate tags and explicit human review rows. |
| [vmodal-find](vmodal-find/SKILL.md) | Search a collection, group hits into scenes, and verify every detail of the query on the frames (PASS / PARTIAL / FAIL) |
| [vmodal-track](vmodal-track/SKILL.md) | Track a subject across a collection and return a verified trail of every appearance; can follow one specific subject (identity mode, with search by image). Needs vmodal-find. |

Requires the robot MCP: see [the package README](../README.md).

## Use

- **Claude Code in this repo:** nothing to do. `.claude/skills/` links here, so the skills load automatically.
- **Claude Code in any project:** link it into your personal skills:

  ```bash
  ln -s "$(pwd)/skills/vmodal-find" ~/.claude/skills/vmodal-find
  ln -s "$(pwd)/skills/vmodal-track" ~/.claude/skills/vmodal-track   # needs vmodal-find next to it
  ```

  Restart Claude Code afterwards.
