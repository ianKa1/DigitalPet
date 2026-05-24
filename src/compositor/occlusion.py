"""
occlusion.py

Per-object occlusion state machine and alpha computation.

  Occlusion principle:
    - Character's depth is determined by its foot position on the scene
      depth map. One stable depth value per frame.
    - For each scene object whose mask overlaps the character bbox, the
      relevant object depth is sampled from the depth map at the actual
      OVERLAP REGION (where the sprite and object mask intersect) rather
      than the pre-computed ground-anchor median. This correctly handles
      tall objects (tissue box, monitor) and side-routing cases where the
      ground anchor is far from the actual intersection area.
    - Per-pixel via the object mask applies the decision, giving clean
      occlusion boundaries.

  State per object:
    IN_FRONT — character is in front, object does not occlude
    BEHIND   — character is behind, object mask occludes character

  One intersection episode = one decision. The decision is made when the
  intersection begins (using current + lookahead foot depths) and held
  until the character fully exits. This gives temporal stability — no
  per-pixel depth noise, no frame-to-frame flickering.
"""

import cv2
import numpy as np


# Erosion margin used in scene_preprocessor.py — keep in sync.
BOUNDARY_EROSION_PX = 10

IN_FRONT = 0
BEHIND   = 1


class ObjectOcclusionState:
    """One state machine per scene object, per character."""

    def __init__(self, obj: dict, depth_tolerance_m: float = 0.0):
        """
        Args:
            obj: scene object dict with 'mask' and 'base_depth_m'.
            depth_tolerance_m: stored for future use but not currently
                applied in _decide_state — the depth comparison remains
                strict (d > obj_depth) regardless of this value.
                Intended as a slop margin to absorb calibration noise
                from monocular depth estimation. Defaults to 0.
        """
        self.obj                = obj
        self.depth_tolerance_m  = depth_tolerance_m
        self.state              = IN_FRONT
        self.is_intersecting    = False

    def _bbox_intersects_mask(self, char_bbox: tuple) -> bool:
        ax1, ay1, ax2, ay2 = char_bbox
        mask = self.obj['mask']
        h, w = mask.shape
        ax1 = max(0, ax1); ay1 = max(0, ay1)
        ax2 = min(w, ax2); ay2 = min(h, ay2)
        if ax1 >= ax2 or ay1 >= ay2:
            return False
        return bool(np.any(mask[ay1:ay2, ax1:ax2] > 128))

    def _sample_overlap_depth(self, char_bbox: tuple,
                               depth_m: np.ndarray) -> float:
        """
        Median depth of the scene depth map restricted to pixels where the
        character bbox overlaps the object mask.

        This is more accurate than base_depth_m (which is the median at the
        object's bottom 10% pixels) for objects where the creature intersects
        the side or top rather than the ground anchor — e.g. routing around
        a tissue box, the relevant depth is the box's side, not its base.

        Falls back to base_depth_m if the overlap area is too small.
        """
        ax1, ay1, ax2, ay2 = char_bbox
        h, w = depth_m.shape[:2]
        ax1 = max(0, ax1); ay1 = max(0, ay1)
        ax2 = min(w, ax2); ay2 = min(h, ay2)
        if ax1 >= ax2 or ay1 >= ay2:
            return self.obj['base_depth_m']

        mask_roi  = self.obj['mask'][ay1:ay2, ax1:ax2]
        depth_roi = depth_m[ay1:ay2, ax1:ax2]
        overlap   = mask_roi > 128

        if overlap.sum() < 4:          # too few pixels — fall back to anchor
            return self.obj['base_depth_m']

        return float(np.median(depth_roi[overlap]))

    def _decide_state(self, foot_depth_m: float,
                      future_depths: list,
                      obj_depth: float) -> int:
        """
        Majority vote across current + lookahead foot depths vs obj_depth.
        Robust to single-frame depth noise.
        """
        all_depths   = [foot_depth_m] + list(future_depths)
        behind_count = sum(1 for d in all_depths if d > obj_depth)
        return BEHIND if behind_count * 2 > len(all_depths) else IN_FRONT

    def update(self, foot_x: int, foot_y: int,
               foot_depth_m: float, future_feet: list,
               char_bbox: tuple,
               depth_m: np.ndarray = None,
               forced_state: int = None) -> bool:
        """
        Intersection-based state transition:
          not intersecting → not intersecting: hold IN_FRONT
          not intersecting → intersecting:     decide once based on depth
          intersecting     → intersecting:     hold current state
          intersecting     → not intersecting: reset to IN_FRONT

        depth_m: scene metric depth map. When provided, the front/behind
                 decision uses the overlap-region median depth instead of
                 base_depth_m, giving correct results for non-ground-level
                 intersections.

        forced_state: if provided (IN_FRONT or BEHIND), overrides the
                 depth-comparison logic entirely. Used for semantic
                 trajectory annotations: when the trajectory says
                 `on_top_of: obj_X`, the character must remain IN_FRONT
                 regardless of how the sampled depth values compare.
        """
        intersecting = self._bbox_intersects_mask(char_bbox)

        if forced_state is not None:
            self.state = forced_state
        elif intersecting and not self.is_intersecting:
            future_depths = [fd[2] for fd in future_feet if len(fd) > 2]
            obj_depth = (self._sample_overlap_depth(char_bbox, depth_m)
                         if depth_m is not None
                         else self.obj['base_depth_m'])
            self.state = self._decide_state(foot_depth_m, future_depths,
                                            obj_depth)
        elif not intersecting and self.is_intersecting:
            self.state = IN_FRONT
        # else: hold

        self.is_intersecting = intersecting
        return self.state == BEHIND


