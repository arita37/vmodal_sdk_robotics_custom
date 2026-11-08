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

## Local format registry: why a demo format may already exist

The registry is local to the MCP **server process**, not your API key or remote
account. Relative paths are resolved from that process's working directory. With
`mcp_python_robot` as the working directory and the default image directory, the
registry is `mcp_python_robot/ztmp/mcp_robot` in the checkout. Set an absolute
`MCP_ROBOT_DIR` in the client's server environment to make the location independent
of how the client launches it. Changing this variable in an unrelated terminal does
not change an already-running server; configure the client and restart/reconnect it.

The checkout includes historical demo artifacts under `ztmp/mcp_robot`:

- `formats/xarm6_gripper_100hz/v1.json`: a previously registered synthetic spec.
- `formats/index.json`: its SHA256 and reviewer/registration provenance. The
  bundled entry records `checked_by=synthetic_fixture`, `checked_at=2026-11-03`,
  and `registered_at=2026-11-04T03:01:06.090310+00:00`.
- `robot_demo/collection.json`: the local `xarm6_gripper_100hz@1` binding.

These tracked files can therefore be present immediately after cloning, before you
register anything. A previous run in the same directory can also leave registrations.
This explains how a review can truthfully say it registered nothing while a later
upload dry run uses an existing v1. The testing report alone does not establish which
server working directory was used; inspect the active directory rather than assuming
all clients share the checkout's registry.

The installer smoke test only drafts a format. Neither drafting nor the format-review
script registers it. Explicit `update_json_format_specs_from_file` calls write the
registry and optional local collection binding; `dry_run=true` on that registration
call writes neither. `robot_episode_upload(dry_run=true)` instead reads an existing
registration and may write episode/check artifacts. It does not automatically register
the bundled source spec or create a remote collection.

Inspect registrations through your connected MCP client:

```json
{
  "tool": "telemetry_format_list",
  "arguments": {"format_id": "xarm6_gripper_100hz"}
}
```

The result includes version provenance and local collection bindings. To investigate
an unexpected result, compare those with `formats/index.json`, the versioned JSON,
and `robot_demo/collection.json` under the **active** `MCP_ROBOT_DIR`. The source
`data/robot/xarm6_gripper_100hz.format.json` is a registration input, not the live
registry. Editing or updating that source does not alter an existing registration.

### Start a fresh demo without deleting existing state

1. Create a separate, private directory on the machine running the server, for example
   `mktemp -d "${TMPDIR:-/tmp}/vmodal-robot-demo.XXXXXX"`. Copy the returned absolute
   path into the MCP client's server environment as `MCP_ROBOT_DIR`, then reconnect.
   Keep the printed path for subsequent calls. Temporary directories may be cleaned
   by the OS; use a dedicated persistent directory for work you need to retain.
2. Call `telemetry_format_list`. An empty directory should return empty `formats`
   and `bindings`. If not, check the client's environment and server working directory.
3. Explicitly register the supplied synthetic format using the call below. Use an
   absolute source path on the server. `sample_path` is deliberately omitted: the
   bundled telemetry contains planted defects, so it is not a clean registration
   acceptance sample. Registration validates the spec; check the episodes separately.
4. Call `telemetry_format_list` again and confirm the returned version, SHA256,
   reviewer fields and `robot_demo` binding before running checks/dry runs. A successful
   registration is not a passing episode verdict or production approval.

```json
{
  "tool": "update_json_format_specs_from_file",
  "arguments": {
    "path": "/absolute/path/to/vmodal-robot/mcp_python_robot/data/robot/xarm6_gripper_100hz.format.json",
    "collection_name": "robot_demo",
    "dry_run": false
  }
}
```

Versioned registrations are immutable. Re-registering identical canonical JSON returns
`status=unchanged`; changed content at the same id/version returns HTTP 409. In
particular, a newer bundled fixture may conflict with the historical cached v1.
Use the isolated directory above for a clean demo. For an ongoing dataset, review and
register a new format version and deliberately rebind future uploads; reconcile any
telemetry header version/hash with that spec. Do not overwrite or delete cached versions
to silence the conflict: older episodes depend on them. Preserve the original directory
and reconnect with its original setting when returning to existing work.
