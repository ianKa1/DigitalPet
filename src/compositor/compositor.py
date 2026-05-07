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


def _build_depth_trajectory(scene: SceneContext,
                            frame_data: list,
                            total_frames: int) -> list:
    """
    Per-frame ground depth at the foot, with object-intersection episodes
    linearly interpolated from pre-entry to post-exit. This prevents an
    object's own shallow pixels from corrupting the character's scale
    when the character bbox overlaps the object.
    """
    print("\n── Pre-computing foot depth trajectory...")

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

    print(f"  Computed depth trajectory for {total_frames} frames")
    return frame_depths


# ──────────────────────────────────────────────
# MAIN COMPOSITE
# ──────────────────────────────────────────────

def composite(
    scene_json:      str   = SCENE_PROCESSED_JSON,
    trajectory_json: str   = TRAJECTORY_JSON,
    character_json:  str   = None,
    output_video:    str   = OUTPUT_VIDEO,
    global_scale:    float = GLOBAL_SCALE,
):
    """
    Run the full compositor.

    Args:
        scene_json:      output of scene_preprocessor.preprocess()
        trajectory_json: keypoint trajectory (see trajectory.json schema)
        character_json:  pet character config; if None, read from
                         trajectory_json's `character_ref` field
        output_video:    output MP4 path
        global_scale:    character scale at the near reference depth
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

    # Per-object occlusion state machines
    occlusion_states = {
        obj["id"]: ObjectOcclusionState(obj) for obj in scene.objects
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
        future_feet = []
        for k in range(1, LOOKAHEAD + 1):
            fdata_k = frame_data[min(i + k, total_frames - 1)]
            fx, fy  = fdata_k["foot_position"]
            fxc     = min(max(fx, 0), scene.w - 1)
            fyc     = min(max(fy, 0), scene.h - 1)
            fd      = float(scene.depth_m[fyc, fxc])
            future_feet.append((fx, fy, fd))

        # ── Update occlusion state machines ──
        for obj in scene.objects:
            state  = occlusion_states[obj["id"]]
            before = state.state
            state.update(foot_x, foot_y, foot_depth_m, future_feet, bbox)
            after  = state.state
            if before != after:
                label = {IN_FRONT: "IN_FRONT", BEHIND: "BEHIND"}
                print(f"  [{obj['id']}] intersect={state.is_intersecting}  "
                      f"{label[before]} -> {label[after]}")

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
    args = parser.parse_args()

    composite(
        scene_json=args.scene_json,
        trajectory_json=args.trajectory_json,
        character_json=args.character_json,
        output_video=args.output,
        global_scale=args.global_scale,
    )
