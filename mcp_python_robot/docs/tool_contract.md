## MCP Tool Contract

`uinterface/mcp_python_robot` mirrors the active `uinterface/sdk_python` client surface
and composes the robot helpers documented below.

External search API tools mirror `vmodal.routes.ACTIVE_ENDPOINTS`, excluding the SDK-only
`auth.auth_check` helper. The MCP registry also exposes SDK helpers that are not single
route constants:

- `collection_video_upload`: signed local video or image upload flow. Its input
  schema is generated from the installed `vmodal` SDK, so newer SDK releases
  automatically expose adaptive network hints and optional `reduce_size=true`
  360-pixel MP4 conversion without breaking older compatible releases.
- `collection_video_upload_bulk`: signed local MP4 folder upload flow.
- `collection_list`: wraps `collections.list_groups` to return every collection,
  mode, and advertised index version, with a Markdown `table` and structured `data`.
- `collection_subcollections_list`: wraps `admin.user_stats` to return deduplicated
  `collection_name` / `sub_collection_name` / `mode` rows and a Markdown table.
  An empty collection filter includes every collection. Optional `mode` and
  `collection_name` filters are applied in MCP, not forwarded to the SDK stats method.
  This is the SDK raw-asset inventory; streams without raw assets are not inventoried.
- `find`: wraps `searches.search_video` with text and/or one image input,
  `collection_name`, and optional `sub_collection_name`. Blank sub-collection searches every stream.
  It infers mode from collection metadata; if the same name exists in several
  modes, callers must specify `mode`.

`find` requires nonblank `query_text`, exactly one image source, or text plus one
image source. `image_query` contains plain base64 image bytes without a data URI
prefix; `image_path` names a file on the MCP server; `image_url` is a VMX signed
image URL. The server reads/fetches and validates the selected image, then passes
plain base64 in the SDK `image_query` field. Never put a URL in `image_query` or
copy image bytes into the conversation. Multiple image sources, empty or malformed
images, and unreadable files return JSON `ValidationError` status 422. Signed URL
errors preserve the SDK status/detail. Image bytes are absent from outputs/logs.

`image_download_from_records(records, root_folder=None)` accepts 1 to 20 unchanged
search records. It signs valid selectors with `images.get_url_bulk`, matches replies
by `input_index`, then retrieves each image with `images.get_image_from_url`.
More than 20 records returns 422 before retrieval; submit subsequent batches
separately. Every input has an ordered `results` entry containing `input_index`,
`found`, `saved_path`, and `error`. Success has `found=true` and an empty error;
failure has an empty saved path and a short error string or an SDK error object.
The result also includes ordered successful `saved_paths`, `n_requested`,
`n_saved`, `n_failed`, and absolute `output_dir`. Signed URLs are not returned.

All saved frames use this exact path:
`{root_folder}/{collection_name}/{stream_name}/{filename_clean}_{TS13digits}.jpg`.
The timestamp is exactly 13 digits with no literal `TS` prefix. The filename is
the original asset basename without its final extension; unsupported characters
in the stem and directory components become `_`. Empty components and invalid
timestamps fail. Paths remain inside the absolute resolved root, which defaults
to existing `MCP_IMAGE_DIR` / `cfg.image_dir`; there is no date directory.
Pillow converts WebP/PNG/GIF frames to real JPEG, compositing transparency on
white. Invalid images write no JPEG. Duplicate selectors may share a path;
different selectors that collide return `path_conflict`. A `.jpg.json` selector
sidecar prevents collisions across calls without adding hashes to filenames.

`find(save_images=N)` (0 to 20) uses the same helper for the first N available
hits, preserves failed hits, adds the same summary and per-record `results`, and
adds each successful row's absolute `saved_path`. Counts report actual outcomes.

A version whose search fails with 404/500 "missing index" or "Unable to resolve
query embedding model" is treated as unusable and the next older advertised
version is tried.

The MCP initialization instructions route ordinary listing and Find prompts to
these three tools. Assistants should display the returned sub-collection table
and omit index versions unless the user explicitly requests a pin.

Users API tools mirror recent SDK additions that resolve identity from the Bearer token:

- `auth_me`
- `admin_usage`
- `admin_cache_stats`
- `r2_credentials`
- `r2_presign_upload_file`
- `r2_presign_upload_folder_video`

Validation is enforced by `tests/test_main_mcp.py::test9`, which compares registry targets
against SDK route constants plus these users-api and SDK-helper targets.

Input-schema parity is checked in `tests/test_main_mcp.py::test3`. MCP exposes
signed-upload modality, preserves required description-update fields, accepts
`mode=null` for an unfiltered group listing, and accepts either an integer
or string image timestamp. The deliberate MCP differences are local uploads by filesystem
path instead of file objects and removal of `user_id`/`userid` because identity comes from
the configured token.

