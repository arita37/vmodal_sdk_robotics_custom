# VLA implementation notes — 2026-11-03

Implemented in the sibling `vmx_mobile` checkout: the robot MCP and reference workflow were
moved out of `vmx_api`. The robot directory was already untracked when work began; unrelated
untracked `.github/workflows/api_endpoint_docs.yml` was left alone.

These are historical implementation notes from that checkout. The current checkout
does not include the referenced CI workflows; run `bash test.sh test` locally instead.

## Delivered scope

- P0: sample-driven drafts, validated immutable format registration, collection bindings,
  registry listing and standalone checks.
- P1: telemetry/frame/video checks, normalized gzip sidecars, per-frame indexes, resumable
  SDK episode uploads, partial handoff status and LeRobot v3 packed-video cuts.
- P2/P3: frame-map time conversion, exact local decode/index fallback, named telemetry
  windows/summaries, version-pinned paginated robot search and manifest filters.
- P4/P5: similar-failure skill, versioned unit-aware detectors with gap masking, signature
  distances/rank fusion, unreviewed candidate exports and explicit human superseding rows.
- Two committed synthetic episodes, JSON/JSONL/Parquet telemetry, frame maps, metadata and
  packed LeRobot samples under `data/robot`; deterministic generator at `data/generate.py`.
- Robot-specific test/release-artifact workflow with secret scanning, public/repository SDK
  suites, source/wheel checks and optional authenticated network suites.

## Verification

All offline suites pass through `bash test.sh test`. Added 26 regression groups across
`test_robot_format.py`, `test_robot.py`, `test_robot_similar.py`, and `test_robot_mcp.py`;
the skill also exposes the shared detector/tag suite from its own test directory.

Coverage includes immutable conflicts, header mismatches, bad fields/NaN/ranges, coverage
limits, gaps and command age, frame-mode exports, rejected uploads, partial retry/resume,
dry-run isolation, packed-clip first/last-frame identity, all 4,569 C9 frame round trips,
integer epoch precision, image fallback/sidecars, downsampling gaps, summaries, metadata
checksums, search pagination/index drift/date filters, detectors/signatures/fusion, C8
Parquet/JSONL and explicit human review, plus a real offline MCP stdio session.

Bash syntax, ShellCheck error-level checks, Actionlint, skill validation, wheel/sdist build
and Twine checks pass. The complete offline suite also passes from an extracted source
distribution; the installed wheel executable starts from `/tmp` outside the source tree.
The new untracked robot files have no graph coverage, so verification used direct source
reads and executable tests after the required graph coverage checks.

The final audit of session changes found no remaining issues requiring a todo block.

## Documentation impact checklist

- Subjects: telemetry identity/time/layout, local artifacts, upload completion, retrieval,
  search, review tags, installation and CI.
- Updated: robot contract/examples, tool/environment/install docs, both package READMEs,
  prompts, sample guide, skill index and similar-failure catalog.
- Neighboring checks: SDK upload/metadata signatures, reference release workflow, copied
  installer behavior, environment defaults and existing MCP registry/test contracts.
- Removed copied generic-MCP installation/publication instructions from active robot guides.
  The VLA draft is retained as the source design; current behavior and clarifications are in
  `robot_contract.md`. In particular, normalized opening decreases gripper position, and
  different legacy schema ids are not silently treated as aliases.

## External validation remaining

Authenticated SDK, MCP stdio, packaged upload/index/search and full robot integration tests
passed locally on 2026-11-03; see `live_api_validation.md`. The customer's M2 ~100-episode recall
study remains external work. Synthetic videos verify handoff and alignment, not real visual failure
quality. P6 backend telemetry serving/filtering remains outside this package. Phase A local
sidecars and manifest completion are explicit; remote multi-asset transactions are unavailable.
The workflow builds release artifacts without publishing to an unspecified public robot repo.