def compute_occlusion_alpha(
    foot_x: int,
    foot_y: int,
    scene,
    bbox: tuple,
    occlusion_states: dict,
) -> np.ndarray:
    """
    Legacy per-object binary occlusion (kept for reference).
    Prefer compute_occlusion_alpha_per_pixel for new code.
    """
    ax1, ay1, ax2, ay2 = bbox
    roi_h = ay2 - ay1
    roi_w = ax2 - ax1

    if roi_h <= 0 or roi_w <= 0:
        return np.ones((roi_h, roi_w), dtype=np.float32)

    alpha = np.ones((roi_h, roi_w), dtype=np.float32)

    for obj in scene.objects:
        state = occlusion_states[obj["id"]]
        if state.state != BEHIND:
            continue

        obj_mask_roi = obj["mask"][ay1:ay2, ax1:ax2]
        if obj_mask_roi.shape != (roi_h, roi_w):
            obj_mask_roi = cv2.resize(obj_mask_roi, (roi_w, roi_h),
                                      interpolation=cv2.INTER_NEAREST)

        obj_active = (obj_mask_roi > 128).astype(np.float32)
        alpha = alpha * (1.0 - obj_active)

    return alpha


def compute_occlusion_alpha_per_pixel(
    foot_depth_m: float,
    scene,
    bbox: tuple,
    soft_band_m: float = 0.02,
) -> np.ndarray:
    """
    Per-pixel occlusion alpha derived directly from the scene depth map.

    For every pixel in the sprite ROI the scene depth is compared against
    the sprite's foot depth:

      scene_depth << foot_depth_m  →  scene is clearly in front  →  alpha = 0 (sprite hidden)
      scene_depth >> foot_depth_m  →  scene is behind            →  alpha = 1 (sprite visible)
      within soft_band_m of boundary →  smooth linear transition

    This replaces the per-object binary state machine.  It handles:
      - Partial occlusion at object edges automatically
      - Tall objects (tissue box, monitor) correctly: each pixel uses its
        own scene depth rather than the object's ground-anchor median
      - The creature routing around the SIDE of an object: scene depth at
        side pixels is whatever the depth map says there, not base_depth_m
      - No lookahead, no state machine, no base_depth_m required

    soft_band_m smooths over DepthAnything's blurry depth boundaries,
    preventing hard-edged artefacts where the depth map transitions.
    """
    ax1, ay1, ax2, ay2 = bbox
    roi_h = ay2 - ay1
    roi_w = ax2 - ax1

    if roi_h <= 0 or roi_w <= 0:
        return np.ones((max(0, roi_h), max(0, roi_w)), dtype=np.float32)

    scene_d = scene.depth_m[ay1:ay2, ax1:ax2]

    if soft_band_m > 0:
        # alpha smoothly goes 0→1 as scene depth crosses foot_depth_m.
        # Below (foot_depth_m - soft_band_m): fully occluded (alpha=0).
        # Above foot_depth_m: fully visible (alpha=1).
        alpha = np.clip(
            (scene_d - (foot_depth_m - soft_band_m)) / soft_band_m,
            0.0, 1.0
        ).astype(np.float32)
    else:
        alpha = (scene_d >= foot_depth_m).astype(np.float32)

    return alpha
