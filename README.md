# DigitalPet MVP

An AI-powered digital pet generator that creates unique pets with personalities and animated sprites, then composites them into real scenes.

## Architecture Overview

The system runs in three sequential phases:

```
[Phase 1: Generators] → pet_info.json + GIF library
[Phase 2: Pre-processors] → animation.json (per input image)
[Phase 3: Video Composer] → final composited video
```

---

## Phase 1: Generators 

Builds a pet's identity and animation library. Run once per pet; output is reusable across any scene.

| Step | Description | Model |
|------|-------------|-------|
| 1. Pet description | Generate personality and appearance text | Gemini 2.5 Flash |
| 2. Image creation | Generate the pet's reference image from description | Gemini 3.1 Flash Image |
| 3. Action generation | Generate a list of actions based on personality | Gemini 2.5 Flash |
| 4. Sprite animation | Generate a batch sprite sheet, extract GIFs for each action | Gemini 3.1 Flash Image |
| 5. Pet profile *(TODO)* | Write extended `pet_info.json` fields: environment preference, interaction style, and abilities | — |

### Pet profile schema (`pet_info.json`)

```json
{
  "name": "Fluffball",
  "species": "Cloud Bunny",
  "personality": ["playful", "curious"],
  "actions": ["idle", "hop", "walk_forward", "walk_right"],

  // TODO — needed by Phase 2
  "environment": "outdoor",          // "indoor" | "outdoor"
  "interaction_style": "introvert",  // "introvert" (reacts to scene) | "extrovert" (seeks people)
  "abilities": ["float", "climb", "swim"]    // informs which scenes/trajectories are valid
}
```

---

## Phase 2: Pre-processors 

Takes an image input and decides how to place the pet in it. Outputs `animation.json`, which Phase 3 reads directly.

### Inputs
- Image input
- Depth map (per-pixel, from team 1)
- Scene description JSON (from team 1 — see format below)

### Required scene description format (from upstream team)

```json
{
  "environment": "outdoor",        // "indoor" | "outdoor" — used by 2a
  "has_water": false,              // bool — used by 2a + 2c
  "people_count": 2,               // int — used by 2a
  "objects": [
    {
      "label": "bench",
      "bbox": [0.1, 0.6, 0.3, 0.75],  // normalized [x1, y1, x2, y2]
      "is_walkable_surface": true,    // pet can stand/walk on this
      "is_walkable_surface": false,   // pet can climb on this
      "is_water": false,             // pet can swim in this
      "is_obstacle": false,            // pet must path around this if true
      "depth_mean": 0.45               // mean depth in this bbox, same scale as depth map
    }
  ]
}
```

**TODO: Discuss bbox and depth representation needed for better animation.**

### Steps

#### 2a. Character–scene matching
Select which pet fits the scene best.

**Proposed Approach:** Use `environment`, `has_water`, and `people_count` from the scene JSON to score each available pet against its `pet_info.json` fields (`environment`, `abilities`, `interaction_style`). Pick creature based on score.

#### 2b. Trajectory + animation planning (combined)
Decide where the pet moves and what it does at each step.
**TODO: Discuss whether to separate them into two steps. For now I put them into one step because trajectory and animation sequence are dependent on each other.**

**Proposed Approach:** Single LLM call that generates the full `(waypoint, action)` sequence as a coherent story, for each key frame.

Prompt inputs:
- Scene object list
- Pet's available `actions` list from `pet_info.json`
- Pet's `personality`, `interaction_style`, `abilities`

Example output the LLM should produce:
```json
{
"keypoints":
[
  { "frame": 0, "foot_position": [0, 0],  "animation": "walk_right" },
  { "frame": 60, "foot_position": [0, 30],  "animation": "look_around" }
]
}
```

#### 2c. Scale at insertion point
Determine how large the pet should appear at each waypoint.

**Proposed Approach:** For each waypoint `(x, y)`, read the normalized depth value `d ∈ [0, 1]` from the depth map. Apply:
```
scale = base_scale * (1 - depth_weight * d)
```
Where `base_scale` is calibrated once using a known reference object in the scene (e.g., a door at ~200 cm). Interpolate scale smoothly along the trajectory.

After this step, write `animation.json`.

### Output schema (`animation.json`)

```json
{
"keypoints":
[
  { "frame": 0, "foot_position": [0, 0],  "animation": "walk_right", "scale": 0.5},
  { "frame": 60, "foot_position": [0, 30],  "animation": "look_around", "scale": 0.5}
]
}
```

---

## Phase 3: Video Composer

Reads `animation.json` and composites the pet onto the scene.

**Proposed Approach:**
1. For each frame, find the active waypoint(s) and interpolate `(x, y, scale)`.
2. Look up the current action's GIF; select the right frame based on elapsed time within that action loop.
3. Resize the sprite to `scale`, remove background (sprite already has transparency), and alpha-blend onto the scene frame.
4. Write frames to output video.

---

## Project Structure

```
src/
├── generators/
│   ├── pet_description_generator.py   # Phase 1, step 1
│   ├── pet_appearance_generator.py    # Phase 1, step 2
│   ├── action_description_generator.py # Phase 1, step 3
│   └── sprite_animation_generator.py  # Phase 1, step 4
├── preprocessors/                     # TODO: Phase 2
├── composer/                          # TODO: Phase 3
├── prompts/
└── utils/
output/
└── pets/<PetName>/
    ├── pet_info.json
    ├── appearance.png
    └── animations/<action>.gif
trajectories/                          # Phase 2/3 experiments
```

---

## Next Steps

- [ ] **Phase 1** — Add `environment`, `interaction_style`, `abilities` fields to pet generation prompt and `pet_info.json` schema
- [ ] **Phase 2a** — Implement scoring rubric for creatures
- [ ] **Phase 2b** — Implement combined trajectory + animation planner ( → waypoint/action/duration sequence)
- [ ] **Phase 2c** — Implement scale post-processor (depth map lookup → add `scale`)
- [ ] **Phase 3** — Implement frame compositor (sprite → scene overlay) and video writer


