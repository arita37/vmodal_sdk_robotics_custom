# MCP robot: episode-level dataset search and curation features

Date: 2026-11-03
Version: 0.1 (feature proposal, not built)
Input: `docs/vla_train/01_new_dataset.md` (Encord, "How to Curate Robot Episode Data at Scale",
2026-08-20), `docs/vla_train/00_doc.md` (Casey Clark M1 data stack), `docs/vla_train/01_doc.md`
(robot MCP plan v0.2), `docs/implementation_vla.md` (P0-P5 delivered).

Labels: **Exists** = in `mcp_python_robot` today. **New** = proposed here.
**Backend** = needs a server change outside this package. **Open** = to agree with the user.


## User Input Specs:

1. Deep read of `01_new_dataset.md`: curation is a cross-episode decision layer above labeling.
   It decides which episodes deserve a seat at training time.
2. Write the new features that improve video dataset search and curation with VModal MCP.

Article claims used as requirements:
- More episodes is not always better; redundant or low-quality demos can hurt a VLA policy.
- Six failure patterns: redundant demos, vague/missing task text, missing sub-task segmentation,
  object misclassification, cross-embodiment inconsistency, failed/partial episodes left in.
- Five pipeline steps: (1) dedup + redundancy, (2) quality scoring, (3) failed/ambiguous
  filtering, (4) cross-embodiment normalization, (5) flywheel routing back to curation.
- Past a few thousand episodes, manual review breaks. Embedding search + automated scoring
  become mandatory, and humans review only flagged cases.
- Teams need queries like "every episode similar to this one" and "the rarest scenarios".


------------------------------------------------------------------------
## Scope:

- `uinterface/mcp_python_robot/src/mcp_server/curate/` : New subpackage, one module per feature.
- `uinterface/mcp_python_robot/src/mcp_server/registry.py`, `main_mcp.py` : register new tools.
- `uinterface/mcp_python_robot/skills/vmodal-robot-curate/` : New skill for the curation run.
- `uinterface/mcp_python_robot/skills/vmodal-robot-similar/reference.md` : add phase and outcome rules.
- `uinterface/mcp_python_robot/tests/`, `data/robot/` : fixtures + tests.
- `uinterface/mcp_python_robot/docs/robot_contract.md` : D0-D10 contracts.

Not changed: `sdk_python` API contract, the existing C1-C9 contracts from `01_doc.md`, or the
customer's Flow 2 (DuckDB filter on a frozen tag snapshot). Every feature here produces
proposals and evidence. Datasets, revisions and the customer `tags/tags.parquet` are never mutated.


## Gap map: article step -> what exists -> what is missing

- Step 1, dedup/redundancy -> Exists: `robot_find` image search, `signature_distances`
  (anchor vs candidates) -> Missing: an all-episode neighbor graph, near-duplicate clusters,
  and a redundancy cap. Today the user can only ask "like this one" for one anchor at a time.
- Step 2, quality scoring -> Exists: C2c check report and C4 sync fields per episode ->
  Missing: a per-episode quality vector (smoothness, idle, retries, tracking error, video
  quality) ranked within the task, and an import path for external influence scores.
- Step 3, failed/ambiguous -> Exists: 6 telemetry detectors, meta `success` -> Missing: an
  outcome audit that cross-checks `success` against evidence, truncated-episode detection,
  and explicit recovery segments, so that kept failures are labeled on purpose.
- Labeling-side patterns (vague text, no segmentation, object confusion) -> Exists: nothing ->
  Missing: phase segmentation, a task-text audit, a neighbor-vote mislabel check, and object
  attribute disambiguation.
- Step 4, cross-embodiment -> Exists: per-collection immutable format spec with names and units
  -> Missing: an embodiment block and a mix check across collections.
- Step 5, flywheel -> Exists: append-only review rows (`review_tags`) -> Missing: linking eval
  rollouts to training coverage, saved queries re-run on new uploads, a review queue ordered
  by value, and calibration from review history.
- Scale -> Exists: paginated client-side search -> Missing: a curation plan builder that turns
  all of the above into one versioned keep/drop/review list, and a search-quality benchmark
  that proves the automation before it is trusted.


## Critical invariant

All invariants 1-8 of `01_doc.md` still hold (`episode_uid` key, `t_ns` from the frame map, spec
is the layout truth, `index_version` + `dataset_rev` on every hit, skills write only
`unreviewed`, customer data is the source of truth, spec immutability, check-before-upload).
New ones:

