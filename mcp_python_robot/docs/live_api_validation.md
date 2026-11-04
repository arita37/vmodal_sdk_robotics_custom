# Live robot MCP validation — 2026-11-03

All four local authenticated suites passed using the existing configured test API key:

| Command | Result | Evidence |
| --- | --- | --- |
| `bash test.sh live` | PASS | SDK health, collection inventory and search |
| `bash test.sh live_mcp` | PASS | Actual stdio handshake, 37 tools, discovery, search and downloaded frames |
| `bash test.sh initial` | PASS | New collection `mcp_test_09002165`, successful job `70013081aaa94cb793b0c575e5efbc28`, 20 indexed frames and search hits |
| `bash test.sh robot_live` | PASS after fix | New collection `mcp_robot_live_20261103_123239_456971`, successful job `f561dacb4ed14c34b9aa8f0ea94e9630`, index version 0 and a mapped hit with images and telemetry |

The robot suite registers the synthetic format, checks and uploads both cameras plus metadata,
creates the scene index, searches via `robot_find`, and calls `robot_retrieve` through a real
MCP stdio session. It requires the scene image to come from `vmodal_index`, verifies wrist
fallback, integer timestamps, revision/index provenance and telemetry rows. Missing credentials,
failed jobs or missing indexed images fail the suite rather than skip it.

The first robot run exposed a selector bug: search returned `filename=ep_demo1`, but retrieval
changed it to `ep_demo1.mp4`, causing the indexed image lookup to miss. Retrieval now preserves
the exact returned filename; explicit local points use the episode stem. The offline regression
asserts the extensionless selector is unchanged. The complete robot live suite then passed.

The historical workflow described below is not included in this checkout and cannot be
dispatched here. Use the explicit `test.sh` commands above for local validation.

At the time of this record, the workflow was published from an isolated checkout based on
GitHub `origin/dev`, keeping
the original diverged local branch and unrelated files unchanged. Workflow dispatch enables
`run_live_tests=true` and includes all four suites. The customer M2 recall study still requires
the real episode dataset; these synthetic fixtures validate contracts and handoff behavior.

The first GitHub attempt stopped on two documentation placeholders (`YOUR_API_KEY`). Both
examples now use the existing explicit `PUT_API_KEY_HERE` convention. The scanner remains
enabled and its rules were not relaxed.

The next GitHub attempt passed its scan and all offline/public-SDK/repository-SDK suites,
source/wheel checks and the first three live suites. The robot check then exposed missing
`ffprobe` on the separate live runner. The live job now installs FFmpeg (including ffprobe)
explicitly, matching the offline job's video dependency setup.
