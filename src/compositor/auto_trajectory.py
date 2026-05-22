"""
auto_trajectory.py

Automatically generates a trajectory JSON (with explicit depth_m per keypoint)
from a preprocessed scene. No manual clicking required.

How it works
────────────
1. Loads scene_processed.json → depth map + object masks
2. Builds a walkable-floor mask: pixels not covered by any SAM2 object and
   within a sensible depth range.
3. Traces a floor profile across the image (the surface the pet walks on)
   by finding, per x-column, the lowest walkable pixel in the floor band.
4. Samples N evenly-spaced waypoints along that profile.
5. Reads depth_m directly from the depth map at each foot position — no
   guessing from surrounding pixels; this is the exact depth at (x, y).
6. Assigns animations using pluggable rules (motion, object proximity,
   variety injection, end-of-path rest).
7. Writes a trajectory JSON with explicit depth_m per keypoint.

Animation selection rules
─────────────────────────
  hop          : foot moves > HOP_DIST_PX between consecutive waypoints
  idle         : small movement
  curious_look : foot lands within CURIOUS_RADIUS px of any object centroid
  bounce       : injected every BOUNCE_EVERY idle keypoints for variety
  wiggle_ears  : alternates with bounce as the other variety action
  sleep        : replaces idle for the final SLEEP_TAIL keypoints if they
                 are all stationary

Usage
─────
  python -m src.compositor.auto_trajectory \\
      --scene-json     output/scenes/desk/processed_scene/scene_processed.json \\
      --character-json output/pets/Fluffball/character.json \\
      --output         scene_input/auto_trajectory.json

Options
───────
  --n-keypoints   N    Number of waypoints (default 10)
  --frame-spacing N    Frames between waypoints (default 20)
  --fps           N    FPS for trajectory JSON (default 30)
  --floor-y-frac  F    Top of the floor band as a fraction of image height
                       (default 0.45 = lower 55% of the image is the search zone)
  --max-depth     F    Exclude floor pixels deeper than this (metres, default 2.0)
  --path-style    S    "sweep" (left-to-right), "return" (left-right-left),
                       or "wander" (gentle random walk on the floor)
  --seed          N    Random seed for "wander" style (default 42)
  --visualize          Write a debug PNG next to the output JSON
"""

import argparse
import json
import math
import os
import random
from pathlib import Path

import cv2
import numpy as np


# ──────────────────────────────────────────────
# TUNABLE THRESHOLDS
# ──────────────────────────────────────────────

HOP_DIST_PX    = 20    # pixel distance between waypoints that triggers "hop"
CURIOUS_RADIUS = 80    # px — if foot is this close to an object centroid → curious_look
BOUNCE_EVERY   = 3     # inject bounce/wiggle every N consecutive idle keypoints
SLEEP_TAIL     = 2     # replace final N stationary keypoints with sleep


# ──────────────────────────────────────────────
# SCENE LOADING
# ──────────────────────────────────────────────

def load_scene(scene_json_path: str) -> dict:
    with open(scene_json_path) as f:
        data = json.load(f)

    image_path = data["scene"]["image_path"]
    bg = cv2.imread(image_path)
    if bg is None:
        raise FileNotFoundError(f"Scene image not found: {image_path}")
    h, w = bg.shape[:2]

    depth_path = (data.get("depth_map_path")
                  or data["scene"].get("depth_map_path"))
    if not depth_path or not os.path.exists(depth_path):
        raise FileNotFoundError(
            f"Depth map not found ({depth_path}). "
            f"Run scene_preprocessor first."
        )
    depth_m = np.load(depth_path).astype(np.float32)
    if depth_m.shape[:2] != (h, w):
        depth_m = cv2.resize(depth_m, (w, h), interpolation=cv2.INTER_LINEAR)

    near_depth_m = float(
        data["scene"]["reference_points"]["near"]["metric_depth_m"]
    )

    objects = []
    for obj in data.get("objects", []):
        mp = obj.get("mask_path")
        if not mp or not os.path.exists(mp):
            continue
        mask = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        if mask.shape[:2] != (h, w):
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        ys, xs = np.where(mask > 128)
        centroid = (int(np.mean(xs)), int(np.mean(ys))) if len(ys) else None
        objects.append({
            "id":           obj["id"],
            "mask":         mask,
            "centroid":     centroid,
            "base_depth_m": float(obj.get("base_depth_m", near_depth_m)),
        })

    return {
        "bg":           bg,
        "h":            h,
        "w":            w,
        "depth_m":      depth_m,
        "near_depth_m": near_depth_m,
        "objects":      objects,
    }


