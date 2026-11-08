# Synthetic robot samples

**Fixture-only data. No real robot task was recorded.** These files test schema,
timing, alignment and diagnostic behavior; they are not a training-quality benchmark.

Two 2-second, 60-frame episodes at encoded 30/1 CFR, plus a packed 120-frame LeRobot v3 video
and episode table. Frame-map capture time deliberately uses 29.95 fps to expose drift bugs.
Telemetry runs at 100 Hz. Both episodes have a 9.0 A j2 current spike at 500 ms.
`ep_demo1` also plants a grasp miss at 150 ms and an opening/drop at 800 ms;
`ep_demo2` simulates a steady grasp. Both `q` and `cmd_q` are constant at 0.1 rad
for all six joints in both episodes. `success=false` (`ep_demo1`) and `success=true`
(`ep_demo2`) are authored test labels, not verified task outcomes. Compare gripper
and commanded-gripper values to distinguish the planted scenarios; the shared current
spike does not distinguish them.

The videos are synthetic color/test patterns, so they validate plumbing and frame alignment,
with a red/blue corner marker distinguishing episode boundaries in the packed clip,
not evidence of an actual grasp, drop, or task completion. A successful format/alignment
check does not establish physical realism, safety, correct success labels, or usefulness
for training. Failure-screen flags are heuristic candidates, not visual confirmation.
All data is synthetic. `checked_by=synthetic_fixture` is test
provenance and does not represent customer review of a production spec.

From the package directory with `PYTHONPATH` set, rebuild with `python data/generate.py build`.
Tests copy these inputs into `ztmp/ztests`; they never overwrite sample files. Per-episode
telemetry is supplied in JSON, JSONL and Parquet. `telemetry/` supplies the dataset uploader's
flat `{episode_uid}.jsonl` layout. `meta/` and `frame_map.parquet` are shared batch inputs. Each episode also includes
a matching `meta.json` for standalone skill runs. The metadata intentionally retains the
2026 start time against 2025 telemetry to exercise timestamp mismatch checks.

See [runnable tool examples](../../docs/robot_examples.md).

## Expected diagnostics

The bundled synthetic format uses a fixture-only current range of [-1, 1] A,
so each planted 9 A spike is rejected. A fresh single-episode dry run returns
`status=rejected`; a batch dry run returns `n_pass=0`, `n_flag=0`, `n_reject=2`.
Rejection produces check reports but no new validated manifest entries, so local
retrieval is not available from that run. Register the fixture spec without
`sample_path`, then check the negative samples separately.

The fixture current range is not a production motor rating;
production owners must supply their own reviewed limits. Existing registered
formats are immutable and are not silently rewritten: register a new version
with reviewed limits to change an existing format. Unbounded current receives
a warning, and isolated statistical spikes are advisory warnings even when
a configured range includes them. These statistics are not physical limits.

Upload checks also compare `meta.start_time` to the first telemetry timestamp
for explicitly declared UTC/Unix nanosecond clocks, with a one-second tolerance
for rounded timestamps and modest recording lead-in. Offset-aware ISO datetimes
are compared in UTC. Missing, invalid, timezone-less or incomparable timestamps
produce warnings instead of assuming a timezone or a device-clock epoch. The
bundled one-year metadata mismatch is intentionally retained as a negative test.
Warnings do not change the schema/alignment verdict; inspect `warnings` even
when `verdict` is `pass`. Range violations still reject uploads.
