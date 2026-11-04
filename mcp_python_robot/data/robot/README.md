# Synthetic robot samples

Two 2-second, 60-frame episodes at encoded 30/1 CFR, plus a packed 120-frame LeRobot v3 video
and episode table. Frame-map capture time deliberately uses 29.95 fps to expose drift bugs.
Telemetry runs at 100 Hz. Both episodes have a 9.0 A j2 current spike at 500 ms.
`ep_demo1` also plants a grasp miss at 150 ms and an opening/drop at 800 ms;
`ep_demo2` has a steady grasp. Compare gripper and commanded-gripper values to
distinguish the grasp outcomes; the shared current spike does not distinguish them.

The videos are synthetic color/test patterns, so they validate plumbing and frame alignment,
with a red/blue corner marker distinguishing episode boundaries in the packed clip,
not visual failure quality. All data is synthetic. `checked_by=synthetic_fixture` is test
provenance and does not represent customer review of a production spec.

From the package directory with `PYTHONPATH` set, rebuild with `python data/generate.py build`.
Tests copy these inputs into `ztmp/ztests`; they never overwrite sample files. Per-episode
telemetry is supplied in JSON, JSONL and Parquet. `telemetry/` supplies the dataset uploader's
flat `{episode_uid}.jsonl` layout. `meta/` and `frame_map.parquet` are shared batch inputs.

See [runnable tool examples](../../docs/robot_examples.md).