# ──────────────────────────────────────────────
# FLOOR MASK
# ──────────────────────────────────────────────

def build_floor_mask(scene: dict,
                     floor_y_frac: float,
                     max_depth_m: float) -> np.ndarray:
    """
    Boolean mask of walkable floor pixels:
      - In the lower portion of the image (y >= floor_y_frac * h)
      - Not covered by any object mask
      - Depth within [near_depth_m * 0.5, max_depth_m]

    The depth lower-bound prevents sky/background pixels (which DepthAnything
    can assign unrealistically shallow values to) from polluting the floor.
    """
    h, w     = scene["h"], scene["w"]
    depth_m  = scene["depth_m"]
    y_min    = int(h * floor_y_frac)

    floor = np.zeros((h, w), dtype=bool)
    floor[y_min:, :] = True

    for obj in scene["objects"]:
        floor &= (obj["mask"] <= 128)

    floor &= (depth_m >= scene["near_depth_m"] * 0.5)
    floor &= (depth_m <= max_depth_m)

    return floor


# ──────────────────────────────────────────────
# FLOOR PROFILE
# ──────────────────────────────────────────────

def trace_floor_profile(floor_mask: np.ndarray,
                        h: int, w: int,
                        smooth_window: int = 40) -> dict:
    """
    For each x column return the full vertical range of walkable pixels as
    (y_min, y_max). y_max is the bottom of the floor (closest to camera /
    most foreground); y_min is the top (deepest walkable point in the scene).

    The path sampler uses this range to clamp any target y to a surface
    that actually exists, regardless of how steeply the path travels into
    the scene. Both edges are smoothed with a rolling median.
    """
    raw_min, raw_max = {}, {}
    for x in range(w):
        col_ys = np.where(floor_mask[:, x])[0]
        if len(col_ys):
            raw_min[x] = int(col_ys.min())
            raw_max[x] = int(col_ys.max())

    if not raw_max:
        raise RuntimeError(
            "Floor mask is empty — no walkable floor pixels found. "
            "Try increasing --floor-y-frac or --max-depth."
        )

    xs_sorted = sorted(raw_max.keys())
    half = smooth_window // 2

    def smooth(raw):
        vals = [raw[x] for x in xs_sorted]
        out  = []
        for i in range(len(xs_sorted)):
            lo = max(0, i - half)
            hi = min(len(vals), i + half + 1)
            out.append(int(np.median(vals[lo:hi])))
        return out

    s_min = smooth(raw_min)
    s_max = smooth(raw_max)

    return {x: (ylo, yhi)
            for x, ylo, yhi in zip(xs_sorted, s_min, s_max)}


# ──────────────────────────────────────────────
# PATH SAMPLING
# ──────────────────────────────────────────────

