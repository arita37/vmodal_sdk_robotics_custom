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
     The draft has `"?"` for units, ranges and limits; this script proposes ranges/rates and
     leaves units as `"?"` on purpose. Existing spec ranges are preserved. Compatible,
     consistent header ranges take precedence over sample extrema, but still need human
     approval. Declared normalized gripper units use [0, 1] without a margin. Constant
     or near-constant components without declared limits leave ranges unresolved;
     never guess physical joint limits from a no-motion sample.
2. From the MCP package root:
   `.venv-robot/bin/python skills/vmodal-robot-format-review/scripts/format_review.py SPEC_JSON EPISODES_DIR OUT_DIR`
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

- Sample-based ranges (when all components vary) describe only the observed data plus
  a margin, not verified operating limits. Confirm against robot documentation before
  production use. Conflicting or incompatible header ranges require human resolution.

- Always run the script and report its findings, including current outliers and metadata
  clock checks; do not substitute an assistant-only assessment. Current ranges are never
  inferred from sample extrema: missing limits need documented header/spec bounds or
  human input. Outlier warnings are statistical evidence, not motor safety limits.
- Metadata is read from each episode's `meta.json` and/or sibling `meta/<uid>.json`.
  A missing/ambiguous clock or missing metadata is explicitly reported as unverified;
  a timestamp's magnitude alone never establishes a UTC epoch.
- Quote the script's placeholder counts from the written draft: total `?` values,
  unresolved data/policy values, and the two required human sign-off values separately.
  Proposed fields are still unapproved; never claim all fields are resolved from data.
