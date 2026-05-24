"""
geometry.py

Spatial utilities for the compositor:
  - Trajectory interpolation from keypoint format
  - Perspective scale from ground plane
  - Surface normal and perspective lean
  - Foot position → character bounding box
"""

import cv2
import numpy as np
import json


# ──────────────────────────────────────────────
# TRAJECTORY
# ──────────────────────────────────────────────

def load_trajectory(trajectory_json_path: str) -> dict:
    with open(trajectory_json_path) as f:
        return json.load(f)["trajectory"]


def interpolate_trajectory(keypoints: list, total_frames: int) -> list:
    """
    Given sparse keypoints [{frame, foot_position, facing, animation,
    depth_m?, on_top_of?}, ...], return a per-frame list of dicts
    with all fields interpolated or carried forward as appropriate.

    Interpolation behavior:
      - foot_position: linearly interpolated between surrounding keypoints
      - facing / animation: step function — held from the most recent
        keypoint until the next change
      - depth_m: linearly interpolated between two surrounding keypoints
        ONLY IF BOTH have a value. If either neighbour is unannotated,
        the value is None (compositor falls back to depth-map sampling).
        This is deliberately stricter than the step-function fields:
        depth overrides are explicit semantic intent, not implicit
        propagation, so they don't carry forward past an unannotated
        keypoint.
      - on_top_of: step function — held until cleared with `on_top_of: null`
        or replaced. Same propagation rules as `animation` because the
        semantic meaning ("character is currently on this object") naturally
        persists across frames.

    Subtlety: `depth_m` and `on_top_of` are *independent* annotation
    paths. They don't blend. If keypoint K0 has `depth_m: 1.0` and K1
    has `on_top_of: obj_X`, the segment between them has neither
    annotation (no smooth depth transition) and the compositor uses the
    legacy depth-map sampling. To get a smooth transition, give both
    keypoints `depth_m` values explicitly.
    """
    if not keypoints:
        raise ValueError("Trajectory has no keypoints.")

    kps = sorted(keypoints, key=lambda k: k["frame"])

    def step_field(kp, name, default=None):
        """Read a field that uses step-function propagation."""
        return kp.get(name, default)

    def interp_depth(k0, k1, t):
        """
        Linear interp of depth_m, but only across segments where both
        endpoints are annotated. At exact keypoint frames (t=0 or t=1)
        we return the endpoint's own value if it has one, even if the
        other endpoint doesn't — annotated keypoints always express their
        author's intent at that frame.
        """
        d0 = k0.get("depth_m")
        d1 = k1.get("depth_m")
        if t == 0:
            return None if d0 is None else float(d0)
        if t == 1:
            return None if d1 is None else float(d1)
        if d0 is None or d1 is None:
            return None
        return float(d0) + t * (float(d1) - float(d0))

    frames = []
    for i in range(total_frames):
        before = [k for k in kps if k["frame"] <= i]
        after  = [k for k in kps if k["frame"] >  i]

        if not before:
            kp = kps[0]
            frames.append({
                "foot_position": tuple(kp["foot_position"]),
                "facing":        step_field(kp, "facing", "right"),
                "animation":     step_field(kp, "animation", "walk"),
                "depth_m":       kp.get("depth_m"),
                "on_top_of":     step_field(kp, "on_top_of"),
            })
            continue

        if not after:
            kp = kps[-1]
            frames.append({
                "foot_position": tuple(kp["foot_position"]),
                "facing":        step_field(kp, "facing", "right"),
                "animation":     step_field(kp, "animation", "idle"),
                "depth_m":       kp.get("depth_m"),
                "on_top_of":     step_field(kp, "on_top_of"),
            })
            continue

        k0 = before[-1]
        k1 = after[0]
        t  = (i - k0["frame"]) / max(k1["frame"] - k0["frame"], 1)

        x = int(k0["foot_position"][0] + t * (k1["foot_position"][0] - k0["foot_position"][0]))
        y = int(k0["foot_position"][1] + t * (k1["foot_position"][1] - k0["foot_position"][1]))

        frames.append({
            "foot_position": (x, y),
            "facing":        step_field(k0, "facing", "right"),
            "animation":     step_field(k0, "animation", "walk"),
            "depth_m":       interp_depth(k0, k1, t),
            "on_top_of":     step_field(k0, "on_top_of"),
        })

    return frames


# ──────────────────────────────────────────────
# PERSPECTIVE SCALE
# ──────────────────────────────────────────────

def compute_scale_from_depth(current_depth_m: float,
                              near_depth_m: float,
                              global_scale: float) -> float:
    """
    Scale the character so it appears correctly sized at current_depth_m,
    calibrated so that at near_depth_m it renders at global_scale.
    """
    if current_depth_m <= 0:
        return global_scale
    return (near_depth_m / current_depth_m) * global_scale


# ──────────────────────────────────────────────
# SURFACE NORMAL / PERSPECTIVE LEAN
# ──────────────────────────────────────────────

def get_stable_normal(depth_map: np.ndarray, x: int, y: int, window: int = 15):
    h, w = depth_map.shape
    y1, y2 = max(0, y - window), min(h, y + window)
    x1, x2 = max(0, x - window), min(w, x + window)
    patch = depth_map[y1:y2, x1:x2].astype(np.float32)
    dy, dx = np.gradient(patch)
    normal = np.array([-np.mean(dx), -np.mean(dy), 1.0])
    norm = np.linalg.norm(normal)
    return normal / norm if norm > 0 else np.array([0.0, 0.0, 1.0])


def apply_perspective_lean(img: np.ndarray,
                            mask: np.ndarray,
                            normal: np.ndarray,
                            scale: float):
    h, w = img.shape[:2]
    pts1 = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
    tilt_x = normal[0] * w * 0.15
    tilt_y = normal[1] * h * 0.15
    pts2 = np.float32([[tilt_x, tilt_y], [w + tilt_x, tilt_y], [0, h], [w, h]])
    M = cv2.getPerspectiveTransform(pts1, pts2)
    warped_img  = cv2.warpPerspective(img,  M, (w, h))
    warped_mask = cv2.warpPerspective(mask, M, (w, h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(warped_img, (nw, nh)), cv2.resize(warped_mask, (nw, nh))


# ──────────────────────────────────────────────
# FOOT POSITION → CHARACTER BOUNDING BOX
# ──────────────────────────────────────────────

def foot_to_bbox(foot_x: int, foot_y: int,
                 char_w: int, char_h: int,
                 foot_offset_x_frac: float,
                 foot_offset_y_frac: float) -> tuple:
    """
    Given the foot position in scene coordinates and the scaled character
    dimensions, compute the top-left corner of the character bounding box.

    foot_offset_x_frac / foot_offset_y_frac: fractional position of the
    foot anchor within the sprite (e.g. 0.5, 0.95 = bottom-centre).
    """
    x1 = foot_x - int(char_w * foot_offset_x_frac)
    y1 = foot_y - int(char_h * foot_offset_y_frac)
    return x1, y1