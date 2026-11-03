# VModal Robot MCP

Upload robot episodes with user-specified telemetry, retrieve exact mapped timestamps and
frames, search episodes, and export similar-failure candidates for human review. Existing
VModal collection, image, and search tools remain available through the Python SDK.

Use Python 3.10+ in your existing environment, with `ffmpeg` and `ffprobe` on PATH. From this
directory:

```bash
bash install.sh install
export api_key=PUT_API_KEY_HERE
vmodal-mcp-robot run --transport stdio
```

Alternatively register from the checkout with `bash install_mcp.sh codex YOUR_API_KEY`
(also supports claude, cursor, copilot). The robot distribution is `vmodal_mcp_robot`;
its executable is `vmodal-mcp-robot`. The copied generic MCP bootstrap URLs are not used.
Both MCP variants use the historical `src` Python namespace, so install only the intended
variant into an existing interpreter. MCP configuration uses the registered interpreter.

Start by drafting telemetry with `telemetry_format_draft_from_file`, review all `?` values,
then register with `update_json_format_specs_from_file`. Bind a collection and run
`robot_episode_upload(dry_run=true)` before network upload. Local format/check/dry-run tools
work without credentials. Network operations require `api_key`.

See [robot contracts and examples](docs/robot_contract.md), [all tool contracts](docs/tool_contract.md),
[configuration](docs/env_vars.md), and [similar-failure skill](skills/vmodal-robot-similar/SKILL.md).
Telemetry and frame maps remain in the configured local robot directory in Phase A.

Committed samples are in [data/robot](data/robot/README.md). Run all offline tests:

```bash
bash test.sh test
```

The `sdk_mcp_robot_test_release.yml` workflow runs these tests against both the public SDK
and repository SDK, then builds and checks wheel/sdist artifacts. A manual dispatch with
`run_live_tests=true` also runs authenticated SDK, stdio, upload/index/search and full robot
upload/search/retrieval tests using
the same Infisical and Cloudflare pattern as `sdk_mcp_test_release.yml`. This workflow
produces release artifacts; it does not publish to an unspecified public repository.
