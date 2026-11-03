# Robot episode contract

Implemented package scope: P0–P5 of [the VLA draft](vla_train/01_doc.md). Server changes in P6,
customer M2 data collection, and real-data quality evaluation remain external work.

## Identity and time

Use one collection per `dataset_rev`. `episode_uid` contains ASCII letters, digits and single
underscores; repeated underscores and characters changed by the backend sanitizer are rejected.
Upload selectors use `{episode_uid}.mp4`, camera sub-collections `cam_scene`/`cam_wrist`, no
`start_datetime_user`, no SDK size reduction, and decoded 30/1 CFR clips. Counts must equal
the frame-map rows and declared episode length. A changed start/count/revision is a conflict.

Customer frame maps are authoritative: `frame_index` is contiguous from zero; `t_scene_ns`
and `t_wrist_ns` are integer nanoseconds, with `wrist_dt_ms` and `wrist_repeated` supplied.
`t_scene_ns` strictly increases. Camera clips must already be row-aligned; LeRobot v3 clips
are cut/re-encoded from the episode table offsets rather than copied at keyframes.

Resolve a hit with `round(offset_ms*30/1000)` then look up its actual frame-map timestamp.
Never compute `t0+offset`. For image selectors replicate the backend float expression
`int((frame_index/30)*1000)` and pad to 13 digits (frame 969 gives 32299 ms). Epoch offsets,
booleans and 19-digit nanoseconds are invalid selectors. Explicit `t_ns` chooses the nearest
frame within 16.7 ms; otherwise retrieval returns `no_frame`. JSON and Arrow readers retain
int64 values without passing through pandas/float.

## Formats and validation

`telemetry_format_draft_from_file(path,output_path)` infers names/shapes/rate; unknown units,
ranges, alignment policy and reviewer fields remain `?`. Fill and check them before calling
`update_json_format_specs_from_file(path,collection_name,sample_path,dry_run)`.
Registration requires unique named fields, dtype/shape/units, reviewed provenance, explicit
time/sampling/alignment settings, and no `?` anywhere. Versioned specs are immutable; changing
content under the same id/version returns 409. A new version can rebind later uploads without
changing the spec used by previous episodes. Registration dry runs write nothing.

Specs live at `formats/{format_id}/v{version}.json`; canonical sorted compact JSON determines
SHA256. `formats/index.json` records provenance, and `{collection}/collection.json` holds a
`format_id@version` binding. Explicit format selection must also include `@version`.

Input supports JSON arrays, `{header,rows}` JSON, JSONL, gzip JSONL and Parquet. Input headers
may omit details, but supplied names/sub-names/units/id/version/hash cannot contradict the
registered spec. The legacy `schema` key aliases `format_id`; it does not alias arbitrary
different format names. The original `data/v1/telemetry.jsonl` uses `vmodal_robot_telemetry/1`
while `input_spec.json` uses `xarm6_gripper_100hz`: the user must reconcile that mismatch before
registering the original sample. The runnable synthetic samples already use matching ids.

Validation checks file/dtype/shape/ranges/finite values, strict timestamp ordering, median
rate, gaps, decoded video frames/CFR, coverage, nearest state and latest preceding command age.
Time gaps are explicit half-open masked spans, never interpolated. Missing frame rows or
malformed data/video always reject, even if `on_fail=flag`; flag applies only to quality
limits (rate, gaps and alignment) on otherwise valid artifacts. This preserves usable identity
and prevents corrupt rows from entering canonical storage.

`telemetry_format_check` runs standalone checks; omit frame/video inputs for file/time checks.
Frame-mode rows may omit timestamps: complete frame-map checks supply them only from the
map; a check without a map reports that timestamp alignment is deferred.
Episode uploads always perform the complete check before any SDK network calls. Reports are
available under `{collection}/checks/{uid}.json` and the episode's immutable artifact folder.
Per-frame indexes record nearest telemetry and preceding command rows, deltas and missingness.

## Upload and local storage

`robot_episode_upload` takes collection, uid, scene/wrist clips, telemetry, frame map, metadata,
revision, optional format, and `dry_run`. `robot_dataset_upload` reads LeRobot v3
`meta/info.json` and `meta/episodes/**/*.parquet`; frame-map `episode_index` maps to the stable
uid. Telemetry files are `{telemetry_dir}/{uid}.{jsonl,jsonl.gz,json,parquet}`; metadata files
are `{meta_dir}/{uid}.json`. Per-camera episode table keys follow
`videos/observation.images.cam_scene/{chunk_index,file_index,from_timestamp,to_timestamp}`.
An optional `episodes` uid list and positive `limit` select a subset.

