"""
compositor.py

Composites a DigitalPet's animation library into a real scene with depth-
aware occlusion and perspective scale.

Key differences from the original (single-video) compositor:

  - The character is no longer a single MP4 + precomputed mask directory.
    Instead it is an AnimationLibrary: a per-action set of GIFs each with
    its own frame count and an independent playhead. The trajectory's
    `animation` field selects which clip is active at each frame, and the
    playhead resumes naturally when an action is re-entered.

  - Masks are not part of the GIFs (DigitalPet GIFs have white backgrounds
    rather than alpha channels). They come from
        output/pets/<name>/animations/masks/<action>/frame_NNNN.png
    written by mask_preprocessor.preprocess_pet_masks() — run that once
    after the sprite extraction step before invoking the compositor.

The depth math, occlusion state machine, perspective lean, and ground-
plane filter are unchanged from the original compositor.
"""

import cv2
import numpy as np

from .geometry import (
    load_trajectory,
    interpolate_trajectory,
    compute_scale_from_depth,
    get_stable_normal,
    apply_perspective_lean,
    foot_to_bbox,
)
from .scene import SceneContext
from .animation_library import AnimationLibrary
from .occlusion import (
    ObjectOcclusionState,
    compute_occlusion_alpha,
    IN_FRONT,
    BEHIND,
)


# ──────────────────────────────────────────────
# DEFAULT PATHS — overridable via composite() args
# ──────────────────────────────────────────────

SCENE_PROCESSED_JSON = "scene_data/scene_processed.json"
TRAJECTORY_JSON      = "scene_data/trajectory.json"
OUTPUT_VIDEO         = "output_composite.mp4"
GLOBAL_SCALE         = 1.0

# Depth tolerance (metres) for the occlusion state machine. The character
# counts as BEHIND an object only if its foot depth exceeds the object's
# base depth by at least this much. Acts as a slop margin to absorb
# calibration noise in monocular depth estimation. 0 disables the
# tolerance (strict ordering, suitable for outdoor scenes with large
# depth gradients). 0.10–0.20m is reasonable for indoor / close-range
# scenes (desks, tables) where multiple objects sit within a few cm.
DEPTH_TOLERANCE_M    = 0.0


# ──────────────────────────────────────────────
# DEPTH TRAJECTORY (foot depth per frame, with intersection smoothing)
# ──────────────────────────────────────────────

def _sample_ground_depth(scene: SceneContext, fx: int, fy: int,
                         patch_r: int = 40) -> float:
    """
    Median depth in a patch around (fx, fy), excluding pixels covered by
    any scene object mask. This gives a stable foot-on-ground depth even
    when the foot is near (but not yet inside) an object.
    """
    fy = min(max(fy, 0), scene.h - 1)
    fx = min(max(fx, 0), scene.w - 1)
    py1 = max(0, fy - patch_r); py2 = min(scene.h, fy + patch_r + 1)
    px1 = max(0, fx - patch_r); px2 = min(scene.w, fx + patch_r + 1)
    patch = scene.depth_m[py1:py2, px1:px2]

    gmask = np.ones_like(patch, dtype=bool)
    for obj in scene.objects:
        op = obj["mask"][py1:py2, px1:px2]
        if op.shape == patch.shape:
            gmask &= (op <= 128)

    if gmask.sum() > patch.size * 0.25:
        return float(np.median(patch[gmask]))
    return float(np.median(patch))


