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
    Given sparse keypoints [{frame, foot_position, facing, animation, depth_m?}, ...],
    return a per-frame list of dicts with all fields interpolated or
    carried forward as appropriate.

    - foot_position: linearly interpolated
    - depth_m:       linearly interpolated when both surrounding keypoints
                     have it; held from the previous keypoint when only one
                     does; None when neither does (compositor falls back to
                     depth-map sampling for those frames)
    - facing / animation: held from last keypoint (step function)
    """
    if not keypoints:
        raise ValueError("Trajectory has no keypoints.")

    # Sort by frame just in case
    kps = sorted(keypoints, key=lambda k: k["frame"])

    frames = []
    for i in range(total_frames):
        # Find surrounding keypoints
        before = [k for k in kps if k["frame"] <= i]
        after  = [k for k in kps if k["frame"] >  i]

        if not before:
            # Before first keypoint — clamp to first
            kp = kps[0]
            frames.append({
                "foot_position": tuple(kp["foot_position"]),
                "depth_m":       kp.get("depth_m"),
                "facing":        kp.get("facing", "right"),
                "animation":     kp.get("animation", "walk"),
            })
            continue

        if not after:
            # After last keypoint — clamp to last
            kp = kps[-1]
            frames.append({
                "foot_position": tuple(kp["foot_position"]),
                "depth_m":       kp.get("depth_m"),
                "facing":        kp.get("facing", "right"),
                "animation":     kp.get("animation", "idle"),
            })
            continue

        k0 = before[-1]
        k1 = after[0]
        t  = (i - k0["frame"]) / max(k1["frame"] - k0["frame"], 1)

        x = int(k0["foot_position"][0] + t * (k1["foot_position"][0] - k0["foot_position"][0]))
        y = int(k0["foot_position"][1] + t * (k1["foot_position"][1] - k0["foot_position"][1]))

        d0 = k0.get("depth_m")
        d1 = k1.get("depth_m")
        if d0 is not None and d1 is not None:
            depth_m = d0 + t * (d1 - d0)   # smooth linear interpolation
        elif d0 is not None:
            depth_m = d0                    # hold — no target yet
        elif d1 is not None:
            depth_m = d1                    # hold forward — approaching explicit region.
                                            # Prevents a depth jump at the boundary frame
                                            # where the compositor would otherwise switch
                                            # from a sampled value to the explicit d1.
        else:
            depth_m = None                  # both sides unset — compositor samples

        frames.append({
            "foot_position": (x, y),
            "depth_m":       depth_m,
            "facing":        k0.get("facing", "right"),
            "animation":     k0.get("animation", "walk"),
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
