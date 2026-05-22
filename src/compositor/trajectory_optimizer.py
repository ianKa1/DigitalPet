"""
trajectory_optimizer.py

Post-processes any trajectory JSON to handle object bounding-box intersections.

For each segment that crosses an object's bounding box the optimizer inserts
corrective keypoints so the creature visibly goes:

  front  — in front of the object  (depth_m set slightly < obj.base_depth_m,
                                    path x,y unchanged)
  behind — behind the object        (depth_m set slightly > obj.base_depth_m,
                                    path x,y unchanged)
  ontop  — climbs to the top of the bounding box and walks across the surface
  around — detours above the bounding box top (inserts bypass waypoints)
  auto   — depth-based: front if path depth < obj.base_depth_m, else behind

The explicit depth_m values set by the optimizer are read directly by the
compositor (which skips depth-map sampling for frames that already have them),
so front/behind rendering is unambiguous at every crossing frame.

Usage
─────
  python -m src.compositor.trajectory_optimizer \\
      --trajectory-json  scene_input/auto_trajectory.json \\
      --scene-json        output/scenes/desk/processed_scene/scene_processed.json \\
      --output            scene_input/optimized_trajectory.json \\
      --strategy          auto \\
      --visualize
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


# ──────────────────────────────────────────────
# TUNABLE DEFAULTS
# ──────────────────────────────────────────────

DEPTH_MARGIN  = 0.04   # metres — depth offset for front / behind strategies
AROUND_MARGIN = 30     # pixels above bbox top for the "around" detour

STRATEGY_COLOURS = {
    "front":  ( 50, 200,  50),   # green
    "behind": ( 50, 100, 220),   # blue
    "ontop":  (255, 160,  30),   # orange
    "around": (180,  50, 220),   # purple
}


# ──────────────────────────────────────────────
# GEOMETRY HELPERS
# ──────────────────────────────────────────────

def liang_barsky(p1, p2, xmin, ymin, xmax, ymax):
    """
    Liang-Barsky segment clipping.
    Returns (t_enter, t_exit) in [0, 1] along the segment, or None if the
    segment does not intersect the axis-aligned bounding box.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    ps = [-dx,  dx, -dy,  dy]
    qs = [p1[0] - xmin, xmax - p1[0],
          p1[1] - ymin, ymax - p1[1]]

    t0, t1 = 0.0, 1.0
    for p, q in zip(ps, qs):
        if abs(p) < 1e-9:
            if q < 0:
                return None        # parallel and outside
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)

    return (t0, t1) if t0 <= t1 else None


def lerp_xy(kp0, kp1, t):
    x = int(round(kp0["foot_position"][0]
                  + t * (kp1["foot_position"][0] - kp0["foot_position"][0])))
    y = int(round(kp0["foot_position"][1]
                  + t * (kp1["foot_position"][1] - kp0["foot_position"][1])))
    return x, y


def lerp_frame(kp0, kp1, t):
    return int(round(kp0["frame"] + t * (kp1["frame"] - kp0["frame"])))


def sample_depth(depth_m, x, y, h, w):
    return float(depth_m[min(max(y, 0), h - 1),
                          min(max(x, 0), w - 1)])


def path_depth_at_t(kp0, kp1, t, depth_m, h, w):
    """
    Linearly interpolated depth along the segment at parametric position t.

    Priority:
      both explicit   → interpolate between them (smooth, no noise)
      only d0         → hold d0 (natural: depth constant until next keypoint)
      only d1         → return d1 (avoids a noisy depth-map sample that would
                        not match d1, causing a jump at the transition frame)
      neither         → sample the depth map at the interpolated (x, y)
    """
    d0 = kp0.get("depth_m")
    d1 = kp1.get("depth_m")
    if d0 is not None and d1 is not None:
        return d0 + t * (d1 - d0)
    if d0 is not None:
        return d0
    if d1 is not None:
        return d1
    x, y = lerp_xy(kp0, kp1, t)
    return sample_depth(depth_m, x, y, h, w)


