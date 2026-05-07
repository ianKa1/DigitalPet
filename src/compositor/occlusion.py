"""
occlusion.py

Per-object occlusion state machine and alpha computation.

  Occlusion principle:
    - Character's depth is determined by its foot position on the scene
      depth map. One stable depth value per frame.
    - Each scene object has a stable base_depth_m sampled at its ground
      anchor during preprocessing.
    - For each scene object whose mask overlaps the character bbox:
        if object.base_depth_m < character foot depth → object in front
            → pixels inside object mask occlude the character
        if object.base_depth_m > character foot depth → object behind
            → character occludes those pixels (no special handling)
    - Per-pixel via the object mask handles partial occlusion naturally
      (e.g. character walking behind a tree).

  State per object:
    IN_FRONT — character is in front, object does not occlude
    BEHIND   — character is behind, object mask occludes character

  One intersection episode = one decision. The decision is made when the
  intersection begins (using current + lookahead foot depths) and held
  until the character fully exits. This honours the trajectory assumption
  that the character does not teleport between front and back mid-overlap.
"""

import cv2
import numpy as np


# Erosion margin used in scene_preprocessor.py — keep in sync.
BOUNDARY_EROSION_PX = 10

IN_FRONT = 0
BEHIND   = 1


class ObjectOcclusionState:
    """One state machine per scene object, per character."""

    def __init__(self, obj: dict):
        self.obj             = obj
        self.state           = IN_FRONT
        self.is_intersecting = False

    def _bbox_intersects_mask(self, char_bbox: tuple) -> bool:
        ax1, ay1, ax2, ay2 = char_bbox
        mask = self.obj['mask']
        h, w = mask.shape
        ax1 = max(0, ax1); ay1 = max(0, ay1)
        ax2 = min(w, ax2); ay2 = min(h, ay2)
        if ax1 >= ax2 or ay1 >= ay2:
            return False
        return bool(np.any(mask[ay1:ay2, ax1:ax2] > 128))

    def _decide_state(self, foot_depth_m: float, future_depths: list) -> int:
        """
        Make one front/behind decision via majority vote across the
        lookahead window — robust to single-frame depth noise.
        """
        base_depth = self.obj['base_depth_m']
        all_depths = [foot_depth_m] + list(future_depths)
        behind_count = sum(1 for d in all_depths if d > base_depth)
        return BEHIND if behind_count * 2 > len(all_depths) else IN_FRONT

    def update(self, foot_x: int, foot_y: int,
               foot_depth_m: float, future_feet: list,
               char_bbox: tuple) -> bool:
        """
        Intersection-based state transition:
          not intersecting → not intersecting: hold IN_FRONT
          not intersecting → intersecting:     decide once based on depth
          intersecting     → intersecting:     hold current state
          intersecting     → not intersecting: reset to IN_FRONT
        """
        intersecting = self._bbox_intersects_mask(char_bbox)

        if intersecting and not self.is_intersecting:
            future_depths = [fd[2] for fd in future_feet if len(fd) > 2]
            self.state = self._decide_state(foot_depth_m, future_depths)
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
    Returns alpha mask (H_roi × W_roi, float 0-1):
      1 = character pixel visible
      0 = occluded by a scene object

    State must already be updated for this frame.
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
