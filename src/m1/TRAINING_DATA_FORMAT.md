# Training data input format (VLA)

What the model is trained on: LeRobot v3.0 frame rows. One row = one scene-camera frame, 30 fps on disk. Schema source: `meta/info.json`.

## Columns

| Column | Type | Content | Units |
| --- | --- | --- | --- |
| `index` | int64 | global row id | – |
| `episode_index` | int64 | episode id within this dataset revision (stable id = `episode_uid`, via frame map) | – |
| `frame_index` | int64 | frame number within the episode | – |
| `timestamp` | float32 | measured scene-cam frame time minus episode start | s |
| `task_index` | int64 | -> task string in `meta/tasks.parquet` | – |
| `observation.state` | float32[7] | `j1..j6`, `gripper` | rad; 0 open .. 1 closed |
| `observation.ee_pose` | float32[6] | `x, y, z`, `roll, pitch, yaw` | m; rad |
| `action` | float32[7] | `j1..j6` commanded, `gripper` | rad absolute; 0..1 |
| `observation.images.cam_scene` | video frame | RealSense D415, 640×480, in mp4 | – |
| `observation.images.cam_wrist` | video frame | RealSense D405, 640×480, in mp4 | – |

Images are not stored in the parquet. They are decoded from the mp4 at the row's `timestamp` (file and offset from the episode table).

## Sample rows

Episode 412, task_index 3 = "put the cup in the bin". Vectors are flattened, one column per element. The camera columns are left out because they are video frames.

```csv
index,episode_index,frame_index,timestamp,task_index,state.j1,state.j2,state.j3,state.j4,state.j5,state.j6,state.gripper,ee.x,ee.y,ee.z,ee.roll,ee.pitch,ee.yaw,action.j1,action.j2,action.j3,action.j4,action.j5,action.j6,action.gripper
1384680,412,120,4.0012,3,0.214,-0.402,-0.688,0.011,1.093,0.226,0.000,0.312,0.061,0.184,3.129,0.021,0.207,0.219,-0.409,-0.681,0.011,1.089,0.231,0.000
1384681,412,121,4.0346,3,0.218,-0.407,-0.683,0.011,1.090,0.230,0.000,0.313,0.063,0.181,3.129,0.022,0.211,0.223,-0.415,-0.675,0.012,1.086,0.235,0.000
1384682,412,122,4.0679,3,0.222,-0.413,-0.677,0.012,1.087,0.234,0.000,0.314,0.064,0.178,3.130,0.022,0.215,0.227,-0.421,-0.669,0.012,1.083,0.239,0.000
```

## How a training sample is built

- **Input at frame t:** `cam_scene` + `cam_wrist` (resized to 224×224 with padding), `observation.state`, task text.
- **Target:** `action[t .. t+9]` (horizon 10 = 0.33 s at 30 fps).
- **π0.5 (openpi):** arm actions converted to deltas (`action − state`), gripper absolute; quantile norm stats from the train split.
- **LingBot-VLA 2.0:** same rows, mapped through its robot config yaml (`subtract_state` for the arm only).
- Joint current is not a model input. It is in the 100 Hz telemetry sidecar and is used for search and tagging only.