1. **Proposals only.** Curation outputs are derived files under
   `{MCP_ROBOT_DIR}/{collection}/curation/`. No tool deletes an episode, edits `success`,
   rewrites a task string, or appends to the customer tag file. The customer's Flow 2 makes
   the revision.
2. **Drop authority.** A curation plan can set `decision=drop` only from:
   (a) measured fields (`check_verdict`, gaps, sync), (b) human, accepted or corrected tags in
   the frozen `tag_rev`, (c) a redundancy cap that the user's rules enable, with the cluster
   recorded so the drop can be undone. Unreviewed auto tags can set `review`, never `drop`.
3. **Ranks, not raw scores.** The VModal `score` is uncalibrated (Casey Q2 still **Open**). Every
   feature uses rank-based statistics (reciprocal-rank fusion, mutual kNN, top fraction,
   percentile within task). It never uses an absolute score threshold. Calibrated numbers come
   only from review history (F12).
4. **Run card.** Every artifact has a `.run.json` with `method, method_version, params_sha256,
   dataset_rev, index_version, tag_rev (if used), inputs[] (path + sha256), created_at,
   n_scanned, n_total`. Two artifacts are comparable only if `index_version` and `dataset_rev`
   match. If the index version changes during a run, the run aborts.
5. **Within-task by default.** Redundancy, rarity and quality percentiles are computed within
   one `task` (and one embodiment). Cross-task similarity is treated as a possible label error
   (F6), not as redundancy.
6. **Failures kept on purpose.** Failure and recovery segments are never silently dropped or
   silently kept. The plan sets each one to `drop` or `keep_labeled`, and the reason is recorded.


## Data Contract

All files live under `{MCP_ROBOT_DIR}/{collection}/curation/`. Each one is written as Parquet
plus JSONL with the same rows, and a `.run.json` (D0). `t_ns` is int64 everywhere (C9).

### D0. Run card (New)
`{artifact}.run.json`: the invariant 4 keys, plus `thresholds` and `rules_sha256` when used.

### D1. Phase tags (New, C8 rows)
`tag = phase:{approach|grasp|transport|place|release|retreat}`, `t_start_ns/t_end_ns` exclusive,
`source=auto`, `tagger=robot_phase`, `tagger_version={rule_ver}`, `confidence=null`,
`review_status=unreviewed`. Extra columns: `phase_k` (grasp attempt number, 1-based) and
`phase_rule_ok` (false when the episode does not fit the rule set).

### D2. Neighbor cache (New)
`knn_cache/{index_version}/{episode_uid}.jsonl`, one row per (query keyframe, hit):
`q_episode_uid, q_t_ns, q_phase, camera, hit_episode_uid, hit_t_ns, hit_phase, rank, page`.
Self-episode hits are kept in the cache and excluded at use. A new `index_version` starts a
new folder, so old caches are never mixed in.

### D3. Redundancy clusters (New)
`redundancy_clusters`: `cluster_id, episode_uid, task, role (medoid|member|singleton),
rrf_to_medoid, tel_dist_to_medoid, n_members, saturated (bool)`.
`redundancy_pairs`: `a, b, rrf_ab, rrf_ba, mutual (bool), tel_dist, tel_q (per-task quantile)`.

### D4. Episode quality vector (New)
`quality`: `episode_uid, task`, then one column per metric (raw value + `_pct` within task),
then `composite_rank`, `weights_sha256`, `external_scores{name: value, source, ckpt}`.
Metric directions and units are listed in the run card.

### D5. Attribute matrix (New)
`attributes`: `episode_uid, attribute, value, best_rank, margin_vs_alt, scope (episode|phase),
bank_version`. A `value` with a margin below the bank's threshold becomes `ambiguous`.

### D6. Audit candidates (New, C8 rows)
Tags `outcome_conflict:{false_success|false_fail}`, `truncated`, `recovery_segment`,
`label_text:{empty|short|placeholder|variant}`, `label_suspect:task`, `object:{name}`.
Each row carries `evidence` (JSON: signals and values) so the reviewer sees why it was raised.

### D7. Calibration (New)
`calibration.json`: per (`tagger, tagger_version, tag, index_version, relevance_rank_bin`):
`n_reviewed, n_accepted, precision, ci95, n_random_stratum`. It also holds the rank cut for a
target precision. It is valid only for the listed `index_version`.

