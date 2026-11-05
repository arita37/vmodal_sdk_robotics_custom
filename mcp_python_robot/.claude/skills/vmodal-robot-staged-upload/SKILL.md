---
name: vmodal-robot-staged-upload
description: Upload robot episodes to vmodal safely and resumably - offline plan gated on qc-batch verdicts and human-reviewed exclusions, a canary upload to a throwaway collection, the full run with progress lines and stop-on-failures, then server-side verification of collections, camera sub-collections and index state, followed by indexing and a search smoke test. Use whenever robot episodes are to be uploaded or an interrupted upload must be resumed/verified.
---

Turns a risky, manual, token-heavy upload (one MCP call per episode, ~30k tokens each) into four
commands with a gate between each. Uploads publish data to the server, so `canary` and `run`
need `--yes`, and you pass it only after the user approves in this conversation.

## Steps (from the MCP package root, `S=skills/vmodal-robot-staged-upload/scripts/staged_upload.py`)
1. **Gates first:** **vmodal-robot-qc-batch** report for this exact collection + dataset_rev;
   **vmodal-robot-failure-screen** `exclusions.json` from a human review; a bound format
   (approved via **vmodal-robot-format-review**; the plan warns when `checked_by` is not a person).
2. **Plan (offline):** `.venv/bin/python $S plan COLLECTION EPISODES_DIR DATASET_REV OUT_DIR --qc QC/qc_report.json --exclusions exclusions.json`
   Show the user: count to upload, MB, blocked episodes with reasons, format approval state.
3. **Canary (after approval):** `.venv/bin/python $S canary <COLLECTION>_canary EPISODES_DIR DATASET_REV OUT_DIR --uid <smallest passing uid> --yes`
   It must report `uploaded` (or `skipped` when already there) and list `cam_scene`/`cam_wrist`.
   Use the measured seconds to estimate the full run.
4. **Run (after explicit go-ahead on the plan):** `.venv/bin/python $S run COLLECTION EPISODES_DIR DATASET_REV OUT_DIR --plan OUT_DIR/upload_plan.json --yes`
   It refuses if any input changed since the plan. It stops after 3 consecutive failures; re-running
   the same command resumes, and identical uploaded episodes are `skipped`.
5. **Verify:** `.venv/bin/python $S verify COLLECTION OUT_DIR` → manifest status counts vs. server
   collection, sub-collections and index versions. `partial` episodes mean run again.
6. **Index + smoke test (MCP tools):** per camera, `index_create(mode="vid_file", group_name=COLLECTION,
   stream_name="cam_scene" | "cam_wrist", index_type="vid_img_emb", modality="vid_img_emb",
   insert_mode="append", create_index=True, version="new_version")`. Poll `index_status(job_id)`
   until done, then `robot_find(collection_name=COLLECTION, query_text="<task text>", limit=10)` and
   confirm hits map to episodes/frames. Report index versions; never mix versions.
7. Afterwards offer to delete the canary collection (`collection_delete`), but only on request.

## Rules
- One collection = one dataset_rev + one format version. A changed format means a new collection.
- Never upload excluded or non-pass episodes, and never edit `exclusions.json` yourself.
- Report every per-episode line that isn't `uploaded`/`skipped` together with its error.
