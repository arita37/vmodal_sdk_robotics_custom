# vmodal-find reference

## Tools used

| Step | Tool | Notes |
|---|---|---|
| list collections | `collection_list()` | collection, mode, index versions |
| list sub-collections | `collection_subcollections_list(collection_name="city")` | exact `sub_collection_name` values |
| search | `find(query_text, collection_name, sub_collection_name="", limit=20)` | blank sub-collection = all; omit `mode` and `version_id` |
| frame URLs | `image_get_url_bulk(records=[hit, ...])` | pass search rows as-is |
| download | `image_get_bulk_from_urls(urls=[...], collection_name="city")` | returns `output_dir`, `saved_paths` |
| convert | `bash <skill_dir>/scripts/frames_to_png.sh <out_dir> <path>...` | WebP → PNG for the Read tool |

Older MCP builds have no `find`. Fall back to
`search_video(group_name=..., stream_name=..., query_text=..., limit=20)` and tell the user
to upgrade, since old builds pin `version_lancedb=0` instead of the newest index.

Use an output dir outside the repo for PNGs, e.g. `${TMPDIR:-/tmp}/vmodal-find/<collection>`.
Don't browse `ztmp/` yourself; only pass the returned saved paths to the script.

## Hit fields

A hit's frame is identified by `mode`, `group_name` (collection), `stream_name`
(sub-collection), `modality` (`vid_img`), `filename` (video) and `ts_unix_13digits`.

## Timestamps

`ts_unix_13digits` is milliseconds, zero-padded to 13 digits.

- Value below 1e12: an offset into the video. `0000000117083` → 117083 ms → **1:57**.
  `0000001178577` → 1178.6 s → **19:38**. Use `h:mm:ss` from 1 hour up.
- Value at or above 1e12: a real Unix time in ms (live or recorded streams). Show it as a
  UTC date and time, e.g. `2026-10-01 08:57:22 UTC`.

Scene gap: hits in the same video ≤ 3000 ms apart from the previous hit belong to one scene.

## Verdict rules (summary)

| Verdict | Core | Attribute / context | Subjective | Unverifiable |
|---|---|---|---|---|
| PASS | pass | all pass | ignored (used to order) | listed in footer |
| PARTIAL | pass | ≥ 1 fail or unclear after second look | ignored | listed in footer |
| FAIL | fail | — | — | — |

Budgets: 8 scenes per round; widen while PASS < 3; stop at 24 scenes viewed.

## Worked example

Request: `red taxi with a white roof, parked, at night. Collection: city`

1. Checklist: `red` (attribute) · `taxi` (core) · `white roof` (attribute) · `parked` (attribute) · `night` (context).
2. `find("red taxi with a white roof, parked, at night", "city", limit=20)` and `find("a taxi", "city", limit=20)`.
3. Hits at 1:54, 1:55, 1:57 and 1:58 in the Kyoto video → one scene, 1:54–1:58, representative 1:57.
4. Frame at 1:57: red taxi ✓, white roof ✓, parked at a taxi stand ✓, sky is pale blue at dusk ✗ night.
5. Verdict: **PARTIAL**, Missed: "dusk, not night". It goes in the "Close, but not matching" table.
