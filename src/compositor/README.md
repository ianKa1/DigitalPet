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
              ▼               │
   ┌──────────────────────┐   │
   │ scene_labeler        │   │
   │  (one-shot per scene)│   │
   │  Gemini Flash VLM    │   │
   │  → mutates scene_    │   │
   │    processed.json    │   │
   │    in place: dedup,  │   │
   │    labels, is_object │   │
   └──────────┬───────────┘   │
              │               │
              ▼               ▼
            ┌─────────────────────┐
            │  compositor.py      │ ← trajectory.json
            │  (per render)       │   (foot positions +
            │                     │    animation +
            │                     │    at_depth_m +
            │                     │    on_top_of refs)
            │  → output_*.mp4     │
            └─────────────────────┘
```

## Modules

| File                    | Role |
|-------------------------|------|
| `geometry.py`           | Trajectory interpolation, scale-from-depth, surface normal, perspective lean, foot→bbox |
| `scene.py`              | `SceneContext`: loads bg image, depth map, per-object masks; `resolve_object_ref` for trajectory refs |
| `animation_library.py`  | `AnimationLibrary`: loads pre-extracted frames + masks with per-action playheads |
| `occlusion.py`          | Per-object front/behind state machine + occlusion alpha computation, with `forced_state` override for `on_top_of` annotations |
| `character_extractor.py`| One-shot: GIFs → SAM2-tracked frames + masks on a shared square canvas |
| `scene_preprocessor.py` | One-shot: scene image → SAM2 segments + DepthAnything depth + scene_processed.json |
| `scene_labeler.py`      | One-shot: VLM dedup of overlapping masks → per-segment labels → containment/IoU merge → Pass 2 disambiguation |
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

1. Dumps each GIF's frames to disk (`gif.seek(i)` + `gif.copy()` per frame
   — PIL's `ImageSequence.Iterator` over a GIF returns shared lazy
   references that all decode to the last frame, so we materialise
   explicitly).
2. Runs SAM2 video tracking on the largest non-white connected component
   of frame 0, using a **5-point click cluster**: the component's median
   pixel plus 4 random body samples (seeded for reproducibility). The
   single-center-point approach used earlier missed limbs and ears
   because the centroid of a sprite often falls on a hole or near an
   edge.
3. Computes the **shared canvas size** — the largest character bounding
   box seen across *all* actions, plus 15% padding on every side.
4. Centers every frame of every action on this shared square canvas.
5. Writes `extracted/<action>/frames/frame_NNNN.png` and
   `extracted/<action>/masks/frame_NNNN.png`.
6. Writes `extracted/canvas.json` with the canvas size and per-action
   metadata.
7. Writes `output/pets/<name>/character.json` with a `foot_offset_y_frac`
   derived from the locomotion actions (with a fallback to the median
   across all actions). Pass `--no-overwrite-character-json` to preserve
   manual tuning across re-runs.

The shared canvas is what makes the foot anchor consistent across action
switches. When the trajectory transitions `hop -> idle -> hop`, the bunny
doesn't pop because every frame in every action is centered the same way
on the same canvas size.

If SAM2 fails to track the character (it returns no masks), check the
`verify_click.png` written into each action's folder — it shows where
the click cluster landed on frame 0.

### 2. Preprocess a scene (once per scene)

Requires `torch`, `transformers`, and `sam2` installed. See the commented
section in `requirements.txt`.

Author a `scene.json` with the scene image path and two depth reference
points (a near and a far point, both within the depth range you care
about — calibrating against very-far background gives noisy mid-ground
depth):

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
    --output-dir output/processed_scene/<scene_name>
```

This writes `scene_processed.json`, `bg_depth_meters.npy`, per-object
masks, and a `debug_segments.png` overlay. The output goes under
`output/processed_scene/<scene_name>/` so multiple scenes coexist.

Inspect the overlay before moving on — it shows the raw SAM2 segments
with no labels. Adjust `--points-per-side`, `--pred-iou-thresh`, etc.
if SAM2 over- or under-segments.

### 3. Label the scene (once per scene)

```bash
python -m src.compositor.scene_labeler \
    --scene-dir output/processed_scene/<scene_name> \
    --save-debug-overlay
```

This mutates `scene_processed.json` in place. Four stages:

1. **Geometric pre-collapse** — within each cluster of overlapping masks,
   any pair with IoU ≥ 0.85 is folded together (largest wins) without
   calling the VLM. This handles SAM2 alternate segmentations that are
   essentially the same shape.
2. **VLM dedup** (Gemini Flash) — for clusters still ambiguous after
   pre-collapse, the labeler renders a cropped+darkened+filled view of
   each cluster and asks the VLM to group the masks by physical object.
   Redundant masks get deleted from the JSON.