def _sample_depth_inside_mask(scene: SceneContext, obj: dict,
                              fx: int, fy: int, patch_r: int = 20) -> float:
    """
    Sample the median depth inside `obj`'s mask, in a patch around
    (fx, fy). Used when the trajectory says `on_top_of: obj` — we want
    the local depth where the character is actually standing on the
    object, which varies across tall objects (a laptop screen's top is
    further away than its base).

    Falls back to the object's `base_depth_m` if the foot position
    doesn't sit near any mask pixels (e.g. one pixel off the edge).
    """
    fy = min(max(fy, 0), scene.h - 1)
    fx = min(max(fx, 0), scene.w - 1)
    py1 = max(0, fy - patch_r); py2 = min(scene.h, fy + patch_r + 1)
    px1 = max(0, fx - patch_r); px2 = min(scene.w, fx + patch_r + 1)

    mask_patch  = obj["mask"][py1:py2, px1:px2]
    depth_patch = scene.depth_m[py1:py2, px1:px2]
    inside = (mask_patch > 128)

    if inside.sum() >= 4:
        return float(np.median(depth_patch[inside]))
    return float(obj["base_depth_m"])


def _resolve_foot_state(scene: SceneContext, fdata: dict) -> tuple:
    """
    Decide how to interpret a single frame's foot position given the
    trajectory's semantic annotations.

    Returns (foot_depth_m, forced_states_dict) where:
      foot_depth_m: explicit depth in metres, or None to let the caller
                    fall back to the legacy depth-trajectory sampling
      forced_states_dict: {object_id: IN_FRONT or BEHIND}, used by the
                          state machine to override depth-based decisions
                          for specific objects.

    `on_top_of` accepts either a single object reference (string) or a
    list of references. This handles two cases with the same mechanism:

      1. **SAM2 over-segmentation.** A single real-world object often
         gets split into multiple overlapping segments — e.g. the right
         mouse becomes both `obj_016` and `obj_017` because SAM2 found
         several plausible mask boundaries for the same surface. The
         trajectory author specifies all of them so each gets forced
         IN_FRONT. Annotating only one leaves the others to fight the
         depth comparison and the character gets occluded.

      2. **Genuinely stacked surfaces.** When the character stands on a
         book that sits on a table, both should be IN_FRONT relative to
         the character. The list expresses this naturally.

    The two annotations compose because they answer different questions:
      - `at_depth_m`  answers "where is the character" (depth/scale)
      - `on_top_of`   answers "what is the character locked onto"
                      (occlusion override against these objects)

    Resolution:
      1. If `on_top_of` is present, force every referenced object to
         IN_FRONT. Depth is sampled from the FIRST referenced object's
         mask (the others are duplicates/stack-mates, not the surface
         the foot is touching).
      2. If `at_depth_m` is also present, it overrides any depth derived
         from on_top_of.
      3. If neither is present, return (None, {}).
    """
    forced = {}
    depth = None

    on_top_of = fdata.get("on_top_of")
    if on_top_of is not None:
        # Normalise to list so single-string and list forms share code.
        # Backward compatible: "obj_017" → ["obj_017"]
        if isinstance(on_top_of, str):
            refs = [on_top_of]
        else:
            refs = list(on_top_of)

        primary_obj = None
        for ref in refs:
            objs = scene.resolve_object_ref(ref)
            if not objs:
                print(f"  ⚠️  on_top_of references unknown object "
                      f"{ref!r}; ignoring.")
                continue
            # A reference can expand to multiple objects when the trajectory
            # uses a label that several SAM2 segments share. All of them
            # get forced IN_FRONT — that's the whole point of label-based
            # references for over-segmented objects.
            for obj in objs:
                forced[obj["id"]] = IN_FRONT
            # The first valid reference's FIRST object is the "primary" —
            # it's what we sample depth from. Convention: author lists the
            # actual surface the foot is touching first, then any other
            # objects (under-stack, lookahead-merged additions) after.
            if primary_obj is None:
                primary_obj = objs[0]

        if primary_obj is not None:
            fx, fy = fdata["foot_position"]
            depth = _sample_depth_inside_mask(scene, primary_obj, fx, fy)

    # at_depth_m always wins for depth if specified; on_top_of's forced
    # states still apply.
    if fdata.get("at_depth_m") is not None:
        depth = float(fdata["at_depth_m"])

    return depth, forced


# ──────────────────────────────────────────────
# ON_TOP_OF LOOKAHEAD EXTENSION
# ──────────────────────────────────────────────

