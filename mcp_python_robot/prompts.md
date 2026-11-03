# Prompts you can copy

Connect VModal using the [setup guide](README.md), then paste any prompt below
into your AI assistant's chat. Each box is a separate prompt.

Use your own collection names and file paths. The examples use `city` and
`my_videos`; those collections may not exist in your account.
You don't need tool names, index versions, or technical settings.
Advanced fashion prompts (trend radar, capsule lookbook) are in
[prompts_fashion.md](prompts_fashion.md).

## Check that VModal is connected

```text
Use VModal to check my connection and show my account.
```

## List my collections

A collection is a group of your videos or images. Start here to see its name:

```text
List all my collections.
```

## List my sub-collections

A sub-collection is a smaller group inside a collection:

```text
List all my sub-collections in a table with two columns:
Collection | Sub-collection
```

To see just one collection:

```text
List the sub-collections in my city collection.
```

## Find something in a collection

Replace the description with what you're looking for, and `city` with a name
from your collection list:

```text
Find a red car.
Collection: city
```

This searches the whole collection. You can also use this format; leaving
Sub-collection blank has the same effect:

```text
Find people standing beside a stone wall.
Collection: city
Sub-collection:
```

## Search just one sub-collection

Replace `rome` with a sub-collection name from your list:

```text
Find a gray car parked on a street.
Collection: city
Sub-collection: rome
```

## Save matching pictures

```text
Find trees shading a street in my city collection. Save the best three
matching pictures to my computer and tell me where to find them.
```

Another example:

```text
Find a castle or a large historic stone building in my city collection.
Save the best five matching pictures to my computer and show me their paths.
```

## Refine a search

After a search, keep chatting:

```text
Try again with a red car parked beside a stone building, in the same collection.
```

## Upload a video and search it

Replace `./my_video.mp4` with the path to your video. This prompt creates a
collection named `my_videos` if needed:

```text
Upload ./my_video.mp4 to a collection named my_videos, in a sub-collection
named my_uploads. Make it searchable and wait until it's ready.
Then find a person walking outside.
```

## Upload a folder of videos

Replace `./camera_exports` with the path to your folder:

```text
Upload all MP4 videos from ./camera_exports to a collection named
camera_exports, in a sub-collection named my_uploads.
Tell me which files uploaded successfully. Make the uploaded videos
searchable and tell me when they're ready.
```

## Check whether my videos are ready

```text
Check whether collection my_videos is ready to search.
Show its indexing jobs and explain the status simply.
```

## Check my usage

```text
Show my current VModal usage and explain it simply.
```

## Preview deleting an old collection

```text
Show what would be deleted if I removed my old_videos collection.
Do not delete anything yet.
```

## If a search finds nothing

```text
I couldn't find what I wanted in my city collection. Check that the
collection exists and is ready to search, then try a simpler description.
```
# Robot sample prompts

- Draft a format from data/v1/telemetry.jsonl; show unknown units and reviewer settings for me to fill.
- Register data/robot/xarm6_gripper_100hz.format.json for robot_demo, then dry-run both LeRobot
  episodes using the paths in docs/robot_examples.md. Show the per-episode verdict table.
- Retrieve ep_demo1 around 1761130005002869449 ns from robot_demo using local_decode;
  show the scene/wrist images, timestamp, named telemetry and sync report.
- On my real indexed collection, find episodes like this failure. Show visual and telemetry
  signatures, search coverage and candidate evidence; export unreviewed tags for my review.