Canonical telemetry is gzip JSONL with `format_id,format_version,format_sha256,episode_uid`
in its first line. Frame maps, telemetry, metadata, checks and frame indexes remain local in
Phase A. Artifact directories are content-addressed; dry runs cannot replace data referenced
by an already uploaded episode. Runtime defaults derive from `MCP_IMAGE_DIR`'s parent:
`MCP_ROBOT_DIR=ztmp/mcp_robot`. Preserve this directory to retrieve from another session.

The manifest records sync metrics, format identity, local paths, revision, input fingerprint,
and `info_json_sha256` over custom metadata (excluding video/title/description/duration and
the checksum itself),
and status. Dry run writes `validated` entries and planned upload lists without network calls.
Live handoff records `partial` before uploading either clip, then sends one metadata row per
camera using existing SDK `video_upload`/`upload_metadata_jsonl`. Only success of every step
marks `uploaded`. Partial episodes are hidden from robot search/retrieval until retried.
Already uploaded identical content is skipped; failed partial handoffs retry.

The backend offers no multi-asset transaction: clips can temporarily exist remotely after a
partial failure. The local manifest is the completion gate; no remote rollback is claimed.
`robot_manifest_build` reconstructs the manifest from preserved local episode records. It
cannot infer historical upload success from raw customer files alone.

## Retrieval and search

`robot_retrieve` accepts 1–20 robot/VModal records or an explicit uid/time. Pass robot hit
wrappers unchanged to preserve `dataset_rev/index_version`; raw VModal records additionally
require the originating `index_version` argument. Explicit local points have a
null index version because they do not originate from an index. `image_source` selects
`vmodal_index`, `local_decode`, or index-first `auto` with local fallback. The response has
images, per-camera sources, actual frame times, wrist flags, sync metrics, telemetry format,
half-open window rows, named state and summary. Nearest state requires <=10 ms, and command
state uses the preceding command row from the stored frame index. Downsampling selects
existing samples per continuous segment, preserving gaps. Summaries use the full window.

Each image gets a `.json` result sidecar. Indexed JPEG `.jpg.json` selector ownership files
remain intact. Mixed fallback is reported as `image_source=mixed` plus `image_sources`.

`robot_find` composes the existing find tool, pins its first resolved index version across
pages, maps filenames through the manifest and filters robot/operator/task/success/date and
maximum sync offset. Unknown filters reject. It returns raw selectors unchanged, versioned
robot hits, half-second windows around hit times, episode counts and merged windows (gap<=3 s,
span<=15 s). `n_scanned`, `n_total`, `n_unmapped` and `page_cap_reached` expose search coverage;
server-side metadata filters are still a P6 follow-up. Do not compare ranks across versions.

## Similar failures and review

The [skill](../skills/vmodal-robot-similar/SKILL.md) combines scene/wrist/text searches and local
versioned telemetry detectors. Fields, sub-names, units and command roles are checked before
scanning; unsupported episodes are reported. Gaps split detector sequences. The normalized
gripper is 0=open/1=closed: a drop's opening signal decreases. Signature distances use named
scalars, nearest-sample fixed-length windows and pooled scanned-set standard deviations.
Reciprocal ranks fuse searches and telemetry distances; detector confidence stays separate.

Candidate writer inputs require a visually triaged PASS/PARTIAL, integer time bounds,
revision/index version and relevance. C8 exports contain tag id, uid, half-open bounds, tag,
source, tagger/version, relevance, optional detector confidence, review status, supersedes,
creation time and revision/index provenance. JSONL and Parquet preserve nanoseconds. Writers
create new files and refuse to overwrite. Auto rows always remain `unreviewed`; human review
exports require explicit decisions/reviewer and create new rows with `supersedes`. Freeze a
reviewed tag snapshot before any training filter; these tools never remove dataset episodes.

## Verification

`bash test.sh test` runs every offline test suite, including robot formats, upload/resume,
LeRobot cuts, time conversion, retrieval, search pagination, planted events, signatures, tags,
MCP schemas/stdio and the existing trend-radar tests. `bash test.sh live`, `live_mcp`, and
`initial` are explicit authenticated network suites and fail on missing configuration.
`bash test.sh robot_live` additionally exercises registered-format dry run/upload, metadata,
index creation, robot search and indexed scene-image plus telemetry retrieval through stdio.
Search filenames are preserved exactly when constructing image selectors; the backend can
return a stem without the raw clip's `.mp4` extension.
CI tests public/repository SDKs and builds checked release artifacts. No public destination
is assumed. Real M2 ~100-episode recall/quality evaluation requires the customer's dataset.
