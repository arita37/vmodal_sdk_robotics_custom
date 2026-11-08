# VModal robotics MCP improvements for auditable training data correction

Updated 2026-11-08. Status: proposal, not implemented. Based on Rerun 0.42.0 and the repository snapshot below.

Audit target: `arita37/vmodal_sdk_robotics_custom`, `mcp_python_robot`, main commit `5561e77c5acd9a6ff9f57c99fe7f9a910d62361c`. Source inspection, plus a narrowly isolated execution of the existing repair functions; not a full application or live-service test. The requested stable Rerun documentation identifies 0.42, with matching release tag 0.42.0; the integration scope is defined below. All tool names prefixed “proposed” below are suggestions, not existing APIs.

## Executive finding

Do not build a new repair stack from scratch. This repository already has real telemetry correction, synchronization auditing and shifting, normalization, human-reviewed exclusions, versioned tags, resumable uploads, and substantial tests. The highest-value work is to harden those paths, expose shared services as MCP tools, and add Rerun as a multimodal inspection and transformation layer. Rerun is neither an automatic correctness oracle nor a replacement for VModal’s video search, episode manifests, reviewed formats or training export contracts.

## What exists today

1. **Nine registered robotics/format MCP tools:** `telemetry_format_draft_from_file`, `update_json_format_specs_from_file`, `telemetry_format_list`, `telemetry_format_check`, `robot_episode_upload`, `robot_dataset_upload`, `robot_manifest_build`, `robot_retrieve`, `robot_find`. [Registry, lines 505–523](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/registry.py#L505-L523). The dispatcher executes these through `robot_func`, injects clients for non-dry uploads and callbacks for search/retrieval. [Dispatcher, lines 450–465](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/main_mcp.py#L450-L465).
2. **Reviewed format and alignment contract:** required format reviewer/time, field shapes/names/units/dtypes/roles, nan rejection, int64 nanoseconds, ranges/unit norms, frame-map schema, gap/rate checks, nearest-state and causal command rows with tolerances. Frame-mode exports are also supported. [Format validator, lines 19–89 and 234–314](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/robot_format.py#L234-L314).
3. **Episode/version integrity and resume:** locks, dataset-revision isolation, input content hashes, preserved telemetry/frame map/check artifacts, partial/uploaded status and identical-input skipping. Dry run avoids network but DOES create local checks/artifacts and may update a manifest. [Upload implementation, lines 73–167](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/robot.py#L73-L167).
4. **Time-aware retrieval:** search-offset vs nanosecond distinction, authoritative frame maps, gap-aware downsampling, dataset/format checks, separate causal command lookup, indexed-frame/local-decode fallback. [Retrieval, lines 243–426](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/robot.py#L243-L426).
5. **Telemetry repair skill:** sorting, duplicate keep-last, bounded nonfinite interpolation or command hold, quaternion renormalization/sign continuity, small clamps and bounded gap fill. Creates new folders, counts operations, compares validator verdicts. This is a script, not a registered repair MCP endpoint. [Repair implementation](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/skills/vmodal-robot-telemetry-repair/scripts/telemetry_repair.py#L49-L225).
6. **Sync audit skill:** decoded count/CFR/coverage/repeats, motion correlation, correlation-plateau interval, collection-consistency heuristics, gripper-event strips and a separate telemetry shift command. Documentation explicitly requires visual review and confirmation. [Sync implementation](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/skills/vmodal-robot-sync-audit/scripts/sync_audit.py#L41-L221).
7. **Normalization skill:** frame-aligned state/action pairs; mean/std/min/max/q01/q99; zero variance, action jumps, gripper threshold and lag warnings; optional NPZ export. [Normalization, lines 61–165](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/skills/vmodal-robot-norm-stats/scripts/norm_stats.py#L61-L165).
8. **Staged upload skill:** offline QC/exclusion planning, episode file hashes, confirmation flag, canary, stop-on-consecutive-failures, resume, collection/subcollection verification. [Staging, lines 83–219](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/skills/vmodal-robot-staged-upload/scripts/staged_upload.py#L83-L219).
9. **Candidate discovery and reviewed labels:** unit/role-aware failure heuristics, gap-separated signatures, index-version-aware rank fusion, append-only unreviewed candidates and explicit superseding human decisions. Heuristic detector “confidence” is a constant 0.8, not a calibrated probability. [robot_similar.py, lines 18–246](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/src/mcp_server/robot_similar.py#L18-L246).

## P0: correctness and safety before more features

### P0.1 One authoritative alignment engine

**Evidence:** validator computes valid `tel_row` and `cmd_row`, gap masks and age checks (`robot_format.py` 285–304), but normalization repeats the bisect logic without those guards (`norm_stats.py` 81–90). `max(bisect_right(t, tt)-1, 0)` uses the first future command when a frame predates all telemetry. Normalization trusts that callers previously ran QC; it does not enforce the QC prerequisite. Retrieval applies an additional hardcoded 10 ms state cutoff (`robot.py` 386), unlike the reviewed `frame_tol_ms`.

**Change:** Extract a typed shared alignment result used by validator, retrieve, norm stats and Rerun export. Encode nearest vs causal hold, max age, gap validity, required fields and per-camera choice. Reject/explicitly mask frames without prior commands. Require an exact content-hash-bound QC result before training export. Accept the spec’s configurable time field instead of hardcoded `t_ns`. Include original/corrected timestamps and clock domains.

**Acceptance:** Before-first-command frame is invalid, never future-filled; stale/missing commands match validator masks; gap-boundary behavior is identical across all four consumers; int64 epoch-ns round-trips exactly; custom time field works; setting tolerance to 5/20 ms gives matching retrieval and training results; output states/actions have explicit source sample IDs and interpolation/hold policy.

### P0.2 Make repair schema-preserving and explicitly conservative

**Evidence:** `telemetry_repair.py` converts every numeric field to float arrays (84–95), normalizes quaternions without zero-norm protection (112–123), initializes gap output with `t[0]` even when every row was dropped (142–144), and rebuilds output from only time + declared fields (157–177). It therefore loses allowed extra fields and `frame_index`; int/bool fields become floats. Leading NaN commands use the next available value (102–104), which is future-command imputation. Its quaternion detection also treats any `unit_norm` field as a quaternion and any field containing “quat” as one, without explicit quaternion shape/order metadata.

**Verification performed:** Executed only the actual `repair` and `runs` function ASTs with NumPy/math/json, avoiding app imports/network. Valid integer rows with `extra` and `frame_index` returned float values with both extra keys removed and no operation logged; empty rows raised `IndexError`. This confirms these narrow defects, not general application behavior. Additional isolated probes confirmed zero-norm quaternion output becomes NaN with no `unrepaired` entry, and leading missing commands are filled from a future value; the normalization selection expression likewise selects a future command. The downstream validator may reject dtype/nonfinite outputs, so these findings do not mean every faulty result is accepted or uploaded.

**Change:** Type-aware operators and explicit operation allowlist; preserve untouched columns and frame indices; mark inserted rows and source lineage; no interpolation for categorical/bool/int fields unless an approved rule exists; no leading command backfill; zero/near-zero quaternions reject; explicit xyzw/wxyz and orientation semantics; quaternion SLERP or documented normalized interpolation with angular bounds; fail with structured errors for empty/all-invalid input. Keep drop/duplicate policy in the approved plan, not implicit defaults. Gate max repaired fraction and total dropped rows, not just run length. An `unrepaired` result cannot silently become a publishable pass.

**Acceptance:** Identity repair preserves schema, dtypes, unknown allowed fields and values; no source file changes; frame mode remains valid; empty/all-bad/single-row data returns an actionable report; zero and antipodal quaternion tests; integer, bool, string and optional-column tests; leading NaN commands remain invalid; deterministic repair hash and row-level provenance; repeated repair is idempotent or explicitly rejected.

### P0.3 Protect originals and make derived revisions atomic

**Evidence:** repair and sync shift hard-link unchanged files into writable output trees (`telemetry_repair.py` 200–209; `sync_audit.py` 175–184). Original paths differ, but later in-place modification of a hard-linked video/frame map modifies the original bytes. Both permit overwriting an existing output directory; provenance holds path/tool/counts but not a complete immutable lineage chain. Shift records milliseconds and tool but no approval or validation result and returns success before rechecking.

**Change:** Immutable content-addressed originals; reflink/copy or read-only content store with safe write isolation; unique derived revision; atomic temporary-output-to-final commit; chain input/output SHA-256, format hash, code/dependency version, operation parameters, reviewer, approval and QC report. Keep logical episode identity but bind every output to a new dataset revision. Refuse source/output overlap through symlinks/ancestor paths and refuse accidental destination reuse.

**Acceptance:** Modify a derived frame map without changing source hash; interruption never publishes partial revision; rejected QC never advances status; rollback returns original references; reapplying a shift cannot silently double-shift; overflow and nonfinite shift rejected.

### P0.4 Harden sync estimation before exposing it to agents

**Evidence:** `audit_one` calls `best_lag` before checking decoded-frame/map counts (`sync_audit.py` 85–91), so different lengths can produce broadcasting errors instead of the intended structural issue. Timestamps become float64 epoch nanoseconds (33, 77–78); use int64 subtraction before conversion. Correlation uses endpoint extrapolation via `np.interp` and a plateau of correlations within 0.05 below the peak labelled `lag_ci_ms`, which is not a statistical confidence interval. A three-frame repeated map flag is evidence of repeated data, not proof of sensor freezing.

**Change:** Check decode/map shape first and skip lag on invalid structure; offset integer clocks locally before float math; restrict correlations to true overlapping observations; configurable motion source and units; minimum excitation/overlap, search-edge and multimodal peak warnings; call plateau a resolution/ambiguity band; optional bootstrapped uncertainty separately. Drift/piecewise clock changes need a reviewed affine/piecewise clock mapping, not a whole-collection constant shift. Track sensor capture, receive and command-application clocks distinctly.

**Acceptance:** Count mismatch produces structured QC, no crash; known ±200 ms offset detected with correct sign; constant/noisy/no-motion streams produce “unresolved”; independent camera offsets do not trigger one global fix; linear drift is distinguished from constant shift; ns-sensitive fixtures survive; visual event-strip tests cover events near clip edges without implying duplicated tiles are distinct evidence.

### P0.5 Bind every publication gate to exact evidence

**Evidence:** staged plan checks QC collection/revision but matches verdicts only by episode UID, then hashes current files (`staged_upload.py` 84–115). This does not prove those bytes were QC-tested. Run checks episode file hashes but not current format binding, QC/exclusion content or a successful canary (`157–165`). Exclusions are optional; `--include_flagged` permits flagged uploads despite the skill’s stronger “only pass” instructions. Canary rejects `reject`, but permits `flag` and checks only presence of `cam_scene`. Verify checks collection/subcollection existence, not every remote artifact/hash.

**Change:** Plan digest includes raw/derived asset hashes, format hash, QC version/report hash, exclusion/review hash, exact target and canary result. Validate all at execution; policy for flagged data must be explicit. Recheck per-episode preconditions immediately before uploading or upload immutable snapshots. Verify expected camera assets, counts, metadata and backend checksum when supported; state clearly where server APIs cannot prove byte equality. Do not claim collection existence verifies every episode.

**Acceptance:** Changed QC inputs, exclusions, format binding, target or canary reject stale plan; excluded canary rejected; wrist missing fails when expected; partial upload resumes correctly; remote asset mismatch reported; uncertainty is not a successful verification; dry-run tests assert no network while documenting local side effects.

## P1: integrate Rerun without duplicating upstream capabilities

### P1.1 A canonical VModal↔Rerun adapter

**Proposed services/tools:** `robot_recording_export`, `robot_recording_import`, `robot_recording_inspect`.

Map episode/revision/format identity, scene/wrist camera streams, telemetry field semantics and units, command/state roles, calibrations/extrinsics, quality masks, reviewed labels and source provenance into explicit entity paths. Preserve authoritative frame-map int64 times; distinguish capture timeline, corrected timeline and frame sequence. Preserve actual video presentation timestamps and decoding mapping; a sampled/visualized frame is not proof of retraining alignment. Keep raw video unchanged unless an explicitly approved conversion creates a new asset.

Use Rerun 0.42 RRD/MCAP readers and supported archetypes/logging for import/export; MCAP decoding schemas and mappings remain application responsibilities. Add optional Rerun dependency extras with a tested version range; do not claim it is currently installed. Retain present two-camera/30 fps ingestion contract until deliberately versioned: `robot.py` 79/175 and format/video checks explicitly require it. Generalizing to arbitrary cameras, VFR, rates, depth, LiDAR, IMU and force is a migration, not a one-line toggle.

**Acceptance:** Synthetic episode round-trip preserves exact telemetry times, frame identities, units, dtypes and source hashes; no video-transcode by default; unsupported MCAP schema reports a specific skip/error; mixed rates and camera offsets render correctly; old 30 fps clients remain compatible; export no longer requires loading an entire dataset into RAM.

### P1.2 Shared review workspace using official Viewer MCP

**Proposed VModal orchestration:** `robot_review_session_create`, returning recording, selection and review identifiers; small adapter only where VModal-specific context is necessary. Reuse official `rerun viewer-mcp` stdio/gRPC and its time, blueprint, headless and screenshot features. Do not implement a parallel generic camera/time/screenshot MCP server.

Provide a before/after blueprint: synchronized scene/wrist video, robot geometry, state vs command plots, scalar/range/gap indicators, quality mask and editable review metadata outside raw data. Move to suspicious event/window; record screenshot plus recording/revision/timeline/time/blueprint hash. Human decisions feed existing append-only `review_tags`, not a silently mutated training label.

**Acceptance:** A `robot_find` hit opens exact episode/revision/time; headless review screenshot comes from the intended frame; before/after remains time synchronized; screenshot artifact includes full replay references; bad/unavailable viewer is an inspection failure, never an automatic pass; review candidate remains unreviewed until explicit decision.

### P1.3 Declarative correction plan, preview, apply and validate

**Proposed tools:** `robot_correction_plan`, `robot_correction_preview`, `robot_correction_apply`, `robot_correction_validate`, `robot_revision_diff`.

Refactor existing scripts into shared pure transformation/validation services first. Use Rerun’s 0.42 chunk transformations (`RrdReader`/`McapReader`, lenses, `map`/`filter`, `write_rrd`) rather than inventing an RRD mutation format. A VModal plan must add domain semantics: approved unit conversions, time offsets/drift mapping, entity/column rename, row filtering, bounded typed repair, calibration update, trim/split and annotation corrections. `filter` may remove data; it does not magically make data valid. Transform a new artifact, re-open it and compare counts/times/schema/checks before publishing. RRD output alone is not a LeRobot/NPZ training export.

**Acceptance:** Dry preview reports affected rows/frames/entities and exact operations; identity transform preserves semantics; invalid fields/units fail before apply; atomic output; source and output checksums; no hidden dropping; re-read output and run existing QC; approval bound to exact plan digest; incompatible clock/unit/calibration mappings require review.

### P1.4 Explicit data-engineering quality rules beyond schema compliance

Keep format correctness separate from semantic fitness. Add user-reviewed joint velocity/acceleration/jerk, current/force saturation, quaternion angular speed, calibration reprojection, camera blur/black/freeze/dropped-frame checks, timestamp-vs-metadata `start_time` consistency with timezone/epoch meaning, action-state causality and episode outcome labels. Visual heuristics flag rather than invent replacement observations. Unknown physical units/frame conventions prohibit automatic conversions. Do not interpolate across contact transitions, reset boundaries or long outages just because a numeric run is short.

**Acceptance:** Unit-converted equivalent datasets have equivalent physical verdicts; legitimate intentional gripper steps remain valid; false positive/negative rates measured on reviewed fixtures; calibrated probabilities only when actually calibrated; synthetically corrupted observations remain marked and can be excluded from training.

## P2: scale and training reproducibility

1. **Catalog/layers and DataFusion:** optional Rerun catalog reader/query integration for cross-recording QC, issue queues and reviewer annotations. Use layers for derived/reviewed information with explicit revision semantics; do not imply a layer makes raw data disappear or that it is a transactional training publication system. VModal manifest remains authoritative until a deliberate migration specifies conflicts, consistency and rollback. Push filters/projections into readers, stream chunks and bound result sizes.
2. **Split-aware normalization:** train-only statistics; manifest of split IDs and hashes; no validation/test leakage; explicitly weight by frame vs episode; finite-only computation after policy gating; incremental mean/variance and bounded-memory quantiles with exact/approximate algorithm recorded. NPZ export keeps quality masks/source row IDs/units/timestamps and immutable spec. Handle empty/all-excluded/one-frame datasets gracefully.
3. **Dataset curation:** duplicate/near-duplicate and temporal overlap detection across train/eval splits; related episodes/sessions/robots grouped before split; reviewed anomaly samples retained as a separate evaluation slice, not always deleted. Similarity ranking and heuristic confidence remain separate.
4. **Review lifecycle:** reuse existing append-only candidates/supersedes; add reviewer identity, affected window, revision, reason, original/new labels, approval and release manifest; query pending/accepted/rejected independently. Separate candidate-generation version, classifier calibration version and search-index revision.
5. **Async jobs and resource boundaries:** bounded jobs with progress/cancel/resume for conversion/QC/export; max bytes/time/chunks/result rows; per-episode failure isolation; no network by default for preview; allowlisted workspace roots and sanitized artifact names; review tools must not leak signed URLs, tokens or credentials into logs or RRD annotations.

## Tests and installation evidence

Existing `test.sh` runs installer/video tests plus format, robot, similarity, MCP and checkout-contract tests, with separate live modes. Preserve and extend these rather than calling the repo untested. [Runner](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/test.sh).

The checked-in November 6–7 test report records useful issues but was run on `docs/robot-mcp-beginner-readme`, not necessarily this exact main commit; treat it as historical corroboration. It explicitly did not test real uploads/indexing/search/MCAP/LeRobot dry run/video QC. Current pyproject declares fire/filelock/Pillow/pyarrow, but not NumPy, despite NumPy imports in repair/sync/norm scripts. Do not repeat the historical claim that all those other dependencies remain absent. [Dependencies](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/pyproject.toml#L10-L18).

The current repair fixture still indexes rows 400–420 and 500–504, so it is not general to small sample episodes. Replace hardcoded corruption offsets with deterministic size-aware synthetic fixtures, and assert validator outcomes, preserved source hashes and repaired-field provenance. [Fixture](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/skills/vmodal-robot-telemetry-repair/tests/make_corrupt.py#L32-L56).

Recommended CI gates: existing offline suite; schema-preservation/causality/provenance tests above; optional pinned Rerun 0.42 integration tests (RRD/MCAP transform and re-read, headless screenshots); clean-environment skills dependency smoke; deterministic multirate/clock/gap/NaN/calibration corpus; opt-in authorized live canary and per-asset verification. Never run live upload tests just to demonstrate an analysis.

## Delivery order

- M0: shared alignment, repair safety, content-bound QC/export gates and regression fixtures.
- M1: Rerun adapter plus official Viewer MCP review workflow, no automatic corrections.
- M2: reviewed transformation plan/apply/validate with immutable derived revisions and training exporter.
- M3: catalog-scale QA, versioned annotation layers, train-only stats and leakage checks.

Success criterion: a reviewer can trace every exported training sample back to raw observation, clock mapping, format, transformation plan and decision; a visually convincing Rerun recording or a schema pass alone never certifies training correctness.

## Integration architecture and compatibility

Use three distinct layers:

1. **VModal source and training authority:** reviewed format specs, episode/frame identity, search/index versions, quality policy, correction ledger, approval, source-format exports and training-release manifests.
2. **Rerun data and inspection engine:** typed multimodal logging, RRD/MCAP chunk transformations, Arrow/DataFusion queries, reusable review blueprints, optional local/remote catalog, and the existing Viewer MCP.
3. **Adapters and jobs:** a small versioned boundary between the above. Do not expose arbitrary Python callbacks, arbitrary shell commands or unrestricted file paths as an agent-facing correction interface.

### P0.6 Version and dependency contract

The requested moving `stable` documentation resolves to **Rerun 0.42**, with release/source tag **0.42.0**, released 2026-11-04. Pin `rerun-sdk==0.42.0` and the matching Viewer for the first integration. The current VModal package is **0.2.0**, supports **Python >=3.10** and declares `pyarrow>=14`; Rerun 0.42 requires **Python >=3.11**, **NumPy >=2**, **PyArrow >=18** and, for its catalog extra, **DataFusion 54.0.0** plus Pandas >=2. These are real integration constraints, not interchangeable optional imports.

Keep the existing non-Rerun Python 3.10 route working. Preferred initial deployment: a dedicated Python 3.11+ Rerun worker/sidecar with a constrained JSON/Arrow contract, while existing VModal tools continue unchanged. A single-environment optional extra is reasonable after a clean-environment dependency-resolution/test matrix proves compatibility. Do not silently change the base package's minimum Python or upgrade every dependency just to enable visualization.

Add a proposed `robot_capabilities` endpoint that reports package/runtime versions, supported source formats, available codecs/FFmpeg, Rerun/Viewer versions, optional catalog support, preview/apply/export support, and unresolved compatibility checks. Treat unsupported experimental readers as explicit capability errors, not silent fallbacks. The endpoint must not expose keys or credentials.

**Acceptance:** fresh Python 3.10 base installation still passes existing local smoke tests; Python 3.11+ Rerun environment passes transform/readback and Viewer MCP checks; mismatched Viewer/SDK is reported; missing FFmpeg or unsupported decoder has an actionable modality-specific error; skills use `.venv-robot` or the configured absolute interpreter, and NumPy is declared wherever its scripts run.

Sources: [VModal package metadata](https://github.com/arita37/vmodal_sdk_robotics_custom/blob/5561e77c5acd9a6ff9f57c99fe7f9a910d62361c/mcp_python_robot/pyproject.toml), [Rerun 0.42 package metadata](https://github.com/rerun-io/rerun/blob/0.42.0/rerun_py/pyproject.toml), [stable documentation](https://ref.rerun.io/docs/python/stable/).

### Proposed module placement

These paths are suggested implementation locations, not files created by this proposal:

| Area | Proposed module | Existing code to reuse |
|---|---|---|
| Shared causal alignment and masks | `src/mcp_server/robot_alignment.py` | `robot_format.telemetry_check`, `robot.telemetry_window`, `robot_retrieve`, norm-stats selection |
| Typed repair operations | `src/mcp_server/robot_corrections.py` | telemetry-repair and sync-audit scripts; retain thin CLI wrappers |
| Immutable plan/revision/lineage | `src/mcp_server/robot_revision.py` | content-addressed episode artifacts, locks, manifest and format hashes |
| Rerun import/export and schema | `src/mcp_server/robot_rerun.py` or isolated worker package | reviewed telemetry format, frame maps and `robot_retrieve` outputs |
| Review orchestration | `src/mcp_server/robot_review.py` | `robot_find`, existing tag/supersedes writers, official Viewer MCP |
| Training-release export | `src/mcp_server/robot_export.py` | norm-stats/NPZ paths and QC/exclusion reports |
| Schema and transport integration | existing `registry.py` and `main_mcp.py` | existing generated function schema/dispatch conventions |

Keep the same business logic behind CLI and MCP. Tests should compare both entrypoints rather than maintain two subtly different alignment/repair implementations.

### Proposed agent-facing operation contracts

Every endpoint below is **new and proposed**, except existing VModal/Rerun tools explicitly named elsewhere. Use references to immutable artifacts instead of large arrays in MCP responses.

| Operation | Main input | Main output | Allowed effects |
|---|---|---|---|
| `robot_capabilities` | none or worker selector | versions, supported formats, codec/dependency diagnostics | Read only |
| `robot_quality_scan` | episode/revision IDs, rule-set version, bounded window | finding IDs, QC digest, counters, report artifact | Local report only; no edits/upload |
| `robot_recording_export` | source revision, modalities/window, reviewed mapping | RRD path/hash, entity/timeline schema, conversion report | New derived preview only |
| `robot_review_session_create` | source/candidate revision, finding or `robot_find` hit | replay location, blueprint hash, review ID | Viewer layout/session and evidence artifacts |
| `robot_correction_plan` | source hashes, typed operations and bounds | immutable plan digest, affected counts, risks, preconditions | Plan artifact only |
| `robot_correction_preview` | plan digest | candidate RRD/files, diff metrics, screenshots | Unpublished candidate artifacts |
| `robot_correction_apply` | plan digest, approval reference, expected source/format/QC hashes | new candidate revision and lineage | Explicit bounded transformation; no implicit remote upload |
| `robot_correction_validate` | candidate revision, policy version | pass/flag/reject, exact metrics, artifact hashes | Validation report only |
| `robot_revision_diff` | base/candidate revisions | changed rows/frames/fields/labels and semantic metrics | Read only |
| `robot_training_export` | approved revision/labels, split manifest, export spec | training files, masks, train-only stats, release manifest | New training artifacts only |

Separate local artifact creation from publishing to VModal, Rerun Hub, object storage or a training registry. Existing `robot_episode_upload(dry_run=true)` has local side effects; preserve that documented behavior or add a genuinely no-write inspection mode under a distinct contract. Avoid calling a mode “read only” if it creates reports/manifests.

### Minimum durable schemas

**Finding:** `finding_id`, `rule_id/version`, `severity`, `episode_uid`, `dataset_rev`, `source_sha256`, `format_sha256`, `camera_or_field`, `timeline`, integer `t_start_ns/t_end_ns` with half-open bounds, source frame/row IDs, observed/expected values and units, evidence references, detector score kind, review state and reason. Serialize nanoseconds as decimal strings over JavaScript-facing transport where exact int64 cannot be guaranteed.

**Correction plan:** `plan_id`, canonical `plan_sha256`, immutable input refs/hashes, format/calibration/clock-domain IDs, typed ordered operations and parameters, affected intervals, maximum allowed changed/dropped/synthetic fractions, output targets, preserved-field policy, prerequisite QC digest, approval reference, tool/dependency versions and expected validation rules. No opaque executable code in the plan.

**Revision:** parent revision(s), input/output hashes, plan digest, original-to-corrected sample mapping, dropped/inserted/retimed sample masks, validation digest, reviewer decision, timestamps and publish state. Use explicit states such as `planned`, `candidate`, `validated`, `approved`, `published`, `rejected`; a Viewer screenshot cannot advance state by itself.

**Training release:** source revision set; reviewed annotation snapshot; split manifest/hash; field schema/units/frame conventions; state/action alignment and maximum-age policy; exclusion/synthetic-data policy; train-only normalization algorithm and inputs; decoder/transcode settings; output checksums and loader round-trip result. Preserve failed episodes and uncertainty as evidence rather than discarding the audit trail.

## Concrete end-to-end workflows

### Workflow A: fix a video/telemetry clock offset

1. Discover a suspect with existing `robot_find` or QC; resolve exact dataset/index revision and `robot_retrieve` frame-map times.
2. Check decoded counts, actual presentation timestamps, clock domains and overlapping time bounds before estimating lag. A correlation peak alone is only a candidate finding.
3. Open synchronized Rerun scene/wrist video, state/action traces and event markers. Inspect multiple events in the episode; distinguish physical command latency from clock misalignment.
4. Propose a signed offset or affine/piecewise clock mapping with evidence, affected modalities and uncertainty. Keep capture times unchanged in source; add corrected times and mapping metadata.
5. Apply to a new revision, regenerate alignment masks/frame indexes, and compare before/after metrics and visuals. Require causal action timestamps, tolerance and gap checks to pass.
6. Export only the approved revision. Verify source hashes unchanged, held-out events aligned, no phase/contact transition invented, and exact frame-to-sample mapping retained.

### Workflow B: repair bounded telemetry corruption

1. Run reviewed schema plus semantic QC and classify each defect: syntax, missing sample, wrong unit, saturation or true physical event. Do not clamp a real collision/current spike merely to make validation pass.
2. Plan sorting/deduplication, approved unit conversion, small state interpolation or quaternion correction with explicit limits. Keep missing leading commands invalid and retain long outages as masks/splits.
3. Preview raw/candidate traces in Rerun with inserted/dropped/changed samples visible. Preserve dtype and unrelated metadata.
4. Validate conservation of untouched values, physical limits, temporal causality, quaternion norm/order, changed fraction and every `unrepaired` item.
5. Write a new revision, record review, then regenerate train-only statistics. Export repair masks so training can include/exclude or downweight synthetic samples deliberately.

### Workflow C: correct labels and training intervals

1. Use text/image/telemetry candidate search, but preserve relevance scores separately from detector confidence and human judgment.
2. Review synchronized video and telemetry in the official Viewer MCP; use `AnnotationContext`, boxes/masks, state timelines and notes to display existing and proposed labels.
3. Persist decisions in the existing append-only tag/supersedes ledger with original/new label, reviewer, source revision, evidence and half-open time bounds. Rerun display metadata is not the system of record for annotation approval.
4. Freeze a reviewed annotation snapshot and apply interval-level training masks. Do not exclude an entire episode when only a short window is invalid unless policy requires it.
5. Check overlap/conflicts, boundary frames, class-map versions and duplicate/session leakage across splits. Re-open the exported training data to confirm exactly the reviewed samples were selected.

### Workflow D: diagnose spatial calibration errors

1. Verify frame conventions, depth scale, camera intrinsics and current calibration assets. Inspect named transform edges and their time; implicit `tf#` frames alone do not indicate a broken tree.
2. Overlay known 3D points/robot geometry in camera views, compare reprojection residuals and examine multiple times/poses. A blueprint orientation change is not a calibration fix.
3. Propose a versioned calibration update only with supporting measurements. Keep optimizer/estimation code and model assumptions explicit and external to visualization.
4. Validate reprojection and transform continuity on held-out observations, then publish a derived calibration asset/revision with all dependent samples linked.

## Rerun feature adoption map

| Rerun 0.42 capability | Use in VModal | Priority and boundary |
|---|---|---|
| `Image`, `AssetVideo`, `VideoFrameReference`, `VideoStream` | Exact event review and raw/candidate camera views | P1; source video edits and codec-safe export remain explicit adapters |
| `Scalars`, `Measurements`, `StateChange`, text and raw/dataframe views | Telemetry, uncertainty, quality masks and review evidence | P1; plot interpolation is not training resampling |
| Timelines, `TimeColumn`, `send_columns` | Capture/corrected/frame timelines and efficient batched export | P1; preserve int64, causal alignment and max-age rules |
| `RrdReader`, `McapReader`, lenses, chunk filters/maps, Arrow, `write_rrd` | Produce auditable candidate RRDs | P1/P2; actual programmable RRD transformations, not original-MP4/LeRobot writeback |
| Official `rerun viewer-mcp` and blueprints | Agent-guided synchronized review, screenshots and headless tests | P1; bridge existing service rather than duplicate controls |
| Points/boxes/masks/meshes, `Pinhole`, transforms, URDF | Geometric label/calibration/kinematic review | P2; no silent joint clamping or invented robot calibration |
| MCAP reflection and experimental HDF5/Parquet/MP4/LeRobot readers | Broader ingestion and format diagnosis | P2; schema mapping, version gating and round-trip tests required |
| Local catalog, DataFusion, datasets/layers/assets/tables | Cross-episode quality queries and review queues | P2; local catalog is available, not necessarily a paid-only feature |
| Experimental PyTorch loaders/manifests | Optional Rerun-backed training path | P3 pilot; staleness enforcement and decoder behavior must be tested |
| Audio, maps/GPS, graphs, voxels/volumes/splats | Domain-specific investigations | P3 demand-driven; do not expand manipulation-MVP scope without data need |

Sources: [0.42 chunk API](https://github.com/rerun-io/rerun/blob/0.42.0/docs/content/concepts/logging-and-ingestion/chunk-processing-api.md), [Viewer MCP](https://github.com/rerun-io/rerun/blob/0.42.0/docs/content/reference/viewer/mcp.md), [DataFusion semantics](https://github.com/rerun-io/rerun/blob/0.42.0/docs/content/concepts/query-and-transform/dataframe-queries.md), [catalog model](https://github.com/rerun-io/rerun/blob/0.42.0/docs/content/concepts/query-and-transform/catalog-object-model.md), [archetypes](https://github.com/rerun-io/rerun/blob/0.42.0/rerun_py/rerun_sdk/rerun/archetypes/__init__.py), [experimental API](https://github.com/rerun-io/rerun/blob/0.42.0/rerun_py/rerun_sdk/rerun/experimental/__init__.py).

## Delivery plan with measurable gates

These are rough engineering sizing estimates for one engineer familiar with the code, excluding data collection, deployment approvals and review turnaround. They are not delivery commitments. Each row can be a separate implementation PR; this document does not implement these changes.

| Milestone | Scope | Dependencies | Indicative effort | Release gate |
|---|---|---|---|---|
| M0 Correctness baseline | P0.1–P0.6, schema/causality/immutability/gate/dependency regressions | None | 7–12 engineer-days | All identified source-level regressions fail before fixes and pass after; existing offline suite passes |
| M1 Review integration | VModal-to-RRD export, capability endpoint, standard blueprint, official Viewer MCP bridge | M0 | 4–7 days | Both cameras and telemetry align at known events; headless evidence has replay hashes; unsupported paths fail clearly |
| M2 Auditable correction | Plan/preview/apply/validate/diff, immutable revisions, label decisions, training export | M0, M1 | 8–14 days | Every exported sample traceable; no implicit future commands; raw hashes unchanged; loader round-trip passes |
| M3 Scale and curation | Catalog queries/layers, bounded jobs, split-aware stats/leakage, richer modalities | M2 and representative dataset | 7–12 days | Declared memory/latency budgets met; cross-split duplicates handled; artifact-level resume and verification demonstrated |
| M4 Optional Rerun training | Experimental dataloader/manifest pilot | M3 | 3–6 days | Fixed sample manifest reproducibility, explicit staleness checks, decoder parity and training comparison on held-out data |

### Regression and evaluation matrix

- **Time:** epoch nanoseconds above 2^53; unsorted/duplicate rows; before-first/after-last sample; near-boundary ties; max-age violations; multiple rates; camera offsets; affine drift; gaps/reset/contact boundaries; actual MP4 PTS vs encoded CFR; custom time field.
- **Schema:** float/int/bool/string/optional/unknown allowed fields; frame-index retention; unit conversions; explicit role mappings; quaternion xyzw/wxyz/zero/antipodal cases; absent metadata; blank/all-invalid inputs.
- **Data integrity:** identity transformation; change-only-selected-field checks; unchanged source hashes; source/output path overlap and symlinks; interruption before atomic commit; retry/idempotency; double-shift prevention; output tampering after approval.
- **Review:** wrong revision/index rejected; explicit human acceptance; superseding/rejected decisions; interval overlap; screenshot replay metadata; missing chunks/viewer loading handled as incomplete evidence.
- **Storage/publication:** QC/report/format/exclusion changes invalidate plan; approved target unchanged; independent scene/wrist asset failures; canary exclusion; partial recovery; no byte-integrity claim without backend evidence.
- **Training:** training-only statistics; empty/all-excluded/single-frame inputs; split/session leakage; synthetic mask preservation; exact row/frame counts; label boundary behavior; frozen release manifest; loader round-trip and tiny deterministic training smoke.
- **Operations:** Python compatibility matrix; dependency absence; no-network preview; CPU-only/headless rendering; codec variations; bounded result size, memory and timeout; cancellation/resume; credentials/signed URLs absent from logs and RRD metadata.

Pilot on a reviewed corpus containing clean data plus seeded defects, then a representative real dataset. Measure defect precision/recall by rule, false repair rate, percent synthetic/dropped samples, alignment residuals, review time per accepted correction, export reproducibility, peak RAM and p50/p95 job latency. Report dataset size, robot/camera/rate mix and hardware with every result. Do not promise improved policy success from visualization alone; compare downstream training/evaluation under a fixed split and training recipe.

## Boundaries and non-goals

- A schema-valid episode can still contain bad demonstrations, wrong task labels or unsafe actions. Keep semantic QC and task-outcome review separate.
- Rerun supports real RRD transformation, but generic source-format writeback, automatic denoising/calibration, collaborative approval and transactional training releases are not automatically supplied.
- Latest-at queries may carry state indefinitely; `fill_latest_at=True` is not a training-validity policy. Explicit age/gap masks remain mandatory.
- Rerun SDK/Viewer are MIT OR Apache-2.0. Hosted service terms, third-party codec licenses, network/data permissions and authentication remain separate concerns. A local catalog is available; no subscription is required merely to test local queries.
- Do not run arbitrary external data loaders or execute code from dataset metadata. Keep file roots, allowed decoders/operations and worker resources bounded.
- No source data was repaired, training dataset published, VModal asset uploaded, Rerun package installed or live service benchmark run for this documentation task. The source-level probes described above are narrower than a complete test-suite pass.