### D8. Curation rules + plan (New)
Rules (user JSON, versioned, sha256): `exclude[]` (field or confirmed-tag predicates),
`redundancy_cap {per_cluster, keep_by: quality|diversity}`, `budget {per_task}`,
`min_per {attribute|operator|robot: n}`, `keep_labeled[]` (failure/recovery tags kept with label).
Plan `curation_plan`: `episode_uid, decision (keep|drop|review|keep_labeled), reasons[]
(rule_id + evidence ref), cluster_id, quality_rank, rarity_pct`. Plan summary: counts per task
and attribute before/after, diff against the previous plan, and `plan_sha256`.

### D9. Eval gap report (New)
`eval_gap`: `rollout_uid, policy_ckpt, train_dataset_rev, fail_t_ns, failure_mode, verdict
(no_coverage|covered_by_bad_demos|covered_good), nearest_train[] (episode_uid, t_ns, rank,
tel_dist, tags), situation (phase + attributes)`.

### D10. Saved query (New)
`queries/{query_id}.json`: `definition` (text/image/detector/composite + filters),
`definition_sha256`, `watermark {index_version, uploaded_at_max}`, `runs[]`.


## Features

Each feature lists: problem (from the article), what it does, how it uses VModal, output, limits.

### Step 0 — Episode structure (foundation)

#### F1. Phase segmentation `robot_phase_segment` (New)

- Problem: "a five-step assembly logged as one undivided episode" hides the temporal structure.
  It also makes visual similarity noisy, because an approach frame can look like a retreat frame.
- Does: splits each episode into approach -> grasp -> transport -> place -> release -> retreat.
  The split uses named telemetry only: `cmd_gripper` crossings, gripper settle
  (|dgripper| < eps for 0.2 s), and TCP speed from `ee_pos`. Repeated grasps get
  `phase_k = 2, 3, ...`. Correction episodes that start mid-task are allowed to start at any phase.
- VModal: none needed (local, C2b telemetry + C2c frame index). Phase boundaries become the
  keyframes for F2/F3/F7 and the scope for F8.
- Output: D1 rows. Episodes that do not fit the rules get `phase_rule_ok=false` and no phases.
  They are reported, never guessed.
- Limits: the rule set covers gripper pick-and-place only. Other tasks (wiping, insertion)
  need their own rule set in `reference.md`, keyed by `task`.

### Step 1 — Dedup and redundancy

#### F2. Near-duplicate clusters `robot_redundancy_scan` (New)

- Problem: "hundreds of near-identical episodes of the same pick-and-place motion". Redundancy
  is semantic, not pixel-exact, so hashes do not work.
- Does: builds an episode neighbor graph within each task, then greedy medoid clusters.
  1. Keyframes: one indexed frame per F1 phase boundary, per camera (`cam_scene`, `cam_wrist`).
     Each keyframe snaps to the nearest indexed `ts` (C9) so that the query image exists.
  2. Visual neighbors: `find(image)` per keyframe, same camera, filter `task`, paged up to
     `k * pages`. Hits map to `episode_uid`. Self hits are dropped. A hit counts only if its
     `t_ns` falls in the same phase type as the query keyframe (D1).
     Pair score = sum over keyframes of 1/(60 + rank) (RRF). Neighbors = top-k by RRF.
  3. Telemetry gate: `signature_distances` (Exists) per phase, computed only on visual
     neighbor pairs (O(N*k), not O(N^2)). A pair passes if `tel_dist <= tel_q`, where tel_q is
     the per-task quantile (default p10).
  4. Clusters: sort episodes by F4 `composite_rank` (best first). Each unassigned episode
     becomes a medoid and takes its mutual-kNN neighbors that pass the gate. This avoids
     single-link chaining (A~B~C~...~Z ending in one giant cluster).
- VModal: image search per keyframe. Results are cached in D2 and the scan resumes from it.
  `dry_run` returns the call count before any search (about 1,000 episodes x 6 phases x 2 cams
  = 12k calls). `max_queries` caps the budget.
- Output: D3. `saturated=true` when all top-k hits of a page are already in the cluster, which
  means the true cluster is bigger than k.
- Limits: the fixed scene camera makes every episode share the same table and background, so
  scene-only similarity over-merges. That is why wrist frames, phase scoping and the telemetry
  gate are required, not optional. With fewer than about 3 indexed frames per phase (short
  phases at 1 fps), the scan falls back to the telemetry signature and marks `visual=sparse`.

#### F3. Coverage and rarity report `robot_coverage_report` (New)

- Problem: "surface the rarest scenarios in this dataset". Rare episodes are either the most
  informative (edge cases) or broken. Both need a look.