def facing_for_segment(kp0, kp1):
    return "right" if kp1["foot_position"][0] >= kp0["foot_position"][0] else "left"


# ──────────────────────────────────────────────
# KEYPOINT FACTORY
# ──────────────────────────────────────────────

def make_kp(x, y, frame, depth_m_val, facing, animation):
    return {
        "frame":         frame,
        "foot_position": [x, y],
        "depth_m":       round(float(depth_m_val), 4) if depth_m_val is not None else None,
        "facing":        facing,
        "animation":     animation,
    }


# ──────────────────────────────────────────────
# INTERSECTION DETECTION
# ──────────────────────────────────────────────

def find_intersections(keypoints, objects):
    """
    For every consecutive segment and every object bounding box, check
    whether the segment crosses the box (Liang-Barsky).

    Returns a list of intersection dicts sorted by (seg_idx, t_enter):
        seg_idx   — index of the segment start keypoint
        obj       — the object dict
        t_enter   — parametric entry into bbox [0, 1]
        t_exit    — parametric exit from bbox
        enter_xy  — (x, y) at entry
        exit_xy   — (x, y) at exit
        mid_xy    — (x, y) at midpoint
        strategy  — filled in later by decide_strategy()
    """
    hits = []
    for i in range(len(keypoints) - 1):
        p0 = tuple(keypoints[i]["foot_position"])
        p1 = tuple(keypoints[i + 1]["foot_position"])

        for obj in objects:
            clip = liang_barsky(p0, p1,
                                obj["x_min"], obj["y_min"],
                                obj["x_max"], obj["y_max"])
            if clip is None:
                continue

            t_enter, t_exit = clip
            t_mid   = (t_enter + t_exit) / 2.0
            enter_x = int(round(p0[0] + t_enter * (p1[0] - p0[0])))
            enter_y = int(round(p0[1] + t_enter * (p1[1] - p0[1])))
            exit_x  = int(round(p0[0] + t_exit  * (p1[0] - p0[0])))
            exit_y  = int(round(p0[1] + t_exit  * (p1[1] - p0[1])))
            mid_x   = int(round(p0[0] + t_mid   * (p1[0] - p0[0])))
            mid_y   = int(round(p0[1] + t_mid   * (p1[1] - p0[1])))

            hits.append({
                "seg_idx":  i,
                "obj":      obj,
                "t_enter":  t_enter,
                "t_exit":   t_exit,
                "t_mid":    t_mid,
                "enter_xy": (enter_x, enter_y),
                "exit_xy":  (exit_x,  exit_y),
                "mid_xy":   (mid_x,   mid_y),
                "strategy": None,
            })

    hits.sort(key=lambda h: (h["seg_idx"], h["t_enter"]))
    return hits


# ──────────────────────────────────────────────
# STRATEGY SELECTION
# ──────────────────────────────────────────────

def decide_strategy(ix, keypoints, depth_m, h, w, global_strategy):
    if global_strategy != "auto":
        return global_strategy

    kp0 = keypoints[ix["seg_idx"]]
    kp1 = keypoints[ix["seg_idx"] + 1]
    path_d = path_depth_at_t(kp0, kp1, ix["t_mid"], depth_m, h, w)
    return "front" if path_d < ix["obj"]["base_depth_m"] else "behind"


# ──────────────────────────────────────────────
# REROUTING — NEW KEYPOINTS PER STRATEGY
# ──────────────────────────────────────────────