# Maximum frames the lookahead will extend an on_top_of annotation backward
# from its declared start. A safety cap for degenerate cases — if a trajectory
# passes the target's mask for a very long approach, the geometric walk-back
# stops at this many frames before the target keypoint.
MAX_LOOKAHEAD_FRAMES = 60


def _refs_as_list(value):
    """Normalise on_top_of: 'obj_X' -> ['obj_X'], list stays list, None -> []."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _extend_on_top_of_annotations(frame_data: list,
                                  scene: SceneContext,
                                  char,
                                  global_scale: float,
                                  near_depth_m: float) -> None:
    """
    Extend each `on_top_of` annotation backward in time along the
    interpolated trajectory, up to the point where the character's bbox
    geometrically intersects the target's mask. Modifies frame_data
    in place.

    Why this exists:
      Without this, the trajectory author has to manually predict the
      exact frame where the character's bbox starts overlapping the
      next on_top_of target, and insert an extra keypoint right before
      that frame. The geometric walk-back automates that prediction:
      forced IN_FRONT activates the moment overlap actually begins.

    Merge semantics:
      If the walk-back from on_top_of=B reaches a frame that already
      has on_top_of=A (an earlier annotation), the frame's annotation
      becomes the merged list [A, B] for that overlap window. Both
      objects are then forced IN_FRONT. This handles "leaving A,
      approaching B" gracefully — the bbox can be touching both
      objects' masks during the handoff, and neither should occlude.

    Approximation:
      The bbox size used for the intersection test is the size the
      character would have *at the target keypoint* (using the target's
      depth/scale). This holds well as long as the approach doesn't
      span very different depths. For a typical desk/scene trajectory
      where depth changes by ~0.1m across the approach, the bbox size
      barely changes — close enough.
    """
    total_frames = len(frame_data)
    if total_frames == 0:
        return

    # Find each run of identical on_top_of values. A "run start" is the
    # first frame in a maximal sequence with the same on_top_of value.
    # We only walk back from run starts because mid-run frames are
    # already covered by the run.
    extensions_made = []  # list of (start_frame, end_frame, refs) for logging

    def get_refs_at(i):
        return _refs_as_list(frame_data[i].get("on_top_of"))

    # Walk forward looking for the START of each on_top_of run
    i = 0
    while i < total_frames:
        refs_here = get_refs_at(i)
        if not refs_here:
            i += 1
            continue

        prev_refs = get_refs_at(i - 1) if i > 0 else []
        is_run_start = (refs_here != prev_refs)
        if not is_run_start:
            i += 1
            continue

        # Walk backward from i-1 trying to extend `refs_here` backward
        extended_to = i  # earliest frame extended
        for back in range(i - 1, max(-1, i - MAX_LOOKAHEAD_FRAMES - 1), -1):
            # Stop if this frame has on_top_of that doesn't overlap refs_here.
            # Under merge semantics: if it shares ALL refs, we'd be mid-run
            # (shouldn't get here); if it shares NONE, we can merge; if it
            # shares some, we can merge. So really we only stop when we
            # collide with an existing annotation that we'd modify in a way
            # that goes against the prior author intent — which is:
            # don't merge if every existing ref would survive (i.e. we'd be
            # adding to a frame that already has its own different annotation).
            existing = get_refs_at(back)
            if existing and not any(r in refs_here for r in existing):
                # Already-annotated region with completely different targets.
                # Merge by union, but don't walk further back — we've hit
                # the previous run.
                merged = list(existing) + [r for r in refs_here if r not in existing]
                frame_data[back]["on_top_of"] = merged
                extended_to = back
                break

            # Does the bbox at frame `back` intersect any target mask?
            if not _bbox_intersects_any_target(
                frame_data[back], frame_data[i], refs_here,
                scene, char, global_scale, near_depth_m,
            ):
                # No intersection — no need to extend further backward.
                break

            # Extend: merge refs_here into this frame's annotation
            existing_refs = get_refs_at(back)
            if existing_refs:
                merged = list(existing_refs) + [
                    r for r in refs_here if r not in existing_refs
                ]
                frame_data[back]["on_top_of"] = merged
            else:
                # No existing annotation — just copy ours
                frame_data[back]["on_top_of"] = (
                    refs_here[0] if len(refs_here) == 1 else list(refs_here)
                )
            extended_to = back

        if extended_to < i:
            extensions_made.append((extended_to, i - 1, refs_here))

        # Advance past this run's start frame; the rest of the run
        # has the same refs and we'll skip over it naturally.
        i += 1

    if extensions_made:
        print(f"\n── Lookahead extended {len(extensions_made)} on_top_of "
              f"annotation(s) backward:")
        for start, end, refs in extensions_made:
            refs_str = refs[0] if len(refs) == 1 else "[" + ",".join(refs) + "]"
            print(f"     {refs_str}: frames {start}-{end} "
                  f"({end - start + 1} frames extended)")


def _bbox_intersects_any_target(fdata_probe: dict,
                                fdata_target: dict,
                                target_refs: list,
                                scene: SceneContext,
                                char,
                                global_scale: float,
                                near_depth_m: float) -> bool:
    """
    Predict whether the character's bbox at frame `fdata_probe` would
    intersect any of the target objects' masks. Uses the scale derived
    from `fdata_target`'s depth (an approximation — see docstring of
    _extend_on_top_of_annotations).
    """
    # Determine the depth at the target frame to compute scale
    target_depth = None
    if fdata_target.get("at_depth_m") is not None:
        target_depth = float(fdata_target["at_depth_m"])
    else:
        # Sample inside the first valid target object's mask.
        # A ref can expand to multiple objects (via label match); pick
        # the first one to sample from.
        for ref in target_refs:
            objs = scene.resolve_object_ref(ref)
            if objs:
                fx, fy = fdata_target["foot_position"]
                target_depth = _sample_depth_inside_mask(scene, objs[0], fx, fy)
                break
        if target_depth is None:
            return False  # nothing we can do

    if target_depth <= 0:
        return False
    scale = (near_depth_m / target_depth) * global_scale
    canvas = char.native_height_px
    bbox_w = max(1, int(canvas * scale))
    bbox_h = max(1, int(canvas * scale))

    # Compute bbox at the probe frame using that scale
    fx_p, fy_p = fdata_probe["foot_position"]
    x1 = fx_p - int(bbox_w * char.foot_offset_x_frac)
    y1 = fy_p - int(bbox_h * char.foot_offset_y_frac)
    x2, y2 = x1 + bbox_w, y1 + bbox_h
    # Clip to scene bounds
    ax1 = max(0, x1); ay1 = max(0, y1)
    ax2 = min(scene.w, x2); ay2 = min(scene.h, y2)
    if ax1 >= ax2 or ay1 >= ay2:
        return False

    # Check intersection with any target mask. A single ref can expand
    # to multiple objects (over-segmentation), and any of them counts —
    # the bunny touching any segment of the target physical object
    # means it's making contact with that object.
    for ref in target_refs:
        objs = scene.resolve_object_ref(ref)
        for obj in objs:
            mask_region = obj["mask"][ay1:ay2, ax1:ax2]
            if np.any(mask_region > 128):
                return True
    return False


# ──────────────────────────────────────────────
# DEPTH TRAJECTORY
# ──────────────────────────────────────────────

def _build_depth_trajectory(scene: SceneContext,
                            frame_data: list,
                            total_frames: int) -> list:
    """
    Per-frame foot depth, resolved with this priority:
      1. Frame's explicit `at_depth_m` (linear-interpolated by the
         trajectory loader between annotated keypoints).
      2. Frame's `on_top_of` — sample the depth map inside that object's
         mask near the foot.
      3. Legacy depth-map sampling at the foot pixel, with bbox-
         intersection smoothing to handle ambiguity when the foot pixel
         falls inside some other (unrelated) object's mask.

    The legacy fallback still does the smoothing pass, because trajectories
    that aren't yet semantically annotated should keep working the way
    they used to.
    """
    print("\n── Pre-computing foot depth trajectory...")

    n_annotated = 0
    semantic_depths = [None] * total_frames

    # First pass: pick up explicit/semantic depths frame by frame
    for i, fd in enumerate(frame_data):
        depth, _ = _resolve_foot_state(scene, fd)
        if depth is not None:
            semantic_depths[i] = depth
            n_annotated += 1

    # Second pass: legacy sampling + smoothing fills in the gaps
    ground_depths = []
    intersecting_any = []
    for fd in frame_data:
        fx, fy = fd["foot_position"]
        d = _sample_ground_depth(scene, fx, fy)

        fxc = min(max(fx, 0), scene.w - 1)
        fyc = min(max(fy, 0), scene.h - 1)
        in_any = any(obj["mask"][fyc, fxc] > 128 for obj in scene.objects)

        ground_depths.append(d)
        intersecting_any.append(in_any)

    frame_depths = list(ground_depths)
    i_ep = 0
    while i_ep < total_frames:
        if intersecting_any[i_ep]:
            start = i_ep
            while i_ep < total_frames and intersecting_any[i_ep]:
                i_ep += 1
            end = i_ep

            pre_idx  = max(0, start - 1)
            post_idx = min(total_frames - 1, end)
            d_pre  = ground_depths[pre_idx]
            d_post = ground_depths[post_idx]

            ep_len = end - start
            for k in range(ep_len):
                t = (k + 1) / (ep_len + 1)
                frame_depths[start + k] = d_pre * (1 - t) + d_post * t
        else:
            i_ep += 1

    # Third pass: semantic overrides win where present
    for i in range(total_frames):
        if semantic_depths[i] is not None:
            frame_depths[i] = semantic_depths[i]

    print(f"  Computed depth trajectory for {total_frames} frames "
          f"({n_annotated} semantically annotated, "
          f"{total_frames - n_annotated} via depth-map sampling)")
    return frame_depths


# ──────────────────────────────────────────────
# MAIN COMPOSITE
# ──────────────────────────────────────────────

def composite(
    scene_json:        str   = SCENE_PROCESSED_JSON,
    trajectory_json:   str   = TRAJECTORY_JSON,
    character_json:    str   = None,
    output_video:      str   = OUTPUT_VIDEO,
    global_scale:      float = GLOBAL_SCALE,
    depth_tolerance_m: float = DEPTH_TOLERANCE_M,
):
    """
    Run the full compositor.

    Args:
        scene_json:        output of scene_preprocessor.preprocess()
        trajectory_json:   keypoint trajectory (see trajectory.json schema)
        character_json:    pet character config; if None, read from
                           trajectory_json's `character_ref` field
        output_video:      output MP4 path
        global_scale:      character scale at the near reference depth
        depth_tolerance_m: slop margin for occlusion ordering (see
                           module-level DEPTH_TOLERANCE_M comment)
    """
    print("\n── Loading scene...")
    scene = SceneContext(scene_json)

    print("\n── Loading trajectory...")
    traj_data = load_trajectory(trajectory_json)
    if character_json is None:
        character_json = traj_data["character_ref"]

    print("\n── Loading character animation library...")
    char = AnimationLibrary(character_json)

    # Total composite frames = span from first to last keypoint
    last_kp_frame = max(kp["frame"] for kp in traj_data["keypoints"])
    total_frames  = last_kp_frame + 1
    frame_data    = interpolate_trajectory(traj_data["keypoints"], total_frames)
    print(f"Trajectory spans {total_frames} frames")

    # Filter walkable surfaces (desk, floor, keyboard...)
    scene.filter_ground_planes()
    # Filter labeler-tagged noise segments (sky, gradients, lighting artifacts).
    # No-op for scenes that haven't been labeled yet.
    scene.filter_noise()

    # Extend on_top_of annotations backward where the bbox would
    # already intersect the target's mask. Runs AFTER ground-plane
    # filtering so we don't try to use filtered objects as targets.
    _extend_on_top_of_annotations(
        frame_data, scene, char, global_scale, scene.near_depth_m,
    )

    # Per-object occlusion state machines
    if depth_tolerance_m > 0:
        print(f"  Using depth tolerance: ±{depth_tolerance_m:.2f}m "
              f"(absorbs calibration noise; objects within this "
              f"distance are treated as IN_FRONT)")
    occlusion_states = {
        obj["id"]: ObjectOcclusionState(obj, depth_tolerance_m=depth_tolerance_m)
        for obj in scene.objects
    }

    # Depth trajectory
    frame_depths = _build_depth_trajectory(scene, frame_data, total_frames)

    # Output video
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps    = float(traj_data.get("fps", 30))
    out    = cv2.VideoWriter(output_video, fourcc, fps, (scene.w, scene.h))

    print(f"\n── Compositing {total_frames} frames → {output_video}")
    print(f"{'Frm':<5} | {'Anim':<10} | {'Foot XY':<14} | {'Depth':>7} | "
          f"{'Scale':>6} | Occluders")
    print("-" * 75)

    LOOKAHEAD = 6

    for i, fdata in enumerate(frame_data):
        action = fdata.get("animation", char.default_animation)
        foot_x, foot_y = fdata["foot_position"]

        # ── Read character frame from the right animation cycle ──
        char_frame, mask = char.step(action)
        if char_frame is None or mask is None:
            out.write(scene.bg_image.copy())
            continue

        # Align mask size to char_frame (they should match by construction
        # but resize defensively in case of fallback masks)
        if mask.shape[:2] != char_frame.shape[:2]:
            mask = cv2.resize(mask,
                              (char_frame.shape[1], char_frame.shape[0]),
                              interpolation=cv2.INTER_NEAREST)

        # ── Facing flip ──
        # Sprites are assumed authored facing right (per character.json
        # animations[<action>].facing field). If trajectory says left,
        # mirror both the frame and its mask.
        anim_meta   = char.get_animation_meta(action)
        author_face = anim_meta.get("facing", "right")
        if fdata.get("facing", "right") != author_face:
            char_frame = cv2.flip(char_frame, 1)
            mask       = cv2.flip(mask, 1)

        # ── Foot depth → scale ──
        foot_y_clamped = min(max(foot_y, 0), scene.h - 1)
        foot_x_clamped = min(max(foot_x, 0), scene.w - 1)
        foot_depth_m   = frame_depths[i]
        scale          = compute_scale_from_depth(foot_depth_m,
                                                  scene.near_depth_m,
                                                  global_scale)

        # ── Perspective lean (subtle ground-plane tilt) ──
        disp_proxy = (scene.depth_m / scene.depth_m.max() * 255).astype(np.uint8)
        normal     = get_stable_normal(disp_proxy, foot_x_clamped, foot_y_clamped)
        char_res, mask_res = apply_perspective_lean(char_frame, mask,
                                                    normal, scale)

        # ── Bounding box ──
        nw, nh = char_res.shape[1], char_res.shape[0]
        x1, y1 = foot_to_bbox(foot_x, foot_y, nw, nh,
                               char.foot_offset_x_frac,
                               char.foot_offset_y_frac)
        ax1 = max(0, x1);            ay1 = max(0, y1)
        ax2 = min(scene.w, x1 + nw); ay2 = min(scene.h, y1 + nh)

        if ax1 >= ax2 or ay1 >= ay2:
            out.write(scene.bg_image.copy())
            continue

        bbox = (ax1, ay1, ax2, ay2)

        # ── Crop character to clipped bbox ──
        cx1, cy1 = ax1 - x1, ay1 - y1
        cx2, cy2 = cx1 + (ax2 - ax1), cy1 + (ay2 - ay1)
        char_crop = char_res[cy1:cy2, cx1:cx2].astype(float)
        mask_crop = mask_res[cy1:cy2, cx1:cx2].astype(float) / 255.0

        # ── Future foot positions/depths for occlusion lookahead ──
        # Use frame_depths (already resolved with semantic overrides
        # baked in) rather than raw depth-map sampling, so the state
        # machine's majority-vote is consistent with the actual depth
        # the character will be at on future frames.
        future_feet = []
        for k in range(1, LOOKAHEAD + 1):
            j = min(i + k, total_frames - 1)
            fdata_k = frame_data[j]
            fx, fy  = fdata_k["foot_position"]
            fd      = frame_depths[j]
            future_feet.append((fx, fy, fd))

        # ── Update occlusion state machines ──
        # Semantic annotations (on_top_of, etc.) produce a forced_states
        # dict that overrides the depth-comparison logic for specific
        # objects. For example, when the trajectory says `on_top_of:
        # obj_023`, that object's state is forced IN_FRONT so the
        # character isn't occluded by it, regardless of depth math.
        _, forced_states = _resolve_foot_state(scene, fdata)

        for obj in scene.objects:
            state  = occlusion_states[obj["id"]]
            before = state.state
            forced = forced_states.get(obj["id"])
            state.update(foot_x, foot_y, foot_depth_m, future_feet, bbox,
                         forced_state=forced)
            after  = state.state
            if before != after:
                label = {IN_FRONT: "IN_FRONT", BEHIND: "BEHIND"}
                src = "forced" if forced is not None else "depth"
                print(f"  [{obj['id']}] intersect={state.is_intersecting}  "
                      f"{label[before]} -> {label[after]} ({src})")

        # ── Occlusion alpha ──
        occlude_alpha = compute_occlusion_alpha(
            foot_x=foot_x, foot_y=foot_y,
            scene=scene, bbox=bbox,
            occlusion_states=occlusion_states,
        )

        active_objs = [obj["id"] for obj in scene.objects
                       if occlusion_states[obj["id"]].state == BEHIND]

        print(f"{i:<5} | {action:<10} | ({foot_x:<5},{foot_y:<5}) | "
              f"{foot_depth_m:>6.2f}m | {scale:>5.3f} | "
              f"{active_objs if active_objs else '-'}")

        # ── Blend ──
        mask_3 = cv2.GaussianBlur(
            (mask_crop * 255).astype(np.uint8), (3, 3), 0
        ).astype(float) / 255.0
        final_alpha = cv2.merge([mask_3 * occlude_alpha] * 3)

        roi     = scene.bg_image[ay1:ay2, ax1:ax2].astype(float)
        blended = char_crop * final_alpha + roi * (1.0 - final_alpha)

        result = scene.bg_image.copy()
        result[ay1:ay2, ax1:ax2] = blended.astype(np.uint8)
        out.write(result)

    char.release()
    out.release()
    print(f"\nDone → {output_video}")
    return output_video


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-json",      default=SCENE_PROCESSED_JSON)
    parser.add_argument("--trajectory-json", default=TRAJECTORY_JSON)
    parser.add_argument("--character-json",  default=None)
    parser.add_argument("--output",          default=OUTPUT_VIDEO)
    parser.add_argument("--global-scale",    type=float, default=GLOBAL_SCALE)
    parser.add_argument(
        "--depth-tolerance",
        type=float,
        default=DEPTH_TOLERANCE_M,
        help="Slop margin (metres) for occlusion ordering. The character "
             "is considered BEHIND an object only if its foot depth "
             "exceeds the object's base depth by at least this much. "
             "Useful for indoor / close-range scenes (try 0.10–0.20). "
             "Default 0 keeps strict ordering for outdoor scenes.",
    )
    args = parser.parse_args()

    composite(
        scene_json=args.scene_json,
        trajectory_json=args.trajectory_json,
        character_json=args.character_json,
        output_video=args.output,
        global_scale=args.global_scale,
        depth_tolerance_m=args.depth_tolerance,
    )