Search deliberately has safer MCP-facing defaults than the shared SDK. A caller
must provide a non-empty `group_name`; omitting `mode` (or passing `null`) infers
the collection mode, and omitting `stream_name` searches every stream,
`search_sources` is fixed to `["image"]`, `version_lancedb` defaults to `null`, and
`limit` defaults to 20. Both `search_video` and `find` fetch current collection
metadata for each search and try advertised `lancedb_versions` in descending
numeric order. They retry an older version only after an API 404/500 that identifies
a missing image/LanceDB index or table. Empty results, authentication errors, and
other failures never trigger a version retry. Discovery and all attempts share
one MCP timeout budget. When metadata advertises no versions, MCP leaves the
version unset and lets the backend resolve it; it never invents version 0.

Explicit `search_video.version_lancedb` integers and `find.version_id` values
(integers or tags such as `v2`) remain pinned. If metadata advertises versions
and the pin is absent from that list, MCP returns 422 with `available_versions`
before searching. Search output reports `version_lancedb` and `available_versions`;
a null version means resolution was delegated to the backend.
Missing-index errors include `available_versions` and `attempted_versions` so
callers can see which revisions failed.

Example tool calls:

```text
collection_list()
collection_subcollections_list()
collection_subcollections_list(collection_name="city")
find(query_text="a red car", collection_name="city")
find(query_text="a red car", collection_name="city", sub_collection_name="rome")
```

Use the exact names returned by the listing tools. Omit `version_id` for ordinary
queries; versions are collection-specific and must not be copied from another collection.

Example user prompts (no version or mode required):

```text
List all collections

List all sub-collections:
  - show in tabular format
  - Collection | Sub-collection

Find a red car parked on a street
Collection: city
Sub-collection:
```

Compact search hits contain the canonical frame selector fields `mode`,
`group_name`, `stream_name`, `modality`, `filename`, and `ts_unix_13digits`, plus
the compatibility keys `score`, `source_path`, `ts_unix`, and `text_snippet`.
Search aliases such as `filename_sanitized`, `file_name`, `stream`, and `ts_unix`
are normalized at the MCP boundary. Editable `title` and opaque frame paths are
never guessed to be original asset filenames. Hits with incomplete selectors
remain visible with `frame_fetchable=false` and `frame_error` (for example
`missing_filename`, `missing_stream`, or `invalid_timestamp`). The canonical retrieval modality is `vid_img`, even though search uses
an image-embedding index. `verbose=true` retains raw hit metadata and overlays the
canonical fields.

Both search tools default to `limit=20` and `offset=0`. Compact and verbose output
retain up to the requested limit in SDK order, with no additional 20-row cap.
`n_total` is the backend total, `n_total_returned=len(data)`, `requested_limit`
is the requested page size, and `offset` is the page start. `trimmed=true` means
compact fields and snippets shortened to 200 characters, never row truncation.
Ordinary pagination does not imply a cap. No separate MCP search cap is imposed.

Rows from `search_video.data` can be passed directly as
`image_get_url_bulk(records=...)`. Bulk lookup strips search-only fields, converts
`img_emb` and `vid_img_emb` to the stored-frame modality `vid_img`, and rejects a
record with a missing mode, group, concrete stream, modality, or filename before
calling the SDK. It never turns an empty frame stream into `astream`.

The URL-only download inputs have changed: `image_get_from_url` now requires
`url_pre_signed` plus a `record`; `image_get_bulk_from_urls` requires 1 to 20
`urls` and aligned `records` of the same length. Both accept `root_folder` and
return the same download summary (including a one-entry `results` for single
downloads). Missing metadata or mismatched lengths returns 422. An opaque URL
cannot supply the original asset, collection, stream, or timestamp. Prefer
`image_download_from_records` to avoid copying URLs between tools.

The single-video schema is generated from `CollectionsResource.video_upload` in
the installed SDK. Current repository SDK controls include `multipart`,
`multipart_threshold_bytes`, `part_size_bytes`, `max_concurrency`,
`max_part_attempts`, `part_timeout_seconds`, `resume`, `network_mbps`, and
`reduce_size`; older compatible SDK releases expose their supported subset and
defaults. Video upload tools are marked long-running and are not wrapped by
the ordinary MCP outer timeout; the SDK retains bounded per-part timeouts,
adaptive tuning, retry, checkpoint reconciliation, and resume behavior.
# Robot episode tools

The robot-specific helper contract, immutable format registration, upload reports, search
hit/time mapping, retrieval and tag/review schemas are in [robot_contract.md](robot_contract.md).
See [robot_examples.md](robot_examples.md) for complete sample tool calls. New tools:
`telemetry_format_draft_from_file`, `update_json_format_specs_from_file`,
`telemetry_format_list`, `telemetry_format_check`, `robot_episode_upload`,
`robot_dataset_upload`, `robot_manifest_build`, `robot_find`, `robot_retrieve`.
They compose the existing Python SDK; they introduce no API routes. Local checks and dry
runs require no API key. Network calls retain the existing SDK authentication contract.
