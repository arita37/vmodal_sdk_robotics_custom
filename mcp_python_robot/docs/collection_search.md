# Collection and sub-collection search

Ask the connected assistant:

```text
List all my collections.

List all my sub-collections in a table with Collection and Sub-collection columns.

Find a red car.
Collection: city
Sub-collection:
```

The assistant should call `collection_list`, `collection_subcollections_list`,
and `find` respectively. Both listing tools return structured rows and a Markdown
table. For a filtered table, call
`collection_subcollections_list(collection_name="city")`.

`find(query_text="a red car", collection_name="city")` searches all sub-collections.
For a specific sub-collection, supply its exact listed name:
`find(query_text="a red car", collection_name="city", sub_collection_name="rome")`.
If a collection name exists in multiple modes, specify the listed mode as well.

Leave `version_id` unset. MCP discovers the collection's advertised index versions
and searches newest first. It tries an older version only if the selected revision
has a missing image index or table. A successful query with zero matches is final.
The response includes the selected `version_lancedb` and `available_versions`.
When metadata lists no versions, resolution is delegated to the backend and the
reported version is null.

To intentionally pin an index, use an advertised version, for example
`find(query_text="a red car", collection_name="city", version_id="v2")`.
An unavailable pin returns a validation error with the available versions.
Pinned searches never switch versions automatically.

The existing `search_video` tool remains available with the SDK field names
`group_name`, `stream_name`, and `version_lancedb`. It uses the same version
selection and fallback behavior. `collection_groups_list` still returns the
unmodified SDK metadata response.

Sub-collection discovery uses the SDK account statistics, which inventory raw
assets. A stream containing only an index and no raw assets is not included in
that inventory. Collection discovery uses the separate metadata endpoint.

Both search tools default to 20 rows. `limit=50` returns up to 50 hits in either
compact or verbose mode. Use `offset` for subsequent pages; output reports
`n_total`, `n_total_returned`, `requested_limit`, and `offset`. Compact results
shorten snippets and omit embeddings without imposing another row cap.

For image search, supply exactly one image source, optionally accompanied by text:

```text
find(collection_name="fashion_milan", image_path="/tmp/query.jpg", limit=50)
find(collection_name="fashion_milan", image_url="<VMX signed image URL>")
find(query_text="runway", collection_name="fashion_milan", image_path="/tmp/query.jpg")
```

`image_path` is on the MCP server's filesystem. The server retrieves VMX signed
URLs through the SDK and converts image bytes to plain base64 internally.
`image_query` is available for existing plain base64 input; never pass a URL or
data URI in that field. There is no need to paste image bytes into a conversation.

To save search hits without moving signed URLs between tools:

```text
image_download_from_records(records=find_result.data, root_folder="/tmp/frames")
find(query_text="runway", collection_name="fashion_milan", save_images=5)
```

Direct download accepts 1 to 20 records per call. `save_images` accepts 0 to 20
and saves only available hits. Both retain input order and report each miss or
failure in `results`, plus `n_requested`, `n_saved`, `n_failed`, and `saved_paths`.
Each successful search row in `find(save_images=N)` also has `saved_path`.

Files are actual JPEG images at
`{root}/{collection}/{stream}/{asset_stem}_{13-digit timestamp}.jpg`.
For `Look 01.mp4` in `fashion_milan/runway` at `1735689600123`, the example root
produces `/tmp/frames/fashion_milan/runway/Look_01_1735689600123.jpg`.
The default root is the server's existing `MCP_IMAGE_DIR`; paths and `output_dir`
are absolute. Missing asset names or streams remain visible as
`frame_fetchable=false` with `frame_error`. They cannot be repaired by guessing
from a title or collection name. Name collisions return `path_conflict`.
