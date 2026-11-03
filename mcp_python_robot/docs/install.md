# Robot MCP installation

Use the active Python 3.10+ interpreter. Install `ffmpeg` and `ffprobe` using your platform's
package manager, then from `uinterface/mcp_python_robot` run:

```bash
bash install.sh install
bash install.sh doctor
export api_key=PUT_API_KEY_HERE
vmodal-mcp-robot run --transport stdio
```

No environment is created. Registration from the checkout supports:

```bash
bash install_mcp.sh claude YOUR_API_KEY
bash install_mcp.sh codex YOUR_API_KEY
bash install_mcp.sh cursor YOUR_API_KEY
bash install_mcp.sh copilot YOUR_API_KEY
```

The checkout wrapper installs the robot package; generic `vmodal_mcp` bootstrap URLs install
a different MCP and must not be used for these robot tools. Both variants retain the `src`
namespace, so use the intended variant in your existing interpreter.

`bash install.sh print_codex` and the other `print_*` commands display interpreter-based
configuration. `api_key` authenticates network calls; local registry/check/dry-run tools work
without it. `MCP_ROBOT_DIR` optionally chooses persistent local storage; see [env_vars.md](env_vars.md).

Run `bash test.sh test` for all offline tests. Explicit network suites are `live`, `live_mcp`,
`robot_live` (full robot upload/search/retrieval), and `initial`; the last runs the packaged upload/index/search CLI flow via
`python tests/test_cli.py test3`. The SDK CLI executable is not replaced by this robot package.

For monorepo development, `source env.sh dev` or `source env.sh prd` selects a gateway.
`python utils.py sdk_version_sync --check=true` verifies the minimum SDK requirement against
the sibling SDK; run without `--check=true` only when intentionally updating that requirement.
The robot package version remains independent. Outside the monorepo, installation uses the
declared public SDK dependency and does not require a sibling checkout.

See [robot_examples.md](robot_examples.md) for complete fixture tool calls and
[robot_contract.md](robot_contract.md) for local storage and revision requirements.