def _kps_front_behind(kp0, kp1, ix, depth_m, h, w, depth_margin, strategy):
    """
    Path x,y unchanged. Insert entry and exit keypoints with depth_m set to
    keep the creature consistently in front of or behind the object.

    The depth at each inserted keypoint is the natural linearly interpolated
    depth of the segment at that t, then clamped so it is guaranteed to be
    on the correct side of the object:
      front  → min(natural_d, obj_d - margin)   never deeper than obj
      behind → max(natural_d, obj_d + margin)   never shallower than obj

    Clamping rather than replacing preserves the overall depth trajectory —
    if the creature is already clearly in front, the natural depth is kept
    unchanged and no sudden jump is introduced.
    """
    obj_d  = ix["obj"]["base_depth_m"]
    facing = facing_for_segment(kp0, kp1)
    anim   = kp0.get("animation", "hop")

    kps = []
    for t, xy in [(ix["t_enter"], ix["enter_xy"]),
                  (ix["t_exit"],  ix["exit_xy"])]:
        natural_d = path_depth_at_t(kp0, kp1, t, depth_m, h, w)
        if strategy == "front":
            d = min(natural_d, obj_d - depth_margin)
        else:
            d = max(natural_d, obj_d + depth_margin)
        kps.append(make_kp(*xy, lerp_frame(kp0, kp1, t), d, facing, anim))

    return kps


def _kps_ontop(kp0, kp1, ix, depth_m, h, w):
    """
    Route the creature over the object's top edge.

    Three keypoints are inserted:
      entry  — at the bbox's left edge,  y snapped to obj.y_min, depth from surface
      mid    — at the bbox midpoint x,   y = obj.y_min, idle animation
      exit   — at the bbox's right edge, y = obj.y_min, depth from surface

    The compositor's linear interpolation from the previous keypoint
    (at normal path y) to the entry keypoint creates the climbing motion,
    and from the exit keypoint back to the next original keypoint creates
    the descent.
    """
    obj    = ix["obj"]
    top_y  = obj["y_min"]
    facing = facing_for_segment(kp0, kp1)

    # Sample depth across the top edge to get a stable surface depth
    sample_xs   = [obj["x_min"],
                   (obj["x_min"] + obj["x_max"]) // 2,
                   obj["x_max"]]
    surface_d   = float(np.median([
        sample_depth(depth_m, sx, max(0, top_y), h, w) for sx in sample_xs
    ]))

    return [
        make_kp(ix["enter_xy"][0], top_y,
                lerp_frame(kp0, kp1, ix["t_enter"]),
                surface_d, facing, "hop"),
        make_kp(ix["mid_xy"][0],   top_y,
                lerp_frame(kp0, kp1, ix["t_mid"]),
                surface_d, facing, "idle"),
        make_kp(ix["exit_xy"][0],  top_y,
                lerp_frame(kp0, kp1, ix["t_exit"]),
                surface_d, facing, "hop"),
    ]


def _kps_around(kp0, kp1, ix, depth_m, h, w, around_margin):
    """
    Detour above the bounding box (smaller y = deeper into the scene).
    Three keypoints track the detour path just above obj.y_min.
    """
    obj    = ix["obj"]
    top_y  = max(0, obj["y_min"] - around_margin)
    facing = facing_for_segment(kp0, kp1)

    kps = []
    for t, x in [(ix["t_enter"], ix["enter_xy"][0]),
                 (ix["t_mid"],   ix["mid_xy"][0]),
                 (ix["t_exit"],  ix["exit_xy"][0])]:
        # Interpolate depth from the original segment rather than sampling
        # the depth map at top_y — point samples are noisy and don't match
        # the surrounding keypoints' depths, causing per-keypoint jumps.
        d = path_depth_at_t(kp0, kp1, t, depth_m, h, w)
        kps.append(make_kp(x, top_y, lerp_frame(kp0, kp1, t), d, facing, "hop"))

    return kps


# ──────────────────────────────────────────────
# FRAME DEDUPLICATION
# ──────────────────────────────────────────────