- Does: from the D2 cache, density = mean RRF of the top-k neighbors. `rarity_pct` = percentile
  of (1 - density) within the task. An episode with no mutual neighbor is flagged `isolated`.
  Composition tables: task x robot x operator x outcome x F7 attributes. It flags imbalance
  ratios, operator dominance (one operator > 60% of a task, i.e. style bias) and empty cells.
- VModal: none beyond the F2 cache.
- Output: `coverage` parquet (per episode: density, rarity_pct, isolated) plus `coverage.md`.
  Isolated episodes are joined with F4 quality: low quality goes to review as a suspected
  defect, high quality goes to review as a suspected valuable edge case.
- Limits: rarity is relative to what is indexed. A situation that was never recorded cannot be
  rare, only missing. F10 covers that.

### Step 2 — Quality scoring

#### F4. Episode quality vector `robot_quality_score` + `robot_scores_import` (New)

- Problem: a unique episode can still be a bad demonstration. The article warns that surface
  heuristics are not enough, and that influence-style scoring is the real ranking.
- Does: computes a vector of metrics, never one opaque score. Sources:
  - stored check data (C2c/C4): `check_verdict`, `n_frames_no_telemetry`, `n_frames_cmd_stale`,
    `telemetry_gap_ms_max`, `sync_offset_ms_max`, `wrist_dt_ms_max`, `cmd_latency_ms`;
  - telemetry: duration z within task, idle fraction (hesitation detector), TCP path length vs
    task median, TCP jerk RMS, grasp attempts (F1 `phase_k` max), `cmd_q - q` tracking error,
    gripper command chatter (toggle count), detector event counts per type;
  - video (local decode on F2 keyframes only): blur (Laplacian variance), exposure clip %,
    wrist dark fraction (occlusion).
  Each metric is converted to a percentile within the task. `composite_rank` is a weighted sum
  of percentiles, with the weights in a versioned user file. It ranks episodes and is not a
  probability.
