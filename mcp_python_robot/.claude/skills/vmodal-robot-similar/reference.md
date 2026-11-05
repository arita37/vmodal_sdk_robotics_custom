# Failure catalog — xarm_demo_v1

These rules produce candidates, not ground truth. Thresholds are demonstration defaults for
the synthetic xArm samples. Supply robot-specific thresholds before using real data. Every
scan returns thresholds and detector version; record both in reports and tag provenance.

| Type | Text phrases / visual PASS | Telemetry rule and required units |
| --- | --- | --- |
| grasp_miss | “gripper closes on nothing”, “empty gripper above table”; object stays on table | cmd_gripper crosses 0.5; gripper > close=0.95 within 0.5 s; both 0_open_1_closed, command role on cmd_gripper |
| object_drop | “object falls from gripper”, “cup dropped during transport”; object below gripper or away from target | gripper decreases by opening=0.1 while command >=0.95, or object stop goes to full close while TCP speed > transport_mps=0.02; ee_pos in m |
| slip | object shifts in closed grasp | gripper creeps >0.05 toward closed within 0.3 s, command >=0.95 |
| collision_contact | tool contacts obstacle | current exceeds current_A per named joint (default 5 A), TCP speed drops below half previous speed; current A and ee_pos m |
| joint_limit | arm at configured travel boundary | q within margin_rad=0.05 of the registered spec range, rad; provide actual robot limits in the spec |
| hesitation_idle | arm stationary mid-task | TCP speed < idle_mps=0.005 for >3 s, excluding first/last second |
| occlusion_wrist | “camera view blocked by hand or object”; wrist dark/blocked | Visual only; scan reports skipped |
| correction | manual correction episode | Exclude from anchors by default; do not exclude from datasets automatically |

The normalized gripper is 0=open, 1=closed, so opening means a **decrease**. This resolves the
draft's contradictory “position rises (opens)” wording. Named vector components come from
the episode's immutable spec. No interpolation or detector transition crosses a telemetry gap.
The current 0.8 detector confidence is a fixed heuristic, never a calibrated probability.

Example: retrieve `ep_demo1` near its close command, inspect both views, search “empty gripper
above table”, and scan `grasp_miss`. A telemetry event between sampled index frames remains
a candidate; use `robot_retrieve(image_source=local_decode)` for its exact mapped frame.

Script input/output contracts are documented in [the robot contract](../../docs/robot_contract.md).