def deduplicate_frames(keypoints):
    """
    Guarantee strictly increasing frame numbers after insertion.
    When two adjacent keypoints land on the same frame, nudge the later
    one (and all subsequent ones that are still equal) by +1.
    """
    if not keypoints:
        return keypoints
    out = [dict(keypoints[0])]
    for kp in keypoints[1:]:
        kp = dict(kp)
        kp["frame"] = max(kp["frame"], out[-1]["frame"] + 1)
        out.append(kp)
    return out


# ──────────────────────────────────────────────
# MAIN OPTIMIZER
# ──────────────────────────────────────────────

def optimize(trajectory_json, scene_json, output_path,
             strategy="auto",
             depth_margin=DEPTH_MARGIN,
             around_margin=AROUND_MARGIN,
             visualize=False):

    # ── Load trajectory ──────────────────────
    with open(trajectory_json) as f:
        traj_root = json.load(f)
    traj_data  = traj_root["trajectory"]
    keypoints  = traj_data["keypoints"]
    print(f"Trajectory  : {len(keypoints)} keypoints  ({trajectory_json})")

    # ── Load scene ───────────────────────────
    with open(scene_json) as f:
        scene_data = json.load(f)

    image_path = scene_data["scene"]["image_path"]
    bg = cv2.imread(image_path)
    if bg is None:
        raise FileNotFoundError(f"Scene image not found: {image_path}")
    h, w = bg.shape[:2]

    depth_path = (scene_data.get("depth_map_path")
                  or scene_data["scene"].get("depth_map_path"))
    if not depth_path or not os.path.exists(depth_path):
        raise FileNotFoundError(
            f"Depth map not found: {depth_path}. Run scene_preprocessor first."
        )
    depth_m = np.load(depth_path).astype(np.float32)
    if depth_m.shape[:2] != (h, w):
        depth_m = cv2.resize(depth_m, (w, h), interpolation=cv2.INTER_LINEAR)

    objects = [
        {
            "id":           obj["id"],
            "x_min":        int(obj.get("x_min", 0)),
            "x_max":        int(obj.get("x_max", w)),
            "y_min":        int(obj.get("y_min", 0)),
            "y_max":        int(obj.get("y_max", h)),
            "base_depth_m": float(obj.get("base_depth_m", 1.0)),
        }
        for obj in scene_data.get("objects", [])
    ]
    print(f"Scene       : {len(objects)} objects  ({scene_json})")

    # ── Detect intersections ─────────────────
    intersections = find_intersections(keypoints, objects)
    print(f"\nIntersections found: {len(intersections)}")

    if not intersections:
        print("No intersections — output trajectory is unchanged.")
        _write(traj_data, keypoints, output_path)
        if visualize:
            _visualize(bg, keypoints, keypoints, [], objects,
                       str(Path(output_path).with_suffix(".debug.png")))
        return output_path

    # ── Assign strategies ────────────────────
    for ix in intersections:
        ix["strategy"] = decide_strategy(ix, keypoints, depth_m, h, w, strategy)
        kp0 = keypoints[ix["seg_idx"]]
        kp1 = keypoints[ix["seg_idx"] + 1]
        print(f"  seg {ix['seg_idx']:>2}→{ix['seg_idx']+1:<2}  "
              f"obj={ix['obj']['id']}  "
              f"depth={ix['obj']['base_depth_m']:.3f}m  "
              f"t=[{ix['t_enter']:.2f},{ix['t_exit']:.2f}]  "
              f"→ {ix['strategy']}")

    # ── Build rerouted keypoint list ─────────
    by_seg = defaultdict(list)
    for ix in intersections:
        by_seg[ix["seg_idx"]].append(ix)

    result = []
    for i, kp in enumerate(keypoints):
        result.append(kp)

        if i >= len(keypoints) - 1 or i not in by_seg:
            continue

        kp0 = keypoints[i]
        kp1 = keypoints[i + 1]

        # Collect all new keypoints for this segment across all intersections,
        # then sort by frame. Without this sort, overlapping bounding boxes
        # produce keypoints whose spatial positions are out of frame order:
        # exit_A (t=0.6, x=60) would precede enter_B (t=0.4, x=40) in the
        # list, causing the interpolator to walk backwards.
        seg_new_kps = []
        for ix in sorted(by_seg[i], key=lambda x: x["t_enter"]):
            strat = ix["strategy"]
            if strat in ("front", "behind"):
                new_kps = _kps_front_behind(kp0, kp1, ix,
                                            depth_m, h, w, depth_margin, strat)
            elif strat == "ontop":
                new_kps = _kps_ontop(kp0, kp1, ix, depth_m, h, w)
            elif strat == "around":
                new_kps = _kps_around(kp0, kp1, ix, depth_m, h, w, around_margin)
            else:
                continue
            seg_new_kps.extend(new_kps)

        # Sort by frame so that spatial positions are monotonically ordered
        # even when bboxes overlap. Deduplicate_frames will then only need
        # to nudge duplicate integers, not reorder.
        seg_new_kps.sort(key=lambda kp: kp["frame"])
        result.extend(seg_new_kps)

    # Final sort + dedup: belt-and-suspenders guard against any remaining
    # frame collisions introduced by integer rounding of lerp_frame.
    result.sort(key=lambda kp: kp["frame"])
    result = deduplicate_frames(result)

    delta = len(result) - len(keypoints)
    print(f"\nOptimized   : {len(result)} keypoints  ({delta:+d} inserted)")

    # ── Write output ─────────────────────────
    _write(traj_data, result, output_path)

    # ── Visualise ────────────────────────────
    if visualize:
        _visualize(bg, keypoints, result, intersections, objects,
                   str(Path(output_path).with_suffix(".debug.png")))

    return output_path


