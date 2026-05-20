# Compositor

Inserts a DigitalPet's animation library into a real scene with depth-aware
occlusion and perspective scale.

## Pipeline overview

```
                ┌───────────────────────────────────────┐
                │  generators/sprite_animation_generator│
                │     (existing — produces GIFs)        │
                └────────────────┬──────────────────────┘
                                 │ output/pets/<name>/animations/*.gif
                                 ▼
              ┌───────────────────────────────────┐
              │  character_extractor.py           │
              │  (SAM2 video tracking, one-shot   │
              │   per pet)                        │
              │  → animations/extracted/<action>/ │
              │      frames/  masks/              │
              │  → animations/extracted/canvas    │
              │      .json (shared canvas size)   │
              └────────────────┬──────────────────┘
                               │
   scene image + scene.json    │
              │                │
              ▼                │
   ┌──────────────────────┐   │
   │ scene_preprocessor   │   │
   │  (one-shot per scene)│   │
   │  SAM2 + DepthAnything│   │
   │  → scene_processed   │   │
   │    .json + masks +   │   │
   │    depth map         │   │
   └──────────┬───────────┘   │
              │               │
              ▼               ▼
            ┌─────────────────────┐
            │  compositor.py      │ ← trajectory.json
            │  (per render)       │   (foot positions +
            │                     │    animation field)
            │  → output_*.mp4     │
            └─────────────────────┘
```

## Modules

| File                    | Role |
|-------------------------|------|
| `geometry.py`           | Trajectory interpolation, scale-from-depth, surface normal, perspective lean, foot→bbox |
| `scene.py`              | `SceneContext`: loads bg image, depth map, per-object masks |
| `animation_library.py`  | `AnimationLibrary`: loads pre-extracted frames + masks with per-action playheads |
| `occlusion.py`          | Per-object front/behind state machine + occlusion alpha computation |
| `character_extractor.py`| One-shot: GIFs → SAM2-tracked frames + masks on a shared square canvas |
| `scene_preprocessor.py` | One-shot: scene image → SAM2 segments + DepthAnything depth + scene_processed.json |
| `compositor.py`         | Main entry: reads everything above, writes the composite video |

## Quick start

### 1. Extract a pet's animation library (once per pet)

After running the existing DigitalPet pipeline through Step 4 (sprite
extraction), run:

```bash
python -m src.compositor.character_extractor \
    --animations-dir output/pets/Fluffball/animations
```

This walks every `*.gif` in that directory and:

1. Dumps each GIF's frames to disk.
2. Runs SAM2 video tracking with a single click point on the first frame
   to segment the character across all frames.
3. Computes the **shared canvas size** — the largest character bounding
   box seen across *all* actions, plus 15% padding on every side.
4. Centers every frame of every action on this shared square canvas.
5. Writes `extracted/<action>/frames/frame_NNNN.png` and
   `extracted/<action>/masks/frame_NNNN.png`.
6. Writes `extracted/canvas.json` with the canvas size and per-action
   metadata.

The shared canvas is what makes the foot anchor consistent across action
switches. When the trajectory transitions `hop -> idle -> hop`, the bunny
doesn't pop because every frame in every action is centered the same way
on the same canvas size.

If SAM2 fails to track the character (it returns no masks), check the
`verify_click.png` written into each action's folder — it shows where
the click landed on frame 0. Override with `--click-x` / `--click-y`.

### 2. Preprocess a scene (once per scene)

Requires `torch`, `transformers`, and `sam2` installed. See the commented
section in `requirements.txt`.

Author a `scene.json` with the scene image path and two depth reference
points:

```json
{
  "scene": {
    "image_path": "testing_background/street.png",
    "reference_points": {
      "near": { "image_pos": [1300, 1450], "metric_depth_m": 1.5 },
      "far":  { "image_pos": [1250, 700],  "metric_depth_m": 30.0 }
    }
  }
}
```

Then run:

```bash
python -m src.compositor.scene_preprocessor \
    --scene-json scene_data/scene.json \
    --output-dir scene_data
```

This writes `scene_processed.json`, `bg_depth_meters.npy`, per-object
masks, and a `debug_segments.png` overlay. Inspect the overlay before
moving on; if SAM2 produced bad segments, mark them `is_ground_plane`
in `scene_processed.json` or tighten the area filters.

### 3. Author a character.json

```json
{
  "character": {
    "name": "Fluffball",
    "frames_dir": "output/pets/Fluffball/animations/extracted",
    "foot_offset_x_frac": 0.5,
    "foot_offset_y_frac": 0.95,
    "default_animation": "idle"
  },
  "animations": {
    "idle": { "facing": "right", "looping": true },
    "hop":  { "facing": "right", "looping": true }
  }
}
```

`frames_dir` points at the extractor's output. `native_height_px` is
auto-derived from `canvas.json` if you don't set it. Tune
`foot_offset_y_frac` after eyeballing the centered frames — it tells the
compositor where in the frame the character's feet actually are.

### 4. Author a trajectory.json

The `animation` field on each keypoint selects which clip plays. It's a
step function — held until the next keypoint changes it. Direct mapping:
`"animation": "hop"` → reads from `extracted/hop/frames/`.

```json
{
  "trajectory": {
    "scene_ref": "scene_data/scene_processed.json",
    "character_ref": "scene_data/character.json",
    "fps": 30,
    "keypoints": [
      { "frame": 0,   "foot_position": [200, 1300], "facing": "right", "animation": "hop"  },
      { "frame": 45,  "foot_position": [800, 1270], "facing": "right", "animation": "idle" },
      { "frame": 90,  "foot_position": [900, 1265], "facing": "right", "animation": "hop"  }
    ]
  }
}
```

### 5. Composite

```bash
python -m src.compositor.compositor \
    --scene-json     scene_data/scene_processed.json \
    --trajectory-json scene_data/trajectory.json \
    --output         output_composite.mp4
```

Or programmatically:

```python
from src.compositor import composite

composite(
    scene_json="scene_data/scene_processed.json",
    trajectory_json="scene_data/trajectory.json",
    output_video="output_composite.mp4",
    global_scale=1.0,
)
```

## Why SAM2 instead of background-keying?

The first version of this pipeline used a flood-fill from the corners to
remove the white background of each GIF. That works for *colored*
characters — the keying carves away connected white pixels and leaves
the character. It breaks for **white-bodied characters** like Fluffball:
the white-keying chews up the body because every pixel is white, and the
flood-fill can't tell character-white from background-white.

SAM2 video tracking sidesteps this entirely. It segments the *character*
(positively, by tracking from a click point), so the character's color
doesn't matter. It also gives a crisper silhouette than morphological
operations can recover from a noisy mask.

## Relationship to `tests/test_animate_pet_on_path.py`

That test does flat 2D pasting along waypoints — no depth, no occlusion.
It's much faster (no SAM2/DepthAnything required) and useful as a quick
preview path for trajectory authoring. The new compositor is the depth-
aware path that produces the final occlusion-correct output.
