---
name: vmodal-robot-format-review
description: Draft or review a vmodal telemetry format spec against real robot episodes - observed ranges, rates and gaps, units, quaternion norm and sign flips, gripper open/close polarity, command-to-state lag - and write a findings table plus a suggested next-version draft. Use before registering a format, when a format is "pending review", or when validation errors look like spec problems.
---

The validator only checks data against the spec; nobody checks the spec against the data.
A wrong unit or gripper polarity passes every check and silently breaks failure detectors and
training. This skill produces the evidence a human needs to approve a format in minutes.

## Steps
1. Get a spec file:
   - registered: `MCP_ROBOT_DIR/formats/<format_id>/v<N>.json` (`telemetry_format_list` shows ids);
   - new dataset: MCP `telemetry_format_draft_from_file(path=<one telemetry.jsonl>, output_path=<draft.json>)`.
     The draft has `"?"` for units, ranges and limits; this script fills ranges/rates from data and
     leaves units as `"?"` on purpose.
2. From the MCP package root:
   `.venv/bin/python skills/vmodal-robot-format-review/scripts/format_review.py SPEC_JSON EPISODES_DIR OUT_DIR`
3. Present `OUT_DIR/format_review.md` (error → warn → info). Explain each **error** with its evidence
   numbers. Typical errors: polarity label contradicts data, values outside range, rad/deg or
   m/mm mix-ups, columns missing or extra.
4. Hand the user `OUT_DIR/<format_id>.v<N>.draft.json`. It always has `checked_by: "?"`.
   Ask them to confirm units, polarity and limits they own. Never fill `checked_by` yourself.
5. Only after explicit approval: MCP `update_json_format_specs_from_file(path=..., collection_name=...)`.
   Registered versions are immutable: a change means a new `format_version` and, for already
   validated data, a new collection (one collection = one dataset_rev + one format).

## Reading the findings
- `sign flips` in quaternions are legal (q and −q are the same rotation) but break delta
  actions and normalization → run **vmodal-robot-telemetry-repair** before **vmodal-robot-norm-stats**.
- `state tracks command with ~X ms lag` is controller behaviour, not a spec limit; it feeds
  action/observation alignment. Low correlation means the estimate is unreliable.
- Thin margin on `max_gap_ms` means one bad episode away from failing; investigate the episode,
  don't widen the limit by reflex.