def _write(traj_data, keypoints, output_path):
    out = {"trajectory": {**traj_data, "keypoints": keypoints}}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved       → {output_path}")


# ──────────────────────────────────────────────
# VISUALISATION
# ──────────────────────────────────────────────

def _visualize(bg, original_kps, optimized_kps, intersections, objects, out_path):
    canvas = bg.copy()
    FONT   = cv2.FONT_HERSHEY_SIMPLEX

    # Build lookup: which objects were intersected, and with what strategy
    obj_strategy = {}
    for ix in intersections:
        obj_strategy[ix["obj"]["id"]] = ix["strategy"]

    # ── Object bounding boxes ────────────────
    for obj in objects:
        strat  = obj_strategy.get(obj["id"])
        colour = STRATEGY_COLOURS.get(strat, (80, 80, 80))
        thick  = 2 if strat else 1
        cv2.rectangle(canvas,
                      (obj["x_min"], obj["y_min"]),
                      (obj["x_max"], obj["y_max"]),
                      colour, thick)
        if strat:
            label = f"{obj['id']} [{strat}]  {obj['base_depth_m']:.2f}m"
            (tw, th), _ = cv2.getTextSize(label, FONT, 0.38, 1)
            lx = obj["x_min"] + 3
            ly = obj["y_min"] + th + 3
            cv2.rectangle(canvas, (lx - 2, ly - th - 2),
                          (lx + tw + 2, ly + 2), (20, 20, 20), -1)
            cv2.putText(canvas, label, (lx, ly), FONT, 0.38, colour, 1, cv2.LINE_AA)

    # ── Original path — dashed grey ──────────
    for i in range(len(original_kps) - 1):
        p0 = tuple(original_kps[i]["foot_position"])
        p1 = tuple(original_kps[i + 1]["foot_position"])
        pts = np.linspace(p0, p1, 24, dtype=int)
        for j in range(0, len(pts) - 1, 2):
            cv2.line(canvas, tuple(pts[j]), tuple(pts[j + 1]),
                     (110, 110, 110), 1, cv2.LINE_AA)
    for kp in original_kps:
        cv2.circle(canvas, tuple(kp["foot_position"]), 5, (110, 110, 110), -1)

    # ── Optimized path — coloured by strategy ─
    orig_positions = {tuple(kp["foot_position"]) for kp in original_kps}

    # Colour each optimized segment by the strategy of any intersection whose
    # frame range it falls within
    seg_frame_ranges = {}
    for ix in intersections:
        f0 = original_kps[ix["seg_idx"]]["frame"]
        f1 = original_kps[ix["seg_idx"] + 1]["frame"]
        seg_frame_ranges[(f0, f1)] = ix["strategy"]

    def segment_colour(f_start, f_end):
        for (f0, f1), strat in seg_frame_ranges.items():
            if not (f_end < f0 or f_start > f1):
                return STRATEGY_COLOURS[strat]
        return (230, 230, 230)

    for i in range(len(optimized_kps) - 1):
        p0 = tuple(optimized_kps[i]["foot_position"])
        p1 = tuple(optimized_kps[i + 1]["foot_position"])
        col = segment_colour(optimized_kps[i]["frame"],
                             optimized_kps[i + 1]["frame"])
        cv2.line(canvas, p0, p1, col, 2, cv2.LINE_AA)

    # Draw keypoints — inserted ones are larger and brighter
    for kp in optimized_kps:
        pt      = tuple(kp["foot_position"])
        is_new  = pt not in orig_positions
        radius  = 8 if is_new else 5
        colour  = (50, 220, 255) if is_new else (200, 200, 60)
        cv2.circle(canvas, pt, radius, colour, -1)

        if is_new:
            d_str = f"{kp['depth_m']:.2f}m" if kp.get("depth_m") is not None else ""
            label = f"{kp.get('animation','?')} {d_str}".strip()
            cv2.putText(canvas, label, (pt[0] + 10, pt[1] - 6),
                        FONT, 0.38, colour, 1, cv2.LINE_AA)

    # ── Legend ───────────────────────────────
    entries = [
        ("original path",   (110, 110, 110)),
        ("inserted point",  ( 50, 220, 255)),
        *[(f"strategy: {s}", c) for s, c in STRATEGY_COLOURS.items()],
    ]
    y = 20
    for label, col in entries:
        cv2.rectangle(canvas, (10, y - 8), (22, y + 4), col, -1)
        cv2.putText(canvas, label, (28, y + 4), FONT, 0.40,
                    (240, 240, 240), 1, cv2.LINE_AA)
        y += 20

    cv2.imwrite(out_path, canvas)
    print(f"Debug image → {out_path}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--trajectory-json", required=True,
                        help="Input trajectory JSON (hand-authored or auto-generated)")
    parser.add_argument("--scene-json",       required=True,
                        help="scene_processed.json from scene_preprocessor")
    parser.add_argument("--output",           required=True,
                        help="Output trajectory JSON path")
    parser.add_argument("--strategy",         default="auto",
                        choices=["auto", "front", "behind", "ontop", "around"],
                        help="Rerouting strategy applied to all intersections. "
                             "'auto' uses depth comparison (default).")
    parser.add_argument("--depth-margin",     type=float, default=DEPTH_MARGIN,
                        help=f"Depth offset (m) used for front/behind strategies "
                             f"(default {DEPTH_MARGIN})")
    parser.add_argument("--around-margin",    type=int,   default=AROUND_MARGIN,
                        help=f"Pixels above bbox top for the 'around' detour "
                             f"(default {AROUND_MARGIN})")
    parser.add_argument("--visualize",        action="store_true",
                        help="Write a debug PNG next to the output JSON showing "
                             "object bboxes, original path (grey dashed), and "
                             "rerouted path (coloured by strategy)")
    args = parser.parse_args()

    optimize(
        trajectory_json=args.trajectory_json,
        scene_json=args.scene_json,
        output_path=args.output,
        strategy=args.strategy,
        depth_margin=args.depth_margin,
        around_margin=args.around_margin,
        visualize=args.visualize,
    )
