# MCP Environment Variables

Network `vmodal_mcp_robot` configuration requires `api_key`; local robot checks and dry runs
work without it. With no
private profile loaded, the server uses the SDK's `prd` gateway default.

Additional MCP variables:

| Variable | Meaning | Default |
| --- | --- | --- |
| `MCP_IMAGE_DIR` | Directory where image payloads are written | `ztmp/mcp_images` |
| `MCP_TRANSPORT` | `stdio` (default) or `http` | `stdio` |
| `MCP_UPLOAD_MAX_MB` | Local upload path size cap in MB | `5120` |
| `MCP_TOOL_TIMEOUT` | Outer per-tool timeout (seconds). Overrides derived value. | derived (see below) |
| `MCP_IMAGE_MAX_FILES` | Max files kept in `MCP_IMAGE_DIR`; oldest pruned at startup | `500` |

`MCP_TOOL_TIMEOUT` derivation: when unset, it is derived from the SDK network
budget as `VMODAL_TIMEOUT * (VMODAL_MAX_RETRIES + 1) + 10` seconds. This gives
the SDK its full retry budget plus a 10s margin before the MCP layer's outer
guard fires (`error_type="Timeout"`, `status_code=504`). Set `MCP_TOOL_TIMEOUT`
explicitly only to override this derived value.

`MCP_TOOL_TIMEOUT` applies to ordinary tools. Video upload and bulk-video upload
delegate timeout, retry, and resume control to the SDK so a healthy large-file
transfer is not cancelled by the MCP outer timeout.

Public authentication:

- Set `api_key` in the MCP client environment. It is sent as the Bearer token.
- For the `vmodal` CLI, `VMODAL_API_KEY` is also accepted and is the preferred
  shell variable.
- At startup, the MCP server resolves and caches the token owner through
  `/api/v1/auth/me` so SDK requests include the required user identity headers.
- Do not pass `user_id` in MCP tool inputs. In gateway mode, `users_api`
  resolves identity from the Bearer token and injects trusted downstream user
  headers.

Private repository developers can select the local gateway before starting the
server:

```bash
source env.sh dev
```

The private `env.sh` is excluded from public releases. Public installations do
not need it and continue to default to `prd`.
# Robot artifact configuration

`MCP_ROBOT_DIR` defaults to `mcp_robot` beside `MCP_IMAGE_DIR` (normally `ztmp/mcp_robot`).
It holds immutable format versions, collection bindings, episode manifests, reports, clips,
telemetry and frame maps. `env.sh` centralizes the derived default for dev/prd. Preserve it
between sessions: the backend does not yet serve these Phase A sidecars. `ffmpeg`/`ffprobe`
must be on PATH for checks, LeRobot clipping and exact local frame retrieval.