- `robot_scores_import(path, score_name, source, ckpt)`: attaches external per-episode scores
  (influence functions, Demo-SCORE, CUPID-style scores from the customer's training runs) as
  columns, with the checkpoint id. The MCP does not compute influence, because that needs the
  policy and its gradients.
- Output: D4.
- Limits: smoothness penalizes fast but correct expert demos. That is why weights are
  per-task user config and the default weight on jerk is low.

### Step 3 — Failed, partial and ambiguous episodes

#### F5. Outcome audit `robot_outcome_audit` (New)

- Problem: "incomplete runs, drops or aborted grasps included as if successful" teach the
  policy that failure is acceptable. This is the most harmful pattern for behavior cloning.
- Does: compares meta `success` with independent evidence:
  - final state: last phase reached (D1), gripper open at end, end `ee_pos` vs the task's
    median place position (distance percentile);
  - unrecovered events: `object_drop` or `grasp_miss` with no later successful grasp
    (a grasp phase followed by transport and release);
  - end-frame visual: a per-task success phrase from the user (e.g. "cup inside the bin").
    `find(text)` filtered to the task gives the rank of each episode's last keyframe.
  Outputs:
  - `outcome_conflict:false_success`: success=true with evidence of failure. Highest priority.
  - `outcome_conflict:false_fail`: success=false with evidence of success (lost data).
  - `truncated`: ends mid-phase (gripper closed at end) or duration < task p5.
  - `recovery_segment`: window from a failure event to a successful re-grasp. It lets the
    customer keep recovery behavior deliberately (article step 3, `00_doc.md` "correction").
- VModal: one text query per task success phrase, paged (T queries, not N).
- Output: D6 rows with `evidence`. `success` is never flipped.
- Limits: tasks with no clear end state (open-ended manipulation) only get telemetry signals.

### Labeling-side patterns found at curation time

#### F6. Label audit `robot_label_audit` (New)

- Problem: vague text ("hold", "task desc") breaks language-to-action grounding. Similar
  objects with the same label add noise the model cannot resolve.
- Does, three checks:
  1. `text`: empty, fewer than 3 words, placeholder stoplist, no verb or no object, and
     spelling variants of one task ("put cup in bin" / "put the cup in the bin"). Variants are
     reported as a proposed canonical map, which the user approves. Nothing is rewritten.
  2. `knn_vote` (from D2): when at least m of an episode's top-k visual neighbors have another
     task, the episode gets `label_suspect:task` with the vote counts.
  3. `text_match`: one `find(text=task_string)` per distinct task. It builds a confusion matrix
     of task text x task label, from each episode's best rank under each text. An episode
     ranked higher by another task's text than by its own becomes a suspect.
  Object disambiguation: the user lists confusable pairs per task (e.g. "red mug" / "blue mug").
  Each phrase is searched within the task, scoped to the grasp phase. The episode gets the
  higher-ranked value if the margin passes, else `ambiguous`.
- Output: D6 rows plus a `label_audit` parquet with the confusion matrix.
- Limits: `text_match` depends on the text encoder knowing the object words. Results go to
  review, and are scored by F12 before anyone trusts them.

#### F7. Attribute query bank `robot_attribute_tag` (New)

- Problem: curation needs slices (lighting, clutter, distractors, object variant, background
  people) to balance a dataset and to explain eval failures. Today these exist only in people's
  heads.
- Does: runs a versioned bank file (attribute -> text phrases, optional reference images,
  opposite phrase, scope episode|phase). Each phrase runs once over the collection (paged).
  An attribute is assigned when an episode is in the top fraction of hits and its margin over
  the opposite phrase passes the bank threshold.
- Output: D5 plus D6 candidate rows. It feeds F3 composition, F8 filters, F10 situations and
  F13 `min_per` stratification.
- Limits: rank-based assignment needs a calibration sample per attribute (F12) before any
  attribute is used in an exclude rule.

### Search improvements

#### F8. Composite robot search `robot_find_composite` (New, extends `robot_find`)

- Problem: real curation questions combine conditions: "gripper closes, then the cup falls
  within 3 s, not in correction episodes, only grasp phase, current spike on j2".
- Does, all client-side on top of the paged `robot_find` (Exists):
  - `phase`: keep only hits whose `t_ns` is inside a D1 phase of the given type;
  - `telemetry_where`: named predicates on the hit window, e.g. `current.j2 abs_max > 3.0`,
    `gripper max > 0.95`, evaluated on stored C2b rows with the spec units checked;
  - `sequence`: A then B in the same episode within dt (A and B can be text, image, detector or tag);
  - `exclude`: drop episodes that match a tag or another query (e.g. `correction`);
  - `anchor_window`: several frames x cameras as one anchor, fused with RRF (generalizes the
    scene + wrist pair that the `vmodal-robot-similar` skill already uses).
- Output: C6 rows plus `episodes`, plus a funnel (`n_total -> n_scanned -> per predicate kept`)
  so that the recall ceiling is visible.
- Limits: recall is bounded by `max_pages` until **Backend** B2 (server-side metadata filters).

#### F9. Cross-embodiment mix check `robot_mix_check` (New)

- Problem: "episodes from different robots merged without normalizing action spaces". The
  vector has the same length but a different meaning (xArm absolute vs delta, LIBERO 10 Hz,
  AXIS 9D without video).
- Does: adds an optional `embodiment` block to the C2 spec as a new `format_version`:
  `robot_model, dof, action_space (abs_joint|delta_joint|ee_pose), gripper_semantics,
  control_hz, frame_convention, cameras`. `robot_mix_check(collections)` reports, per pair:
  field name/unit match, rate ratio, action semantics, camera roles. The verdict is
  `compatible`, `needs_transform` (with the list of transforms) or `incompatible`.
  Cross-collection `robot_find` adds `embodiment` to each hit.
- Output: `mix_check.json`. No data is normalized; that stays in the customer export (3e).
- Limits: collections without video (AXIS) take part only in telemetry-based features.

### Step 5 — Flywheel

#### F10. Eval rollout -> training coverage gap `robot_eval_link` (New)

- Problem: "the highest-value episodes are often the rare, hard cases a deployed model still
  struggles with". Failed rollouts should drive the next collection and curation round.
- Does: rollouts are uploaded with `robot_episode_upload` (Exists) into
  `{dataset}_eval_{ckpt}`, with meta keys `source=rollout, policy_ckpt, train_dataset_rev,
  success, failure_mode`. For each failed rollout, the failure time (tag or detector) is the
  anchor. Its scene + wrist frames are searched in the training collection (cross-collection
  image search), then gated by telemetry signature and same phase. Verdicts:
  - `no_coverage`: no training neighbor passes. The situation needs more demonstrations.
  - `covered_by_bad_demos`: neighbors carry failure tags or low F4 quality. This is a curation
    problem.
  - `covered_good`: good neighbors exist. The cause is the model or something else.
- Output: D9 plus `collection_requests.md`, grouped by situation (phase + F7 attributes).
- Limits: sim-to-real or new-scene rollouts may legitimately have no neighbors. The
  `situation` column lets the user tell that apart from a true gap.

#### F11. Saved queries with incremental re-run `robot_query_save` / `robot_query_run` (New)

- Problem: curation "isn't a one-time filter". New episodes arrive every day.
- Does: saves any F8, detector or text/image query as D10. Needs a new manifest key
  `uploaded_at` (ISO UTC), set by `robot_episode_upload` when the status becomes `uploaded`. It
  is absent today, so older rows are backfilled from the upload log, or treated as "before
  the first watermark". `robot_query_run(new_only=true)`
  runs it only on episodes whose manifest `uploaded_at` is after the watermark, writes
  candidate tags with the `query_id`, and moves the watermark forward. A change of
  `index_version` resets the watermark and forces a full run (invariant 4).
- Trigger: the user, or a scheduled CI job. Nothing watches continuously.

#### F12. Review queue + calibration `robot_review_queue` / `robot_tag_stats` (New)

- Problem: past a few thousand episodes, "review must be targeted". Without calibration, the
  rule "confidence >= 0.8" in Flow 2 has no meaning for search tags.
- Queue: orders unreviewed tags by expected value, not only by relevance:
  - disagreement between visual rank and telemetry detector (one fires, the other is silent);
  - impact (the tag would change a `keep` episode in the current plan);
  - rarity (F3), and a middle-rank uncertainty band;
  - one item per redundancy cluster first. The decision is then proposed to the other cluster
    members as candidates, never applied to them.
  A fixed random stratum (default 10%) is always mixed in, so that the precision and recall
  estimates are not biased by the queue's own ordering.
- Stats: from accepted/rejected/corrected rows, precision with ci95 per (tagger, version, tag,
  index_version, rank bin). The tool gives the rank cut for a target precision. It can then set
  `confidence` = empirical precision with `confidence_source=calibration@{ver}`. This answers
  Casey Q2 from data, not from the score scale.
- Output: queue sheet with returned scene/wrist frame paths for direct inspection, plus D7.
  No contact-sheet helper is included in this checkout.

### Assembly

#### F13. Curation plan builder `robot_curate_plan` (New)

- Problem: the article's pipeline ends in one decision per episode. Today that decision is a
  hand-written SQL file per round, and nobody can see why an episode left.
- Does: joins the manifest with D3, D4, D5, D6, the F3 coverage file and the frozen `tag_rev`
  snapshot, then applies the D8 rules in a fixed order:
  1. exclude (measured fields or confirmed tags only);
  2. `keep_labeled` for failure/recovery tags the user wants to keep;
  3. redundancy cap per cluster (keep the best by quality or by diversity);
  4. per-task budget;
  5. `min_per` stratification (adds back episodes so that each operator, attribute and robot
     keeps a minimum count);
  6. everything that is only suspected goes to `review` (invariant 2).
- Output: D8 plan plus summary (before/after counts per task, attribute coverage, operator
  share, diff vs the previous plan). The customer's Flow 2 reads the keep list and builds the
  new revision. The MCP never writes revisions.
- Limits: a plan is tied to its `tag_rev` and `index_version`. If either changes, the plan is
  stale and must be rebuilt.

#### F14. Search quality benchmark `robot_search_eval` (New)

- Problem: the article's scale table says automation is mandatory at tens of thousands of
  episodes, but automation that is never measured fails without anyone noticing.
- Does: takes gold windows (human-accepted tags, or the planted failures of the M2 study) and a
  list of query methods (text phrases, image anchor, scene + wrist, F8 composite, detector
  only). It reports episode recall@k, precision@k and window IoU per method and per
  `index_version`. Re-run it on every index or model change as a regression gate.
- Output: `search_eval.json` + markdown. It is the M2 report's "search quality" section.


## Component Diagram Flows

### Component Diagram Flows

Build (once per `dataset_rev` + `index_version`):
manifest (C5) + telemetry (C2b) + frame index (C2c) -> F1 phase tags (D1)
-> F2 keyframes -> `find(image)` x keyframes -> D2 cache -> D3 clusters
-> F3 coverage, F4 quality (D4), F6 knn_vote

Audit (per round):
D1 + telemetry + `find(text)` per task -> F5 outcome candidates, F6 label candidates (D6)
bank -> `find(text)` per phrase -> F7 attributes (D5)

Review:
D6 + other candidate tags -> F12 queue -> human accept/reject (Exists `review_tags`)
-> customer `tag_rev` snapshot -> F12 calibration (D7)

Decide:
D3 + D4 + D5 + D6 + coverage + `tag_rev` + rules -> F13 plan (D8)
-> customer Flow 2 -> new `dataset_rev` -> upload -> index -> Build again

Flywheel:
eval rollouts -> `robot_episode_upload` (eval collection) -> F10 gap report (D9)
-> collection requests + new demos -> upload -> F11 saved queries on new episodes -> Review

### Coupling and dependencies between components

- F1 is the base. F2, F3, F5, F6 (object), F7 (phase scope) and F8 (phase) read D1.
  If F1 is missing, those features fall back to whole-episode scope and say so in the run card.
- F2 writes D2. F3 and the F6 `knn_vote` only read D2 and never call `find` themselves.
- F4 reads F2 keyframes for video metrics. F2 reads F4 `composite_rank` to order medoids.
  The cycle is broken by running F4 without video metrics first. Video metrics are added after F2.
- F12 and F13 read the customer `tag_rev` snapshot, never live candidate files.
- All features call the SDK only through existing tools (`find`, `robot_find`,
  `image_download_from_records`). No new SDK route is needed for phase 1.
  B1-B5 are optional speedups.


## Folder Tree files Structure

```
uinterface/mcp_python_robot/
  src/mcp_server/curate/
    __init__.py
    common.py           run card D0, artifact IO, rank utils (RRF, percentiles), index_version guard
    phase.py            F1 phase rules over named telemetry -> D1
    redundancy.py       F2 keyframes, D2 cache, mutual kNN, telemetry gate, medoid clusters -> D3
    coverage.py         F3 density/rarity + composition report
    quality.py          F4 metric vector, percentiles, composite, external score import -> D4
    outcome.py          F5 outcome audit, truncation, recovery segments -> D6
    labels.py           F6 text audit, knn vote, text_match confusion, object pairs -> D6
    attributes.py       F7 bank runner -> D5
    composite.py        F8 phase/telemetry/sequence/exclude predicates over robot_find
    embodiment.py       F9 spec embodiment block + mix check
    evalgap.py          F10 rollout anchors -> train neighbors -> D9
    queries.py          F11 saved queries + watermark -> D10
    review.py           F12 queue ordering, random stratum, calibration -> D7
    plan.py             F13 rules -> plan -> D8 + summary/diff
    search_eval.py      F14 recall/precision/IoU per method
  src/mcp_server/registry.py, main_mcp.py      edit: register robot_* curation tools
  src/mcp_server/robot.py                      edit: manifest key uploaded_at (F11)
  skills/vmodal-robot-curate/
    SKILL.md            New: "curate this dataset", "find duplicates", "rarest episodes", "build next revision"
    reference.md        New: rules file examples, attribute bank example, scale playbook
  skills/vmodal-robot-similar/reference.md     edit: phase rules, outcome evidence rules
  tests/
    test_curate_phase.py, test_curate_redundancy.py, test_curate_quality.py,
    test_curate_outcome.py, test_curate_labels.py, test_curate_plan.py, test_curate_review.py
  data/robot/curate/    New: ~12 synthetic episodes (2 tasks, planted duplicates, false success,
                        vague task text, recovery) from data/generate.py
  docs/robot_contract.md                       edit: D0-D10
```


## List of potential failures issues

Search and similarity:
1. **Uncalibrated scores.** Thresholds on raw `score` drift with the index version and the
   query. Fix: ranks only (invariant 3), with calibration from review (F12).
2. **Static scene bias.** The fixed scene camera makes every episode look alike, so
   dedup over-merges. Fix: wrist keyframes, phase scoping, telemetry gate, mutual kNN (F2).
3. **Sparse index on short phases.** At 1 fps, with near-duplicate frame removal on idle
   periods, a 0.5 s grasp may have no indexed frame. Fix: snap to the nearest indexed frame in
   the same phase, else fall back to telemetry and mark `visual=sparse`. **Backend** B3.
4. **Saturated neighbor lists.** A task with 500 near-identical episodes fills top-k with
   duplicates, so rarity is underestimated and clusters are cut at k. Fix: `saturated` flag,
   then page further for that cluster only.
5. **Index re-built during a scan.** Ranks from two indexes get mixed. Fix: `index_version`
   checked on every page, the run aborts, and the D2 cache folder is per version.

Curation decisions:
6. **Dropping all of one operator or condition.** A redundancy cap plus quality ordering can
   remove one operator's style completely. Fix: `min_per` stratification (F13) and the operator
   share in the summary.
7. **Throwing away recovery data.** Failure filters remove the episodes that teach recovery.
   Fix: `recovery_segment` tags and the `keep_labeled` rule (invariant 6).
8. **Plan on a moving tag file.** Fix: the plan reads only a frozen `tag_rev` and records it.
   It is stale when the snapshot changes.
9. **Auto tags excluding data.** Fix: invariant 2. The plan builder refuses an exclude rule
   that matches `source=auto, review_status=unreviewed` rows unless `confidence` comes from D7
   calibration.
10. **Biased calibration.** A queue sorted by value only shows the easy or the borderline
    cases. Fix: a fixed random stratum, and precision reported per stratum.

Data and time:
11. **Phase rules on unfit episodes.** Correction episodes start mid-task, and multi-object
    tasks have several grasps. Fix: `phase_k`, start at any phase, `phase_rule_ok=false`
    instead of forced phases.
12. **Revision churn.** A trimmed episode in a new `dataset_rev` has new keyframe times. Fix:
    all artifacts are keyed by `dataset_rev`. Nothing is reused across revisions except D2,
    when the index and the clip are unchanged (same `n_frames`, `t0_ns`).
13. **Cost and rate limits.** 10k+ image searches for a full F2 scan. Fix: `dry_run` call
    estimate, `max_queries`, resumable D2 cache, and **Backend** B1.
14. **Cross-task duplicates hidden as redundancy.** Two tasks with the same visuals (label
    error) would be merged. Fix: within-task scope (invariant 5), and cross-task similarity is
    sent to F6 instead.
15. **Units in new metrics.** Jerk, speed and path length need `ee_pos` in m. Fix: each metric
    declares required fields + units, like the detector `REQUIRES` (Exists). It is skipped and
    reported when the spec lacks them.


------------------------------------------------------------------------
## Priority and implementation order

Ranked by harm avoided per unit of work, for the M2 ~100-episode set first:

1. F1 phase segmentation: local, cheap, and needed by most other features.
2. F5 outcome audit: false successes are the most harmful pattern for behavior cloning.
3. F2 redundancy clusters + F3 coverage/rarity: the article's headline problem, and Casey's
   pain point "unbalanced dataset, wasted GPU time".
4. F6 label audit: vague text and task mislabels break VLA language grounding.
5. F4 quality vector (without video metrics first, video metrics after F2).
6. F14 search benchmark, run inside the M2 study to measure 2-5 before trusting them.
7. F13 curation plan builder, then F12 review queue + calibration.
8. F8 composite search.
9. F7 attribute bank, F10 eval gap, F11 saved queries, F9 mix check.

How it maps to the article's scale table:
- Hundreds (M2): F1, F5, F6 text checks, every episode reviewed through F12 sheets.
- Thousands (current ~1,000 episodes): add F2, F3, F4, F13. Review only flagged and random-stratum items.
- Tens of thousands: F12 calibration becomes required, F11 incremental runs, B1 + B2.
- Hundreds of thousands and more: B1-B4 required, F10 flywheel, imported influence scores (F4).


## Backend follow-ups (not in this package)

Ordered by impact on the features above. P6.1-P6.5 in `01_doc.md` still apply.
- B1. Episode-level neighbor API: server-side top-k neighbor episodes for an episode (or a set
  of frames) from the existing index. It replaces about 12k client `find` calls in F2/F3 with
  one batch job.
- B2. Metadata filters in `/search` on `info_json` keys (= P6.2). It removes the pagination
  recall ceiling in F2, F5, F6, F8.
- B3. Denser indexing at event candidates (= P6.3): index the frames at F1 phase boundaries and
  detector windows, not only at 1 fps.
- B4. Telemetry window embeddings (= P6.4), so the F2 gate and F8 `telemetry_where` run on the server.
- B5. Score distribution per query (percentiles of `score` over the collection), as a first
  step toward a calibrated `relevance`.


## Open questions

1. Rules format for F13: JSON (matching the format spec) or YAML? Default: JSON.
2. Redundancy cap default: keep the best by quality, or the most diverse by visual and
   telemetry spread inside the cluster? Default: quality, with diversity as an option.
3. Success phrase per task (F5) and confusable object pairs (F6): provided by Casey per task,
   or drafted by the skill from task strings and then checked by Casey (same pattern as the
   P0 format draft with `"?"`)? Default: drafted, then checked.
4. Should F4 `composite_rank` order the F2 medoids, or should medoids be chosen by centrality
   only, with quality applied later by the F13 cap? Default: quality order.