3. **Pass 1 labeling** — every surviving segment gets a per-mask VLM
   label using a magenta-outlined crop. Labels include color/material
   for distinguishability (`"white mechanical keyboard"` not just
   `"keyboard"`).
4. **Containment verification + relabeling** — candidate parent/child
   pairs (containment ≥ 0.8 OR IoU ≥ 0.4) are verified by a VLM yes/no
   call, then the verified-as-same children inherit the parent's label.
5. **IoU clustering + Pass 2 disambiguation** — same-label segments are
   grouped by IoU; multi-instance clusters (e.g. two distinct mice
   sharing the label `"computer mouse"`) get distinguishing names from
   one VLM disambiguation call.

Each labeled segment gets a `label`, `label_confidence`, and `is_object`
field. The `is_object: false` flag marks sky / distant scenery / lighting
artifacts so the compositor can skip them as occluders.

Useful flags:

| Flag                    | Effect |
|-------------------------|--------|
| `--force-relabel`       | Re-label every segment even if it already has a label. Default skips labeled ones to preserve manual edits across re-runs. |
| `--save-debug-overlay`  | Writes `debug_segments_labeled.png` showing every segment with its ID, label, and depth. |
| `--debug-overlay-only`  | Skip labeling, just regenerate the overlay from the current JSON. Useful after hand-editing labels. |
| `--no-dedupe-masks`     | Skip pre-collapse + VLM dedup. Every raw SAM2 segment goes through labeling. Useful for debugging the labeler in isolation. |
| `--debug-dedup-views`   | For each multi-mask cluster, dump the rendered VLM-input image plus a sidecar JSON capturing the raw VLM response into `<scene_dir>/debug_dedup/`. Used when the dedup VLM does something surprising. |

#### Why dedup before labeling

SAM2 routinely produces multiple overlapping masks for the same physical
object (full keyboard + keycap region + spacebar; "both mice" wide mask
+ individual left/right mouse masks). If labeling runs first, downstream
containment relabeling and Pass 2 disambiguation cope with this but
produce edge cases: labels diverge slightly, disambiguation splits a
single physical object into `_left`/`_right` variants, supersets cover
multiple objects so transitivity breaks.

The dedup stage folds each cluster down to one mask per physical object
*before* labels exist. The geometric pre-collapse handles the common
case (alternate segmentations of the same shape) deterministically; the
VLM call only fires on clusters that survive pre-collapse.

The geometric pre-collapse also fixes a rendering pathology with the
VLM dedup view: alpha-blended fills get painted on top of each other, so
when N masks have near-identical coverage only the *last-drawn* mask is
visible to the VLM. The earlier mask numbers become invisible and the
VLM hallucinates descriptions for them by grasping at faint background
features. Pre-collapsing IoU ≥ 0.85 pairs removes the invisible masks
before they reach the VLM.

### 4. Author a character.json

```json
{
  "character": {
    "name": "Fluffball",
    "frames_dir": "output/pets/Fluffball/animations/extracted",
    "foot_offset_x_frac": 0.5,
    "foot_offset_y_frac": 0.811,
    "default_animation": "idle"
  },
  "animations": {
    "idle": { "facing": "right", "looping": true },
    "hop":  { "facing": "right", "looping": true }
  }
}
```

`frames_dir` points at the extractor's output. `native_height_px` is
auto-derived from `canvas.json` if you don't set it. `foot_offset_y_frac`
is auto-derived by the extractor from the locomotion actions, but worth
double-checking by eyeballing the centered frames — it tells the
compositor where in the frame the character's feet actually are.

### 5. Author a trajectory.json

The `animation` field on each keypoint selects which clip plays. It's a
step function — held until the next keypoint changes it. Direct mapping:
`"animation": "hop"` → reads from `extracted/hop/frames/`.

```json
{
  "trajectory": {
    "scene_ref": "output/processed_scene/desk/scene_processed.json",
    "character_ref": "output/pets/Fluffball/character.json",
    "fps": 30,
    "keypoints": [
      { "frame": 0,   "foot_position": [150, 1100], "facing": "right",
        "animation": "hop", "at_depth_m": 0.35 },

      { "frame": 60,  "foot_position": [500, 1080], "facing": "right",
        "animation": "hop",  "on_top_of": "obj_004" },

      { "frame": 120, "foot_position": [600, 1080], "facing": "right",
        "animation": "curious_look", "on_top_of": "obj_004" },

      { "frame": 200, "foot_position": [1080, 1050], "facing": "right",
        "animation": "idle", "on_top_of": ["obj_033", "obj_026"] }
    ]
  }
}
```

#### Trajectory annotations

Each keypoint can carry two optional semantic fields beyond the basic
`foot_position` / `facing` / `animation`:

**`at_depth_m`** (float, optional) — overrides the depth-map-sampled
depth at that keypoint. Linearly interpolated between two surrounding
keypoints that both carry the field. If either neighbour is unannotated,
unannotated frames fall back to depth-map sampling — `at_depth_m` is
explicit semantic intent, not implicit propagation. Use this when the
depth map gives noisy values for the character's current support
surface (e.g. on top of a tissue box where the depth map sees the box
top but DepthAnything's estimate is off by 10–20cm).

**`on_top_of`** (string or list of strings, optional) — forces the
character IN_FRONT of the referenced scene object(s) regardless of
depth comparison. Step function — held across frames until cleared
(`on_top_of: null`) or replaced. The reference resolves via
`SceneContext.resolve_object_ref`:

- An exact ID match (`"obj_004"`) returns that single object.
- Otherwise, a case-insensitive label match returns all objects sharing
  that label.

When the bunny is at a scene depth that should put it behind an object
it's semantically standing on (its foot depth is deeper than the object's
sampled base depth, perhaps due to depth-map noise), `on_top_of` is the
escape hatch.

**List form** — when masks overlap in the bunny's path (e.g. two adjacent
mouse masks, or a "both mice" superset overlapping with each individual
mouse), give a list to force IN_FRONT against all of them at once.

**Lookahead extension** — `on_top_of` annotations are extended backward
in time automatically. The compositor walks back up to 60 frames from
each `on_top_of` run-start to find where the character's bbox first
intersects the referenced object's mask, and extends the annotation
backward to that frame. This avoids needing a keypoint exactly at the
moment of bbox-mask intersection.

#### Trajectory refs: labels vs IDs

`on_top_of` accepts either form, but the two have different stability
properties:

- **IDs** (`"obj_004"`, `"obj_033"`) are assigned by the preprocessor and
  survive every re-run of the labeler. Stable.
- **Labels** (`"white mechanical keyboard"`) can drift across labeler
  re-runs — Pass 1 might phrase it differently (`"white and blue
  mechanical keyboard"`), and Pass 2 disambiguation might suffix it
  (`"white_mechanical_keyboard_left"`). When the trajectory's label
  reference stops matching, `on_top_of` silently resolves to nothing
  and the depth-map fallback kicks in.

For trajectories that need to survive labeler iteration, prefer IDs.
Labels are convenient for hand-authoring and fine when labels are
stable. Mix the two as needed.

### 6. Composite

```bash
python -m src.compositor.compositor \
    --scene-json     output/processed_scene/desk/scene_processed.json \
    --trajectory-json output/processed_scene/desk/trajectory.json \
    --output         output_composite.mp4
```

Or programmatically:

```python
from src.compositor import composite

composite(
    scene_json="output/processed_scene/desk/scene_processed.json",
    trajectory_json="output/processed_scene/desk/trajectory.json",
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
(positively, by tracking from a click cluster), so the character's color
doesn't matter. The 5-point click cluster — median of the largest
non-white connected component plus 4 random body samples — is more
robust than a single centroid click; the centroid of a sprite often
falls in a hole or right at an edge.

## Known gotchas

- **Dedup VLM can over-split** when a cluster's masks cover one
  physical object with visually distinct sub-features (e.g. a keyboard
  with red/blue LED indicators visible inside the mask region). The
  geometric pre-collapse handles the common case; for the residual
  cases, run with `--debug-dedup-views` and inspect the rendered cluster
  view + sidecar JSON.
- **Supersets get warned, not auto-merged.** When one mask covers
  multiple distinctly-labeled children (a `"silver laptop"` containing
  separate `"laptop_screen"` / `"laptop_keyboard"` / `"laptop_trackpad"`
  children), auto-merging would destroy the children's identity. The
  labeler logs a warning so the human can either rename the superset
  to one child's label, mark it `is_object: false`, or list its ID as
  an extra `on_top_of` ref in the trajectory.
- **The labeler mutates `scene_processed.json` in place** and drops
  redundant masks from `objects[]` on each run. Mask PNG files on disk
  are preserved. To re-introduce a dropped mask, re-run the
  preprocessor.
- **`at_depth_m` and `on_top_of` are independent annotation paths.**
  They don't blend. A keypoint with `at_depth_m: 1.0` followed by one
  with `on_top_of: obj_X` does not produce a smooth depth transition
  in between — the segment falls back to depth-map sampling. To get a
  smooth depth ramp across an `on_top_of` boundary, give both keypoints
  explicit `at_depth_m` values.
- **Close-range scenes** (a desk where multiple objects sit within
  10–20 cm of each other) push the limits of monocular depth
  estimation. `on_top_of` semantic annotations are the intended
  resolution; the labeler is what makes those annotations possible.

## Relationship to `tests/test_animate_pet_on_path.py`

That test does flat 2D pasting along waypoints — no depth, no occlusion.
It's much faster (no SAM2/DepthAnything required) and useful as a quick
preview path for trajectory authoring. The compositor here is the
depth-aware path that produces the final occlusion-correct output.