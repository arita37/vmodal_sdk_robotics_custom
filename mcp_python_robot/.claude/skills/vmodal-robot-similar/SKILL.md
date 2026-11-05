---
name: vmodal-robot-similar
description: Find robot episodes with failures similar to an anchor or text query, verify scene and wrist frames, and export unreviewed candidate tags for human review.
---

Use the robot MCP tools with vmodal-find and vmodal-incident. Read [reference.md](reference.md)
for detector requirements and thresholds. Customer MCAP/LeRobot data remains authoritative.

1. Identify the collection and dataset revision. Anchor on an episode/time, frame image,
   catalog failure type, or free text. Exclude correction episodes from anchors unless requested.
   For episode/time anchors call `robot_retrieve` for scene and wrist views plus telemetry.
   Show a signature with 2–4 visible facts and the catalog telemetry rule before searching.
2. Search scene image, wrist image, catalog phrases, and a user-phrased query with
   `robot_find(limit=50,max_pages=10)`. These independent searches may run concurrently.
   Record the query ids, index versions and `n_scanned/n_total`; never fuse different versions.
3. From the MCP package root, with its Python environment and `PYTHONPATH` set, run:
   `python skills/vmodal-robot-similar/scripts/telemetry_scan.py COLLECTION grasp_miss scan.json`.
   Scan all local telemetry independently of indexed-frame availability. Report skipped specs.
   Gaps are masked even for flagged episodes. Read thresholds from a per-robot JSON file when
   supplied; report the detector version and thresholds used.
4. Use `telemetry_sig.py` for named-field, fixed-length signatures. Its input JSON contains
   `anchor`, `candidates` (lists of telemetry rows), `spec`, `fields` (e.g. `current.j2`), and
   optional `searches` and `telemetry_hits` for fusion. Scanned-set standard deviations normalize
   field distances; windows crossing gaps are rejected. Fuse reciprocal ranks, merging windows
   separated by at most 3 seconds with a maximum span of 15 seconds. Keep visual relevance,
   signature distance, and detector confidence as separate evidence.
5. Triage batches of ten. Retrieve the peak scene/wrist frames, use the existing
   `vmodal-incident/scripts/frames_strip.sh` contact-sheet helper, and assign PASS/PARTIAL/FAIL
   using the catalog visual rule. Stop after two consecutive batches with no new PASS or
   after 40 candidates. State the stopping rule.
6. Save triaged candidates as JSON with `verdict`, `episode_uid`, half-open integer
   `t_start_ns/t_end_ns`, `dataset_rev`, `index_version`, `relevance`, optional `detector` and
   `confidence`. Run `tags_write.py candidates PATH TAG INDEX_VERSION QUERY_ID OUT`.
   PASS/PARTIAL become `source=auto,review_status=unreviewed`; FAIL is omitted. Confidence
   stays null without a versioned detector. Never delete/exclude episodes or write accepted tags.
7. Report anchor/signature, searches, coverage, episode/window/verdict/relevance/detector table,
   contact sheets and tag file paths. Explain that the reviewer must accept/reject/correct and
   freeze a `tag_rev` snapshot before training filters consume tags.

For text-only batch tagging, omit anchor retrieval and use `min_relevance` on the candidate
writer; visual triage remains required. For explicit human review, create a decisions JSON
array of `tag_id,review_status` and optional corrected `tag`, then run
`tags_write.py review TAGS_JSONL DECISIONS_JSON REVIEWER OUT QUERY_ID`. This writes new human
rows with `supersedes`; preserve the original candidate file. Do not invent reviewer decisions.