def sample_path(profile: dict,
                w: int,
                n_keypoints: int,
                path_style: str,
                start_y: int,
                end_y: int,
                seed: int = 42) -> list:
    """
    Returns a list of (x, y) tuples.

    The path moves diagonally from (x_lo, start_y) to (x_hi, end_y) —
    this is what makes the pet travel "into" the scene rather than staying
    flat along the bottom edge. In a perspective desk view, start_y should
    be near the bottom of the image (large y = close to camera) and end_y
    should be higher up (small y = farther into the scene).

    At each sampled x, the target y is clamped to the (y_min, y_max) range
    from the floor profile so every point lands on an actual walkable surface.

    sweep  : straight diagonal from start_y to end_y, left-to-right
    return : forward half sweeps to end_y, back half returns to start_y
    wander : jittered walk in both x and y, drifting from start_y to end_y
    """
    xs_available = sorted(profile.keys())
    x_lo = xs_available[0]
    x_hi = xs_available[-1]

    def target_y_at(x):
        """Linear interpolation of target y between start_y and end_y."""
        if x_hi == x_lo:
            return start_y
        t = (x - x_lo) / (x_hi - x_lo)
        return int(start_y + t * (end_y - start_y))

    def clamp_to_floor(x, y):
        """Snap x to nearest profile column, clamp y to that column's range."""
        cx = min(xs_available, key=lambda px: abs(px - x))
        y_min, y_max = profile[cx]
        return (int(cx), int(np.clip(y, y_min, y_max)))

    if path_style == "sweep":
        xs = np.linspace(x_lo, x_hi, n_keypoints, dtype=int)
        return [clamp_to_floor(x, target_y_at(x)) for x in xs]

    elif path_style == "return":
        half = max(2, n_keypoints // 2)
        fwd_xs = np.linspace(x_lo, x_hi, half, dtype=int)
        bwd_xs = np.linspace(x_hi, x_lo, n_keypoints - half, dtype=int)
        fwd = [clamp_to_floor(x, target_y_at(x)) for x in fwd_xs]
        # Return leg: reverse the y direction (end_y → start_y)
        bwd = [clamp_to_floor(x, target_y_at(x_hi - (x - x_lo))) for x in bwd_xs]
        return fwd + bwd

    elif path_style == "wander":
        rng    = random.Random(seed)
        x_step = (x_hi - x_lo) / max(n_keypoints - 1, 1)
        y_step = (end_y - start_y) / max(n_keypoints - 1, 1)
        x_cur  = float(x_lo)
        y_cur  = float(start_y)
        points = []
        for _ in range(n_keypoints):
            points.append(clamp_to_floor(int(x_cur), int(y_cur)))
            x_cur += max(0.0, rng.gauss(x_step, x_step * 0.35))
            y_cur += rng.gauss(y_step, abs(y_step) * 0.5)
            x_cur  = np.clip(x_cur, x_lo, x_hi)
        return points

    else:
        raise ValueError(f"Unknown path_style: {path_style!r}")


# ──────────────────────────────────────────────
# ANIMATION ASSIGNMENT
# ──────────────────────────────────────────────

def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _nearest_object_dist(x, y, objects):
    best = float("inf")
    for obj in objects:
        if obj["centroid"] is not None:
            d = math.hypot(obj["centroid"][0] - x, obj["centroid"][1] - y)
            best = min(best, d)
    return best


def assign_animations(waypoints: list,
                      objects: list,
                      available: list) -> list:
    """
    Returns a list of (animation, facing) strings parallel to waypoints.

    Decision order per keypoint:
      1. curious_look  — if near an object centroid (and available)
      2. hop           — if moving far enough from previous waypoint
      3. idle variety  — bounce / wiggle_ears injected every BOUNCE_EVERY
                         consecutive idle keypoints
      4. idle          — default stationary animation
      5. sleep         — overrides idle for the final SLEEP_TAIL stationary pts

    'available' is the sorted list of action names from character.json.
    Unknown names fall back to the first available action.
    """
    def pick(name):
        return name if name in available else available[0]

    results  = []
    idle_run = 0   # consecutive idle/stationary keypoints

    for i, (x, y) in enumerate(waypoints):
        # Facing: derived from x-delta to next waypoint (or prev if last)
        if i < len(waypoints) - 1:
            dx = waypoints[i + 1][0] - x
        elif i > 0:
            dx = x - waypoints[i - 1][0]
        else:
            dx = 1
        facing = "right" if dx >= 0 else "left"

        prev = waypoints[i - 1] if i > 0 else None
        dist = _dist(prev, (x, y)) if prev else 0
        near_obj = _nearest_object_dist(x, y, objects) < CURIOUS_RADIUS

        if near_obj and "curious_look" in available:
            anim     = pick("curious_look")
            idle_run = 0
        elif dist >= HOP_DIST_PX:
            anim     = pick("hop")
            idle_run = 0
        else:
            idle_run += 1
            if idle_run % BOUNCE_EVERY == 0:
                # Alternate between bounce and wiggle_ears for variety
                if idle_run % (BOUNCE_EVERY * 2) == 0 and "wiggle_ears" in available:
                    anim = pick("wiggle_ears")
                else:
                    anim = pick("bounce") if "bounce" in available else pick("idle")
            else:
                anim = pick("idle")

        results.append((anim, facing))

    # Replace the final SLEEP_TAIL stationary keypoints with sleep
    if "sleep" in available and len(waypoints) >= SLEEP_TAIL:
        tail_start = len(waypoints) - SLEEP_TAIL
        all_stationary = all(
            _dist(waypoints[j], waypoints[j + 1]) < HOP_DIST_PX
            for j in range(tail_start, len(waypoints) - 1)
        )
        if all_stationary:
            for j in range(tail_start, len(waypoints)):
                results[j] = ("sleep", results[j][1])

    return results


# ──────────────────────────────────────────────
# DEBUG VISUALISATION
# ──────────────────────────────────────────────

def save_debug_image(scene: dict,
                     floor_mask: np.ndarray,
                     waypoints: list,
                     anims: list,
                     output_path: str):
    canvas = scene["bg"].copy()

    # Floor mask — semi-transparent green tint
    tint = canvas.copy()
    overlay_colour = np.array([0, 120, 0], dtype=np.float32)
    tint[floor_mask] = (tint[floor_mask].astype(np.float32) * 0.5
                        + overlay_colour * 0.5).astype(np.uint8)
    canvas = tint

    # Connecting line
    for i in range(len(waypoints) - 1):
        cv2.line(canvas, waypoints[i], waypoints[i + 1], (200, 200, 200), 2, cv2.LINE_AA)

    # Keypoints
    FONT = cv2.FONT_HERSHEY_SIMPLEX
    for i, (x, y) in enumerate(waypoints):
        anim, facing = anims[i]
        d = float(scene["depth_m"][min(max(y, 0), scene["h"] - 1),
                                    min(max(x, 0), scene["w"] - 1)])
        cv2.circle(canvas, (x, y), 8, (50, 220, 255), -1)
        label = f"{i}:{anim} {'→' if facing == 'right' else '←'} {d:.2f}m"
        cv2.putText(canvas, label, (x + 10, y - 8),
                    FONT, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.imwrite(output_path, canvas)
    print(f"Debug image → {output_path}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def generate(scene_json: str,
             character_json: str,
             output_path: str,
             n_keypoints: int = 10,
             frame_spacing: int = 20,
             fps: int = 30,
             floor_y_frac: float = 0.45,
             max_depth_m: float = 2.0,
             path_style: str = "sweep",
             start_y_frac: float = 0.90,
             end_y_frac: float = 0.55,
             seed: int = 42,
             visualize: bool = False):
    """
    start_y_frac / end_y_frac control where the diagonal path begins and
    ends vertically (as a fraction of image height). The defaults sweep
    from near the bottom of the image (0.90 * h, close to camera) up toward
    the middle (0.55 * h, deeper into the scene) — which produces a natural
    perspective walk across a desk or floor.

    Set both to the same value for a flat horizontal path.
    """
    print(f"Loading scene: {scene_json}")
    scene = load_scene(scene_json)
    print(f"  Image: {scene['w']}x{scene['h']}  "
          f"near_depth={scene['near_depth_m']:.2f}m  "
          f"objects={len(scene['objects'])}")

    # Load available animations from character.json
    available = ["idle", "hop"]
    if os.path.exists(character_json):
        with open(character_json) as f:
            char_data = json.load(f)
        if "animations" in char_data:
            available = sorted(char_data["animations"].keys())
    print(f"  Animations: {available}")

    print(f"\nBuilding floor mask (y >= {floor_y_frac*100:.0f}% of image, "
          f"depth <= {max_depth_m}m)...")
    floor_mask = build_floor_mask(scene, floor_y_frac, max_depth_m)
    n_floor_px = int(floor_mask.sum())
    print(f"  Walkable floor pixels: {n_floor_px:,}")
    if n_floor_px < 100:
        raise RuntimeError(
            "Too few walkable floor pixels. Try lowering --floor-y-frac "
            "or raising --max-depth."
        )

    print(f"\nTracing floor profile...")
    profile = trace_floor_profile(floor_mask, scene["h"], scene["w"])
    y_mins = [v[0] for v in profile.values()]
    y_maxs = [v[1] for v in profile.values()]
    print(f"  Profile spans x=[{min(profile)}, {max(profile)}]  "
          f"y_min=[{min(y_mins)}, {max(y_mins)}]  "
          f"y_max=[{min(y_maxs)}, {max(y_maxs)}]")

    start_y = int(scene["h"] * start_y_frac)
    end_y   = int(scene["h"] * end_y_frac)
    print(f"\nSampling {n_keypoints} waypoints (style={path_style}, "
          f"start_y={start_y}, end_y={end_y})...")
    waypoints = sample_path(profile, scene["w"], n_keypoints, path_style,
                            start_y, end_y, seed)

    print(f"\nAssigning animations...")
    anims = assign_animations(waypoints, scene["objects"], available)

    # Build keypoints with explicit depth_m
    depth_m_map = scene["depth_m"]
    keypoints   = []
    print(f"\n{'#':<4}  {'frame':>5}  {'pos':^16}  {'depth':>7}  "
          f"{'animation':<16}  facing")
    print("-" * 65)
    for i, ((x, y), (anim, facing)) in enumerate(zip(waypoints, anims)):
        yc = min(max(y, 0), scene["h"] - 1)
        xc = min(max(x, 0), scene["w"] - 1)
        d  = round(float(depth_m_map[yc, xc]), 4)
        frame = i * frame_spacing

        kp = {
            "frame":         frame,
            "foot_position": [x, y],
            "depth_m":       d,
            "facing":        facing,
            "animation":     anim,
        }
        keypoints.append(kp)
        pos = f"({x},{y})"
        print(f"{i:<4}  {frame:>5}  {pos:^16}  {d:>6.3f}m  "
              f"{anim:<16}  {facing}")

    trajectory = {
        "trajectory": {
            "scene_ref":     scene_json,
            "character_ref": character_json,
            "fps":           fps,
            "keypoints":     keypoints,
        }
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(trajectory, f, indent=2)
    print(f"\nSaved → {output_path}")

    if visualize:
        debug_path = str(Path(output_path).with_suffix(".debug.png"))
        save_debug_image(scene, floor_mask, waypoints, anims, debug_path)

    return output_path


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--scene-json",     required=True)
    parser.add_argument("--character-json", required=True)
    parser.add_argument("--output",         required=True)
    parser.add_argument("--n-keypoints",    type=int,   default=10)
    parser.add_argument("--frame-spacing",  type=int,   default=20)
    parser.add_argument("--fps",            type=int,   default=30)
    parser.add_argument("--floor-y-frac",   type=float, default=0.45,
                        help="Top of floor search band as fraction of image "
                             "height (default 0.45 = lower 55%%).")
    parser.add_argument("--max-depth",      type=float, default=2.0,
                        help="Exclude floor pixels deeper than this (metres).")
    parser.add_argument("--path-style",     default="sweep",
                        choices=["sweep", "return", "wander"])
    parser.add_argument("--start-y-frac",   type=float, default=0.90,
                        help="Vertical start of the path as a fraction of "
                             "image height. 0.9 = near the bottom (close to "
                             "camera). Default: 0.90.")
    parser.add_argument("--end-y-frac",     type=float, default=0.55,
                        help="Vertical end of the path as a fraction of "
                             "image height. 0.55 = middle of image (deeper "
                             "into the scene). Default: 0.55.")
    parser.add_argument("--seed",           type=int,   default=42)
    parser.add_argument("--visualize",      action="store_true",
                        help="Write a debug PNG showing the floor and path.")
    args = parser.parse_args()

    generate(
        scene_json=args.scene_json,
        character_json=args.character_json,
        output_path=args.output,
        n_keypoints=args.n_keypoints,
        frame_spacing=args.frame_spacing,
        fps=args.fps,
        floor_y_frac=args.floor_y_frac,
        max_depth_m=args.max_depth,
        path_style=args.path_style,
        start_y_frac=args.start_y_frac,
        end_y_frac=args.end_y_frac,
        seed=args.seed,
        visualize=args.visualize,
    )
