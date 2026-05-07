"""
scene.py

Loads the preprocessed scene (image, depth map, per-object masks) for the
compositor. This is the same SceneContext from the original compositor —
extracted into its own module for clarity.
"""

import os
import json
import cv2
import numpy as np


class SceneContext:
    """Loads and holds all scene-level data needed by the compositor."""

    def __init__(self, scene_json_path: str):
        with open(scene_json_path) as f:
            data = json.load(f)

        scene_cfg = data["scene"]
        self.bg_image = cv2.imread(scene_cfg["image_path"])
        if self.bg_image is None:
            raise FileNotFoundError(
                f"Scene image not found: {scene_cfg['image_path']}"
            )

        self.h, self.w = self.bg_image.shape[:2]
        self.near_depth_m = scene_cfg["reference_points"]["near"]["metric_depth_m"]

        # Metric depth map (float32, metres)
        depth_path = data.get("depth_map_path") or scene_cfg.get("depth_map_path")
        if depth_path and depth_path.endswith(".npy") and os.path.exists(depth_path):
            self.depth_m = np.load(depth_path)
        else:
            print("Warning: no metric depth map found, using flat fallback.")
            self.depth_m = np.full((self.h, self.w),
                                   self.near_depth_m, dtype=np.float32)

        if self.depth_m.shape[:2] != (self.h, self.w):
            self.depth_m = cv2.resize(self.depth_m, (self.w, self.h),
                                      interpolation=cv2.INTER_LINEAR)

        # Per-object masks and stable base depths
        self.objects = []
        for obj in data.get("objects", []):
            mask = self._load_mask(obj)
            if mask is None:
                print(f"  Warning: object '{obj['id']}' has no usable mask, "
                      f"skipping.")
                continue

            eroded_mask = self._load_optional_mask(obj.get("eroded_mask_path"))
            bottom_edge = None
            bep = obj.get("bottom_edge_path")
            if bep and os.path.exists(bep):
                bottom_edge = np.load(bep)

            self.objects.append({
                "id":              obj["id"],
                "label":           obj.get("label", ""),
                "mask":            mask,
                "eroded_mask":     eroded_mask,
                "bottom_edge":     bottom_edge,
                "base_depth_m":    float(obj["base_depth_m"]),
                "x_min":           int(obj.get("x_min", 0)),
                "x_max":           int(obj.get("x_max", self.w)),
                "y_min":           int(obj.get("y_min", 0)),
                "y_max":           int(obj.get("y_max", self.h)),
                "is_ground_plane": bool(obj.get("is_ground_plane", False)),
            })

        print(f"Scene loaded: {self.w}×{self.h}  |  "
              f"{len(self.objects)} objects")
        for o in self.objects:
            print(f"  [{o['id']}]  base_depth={o['base_depth_m']:.2f}m")

    def _load_mask(self, obj):
        mask = None
        mp = obj.get("mask_path") or obj.get("mask_image_path")
        if mp and os.path.exists(mp):
            mask = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
            if mask is not None and mask.shape[:2] != (self.h, self.w):
                mask = cv2.resize(mask, (self.w, self.h),
                                  interpolation=cv2.INTER_NEAREST)
        elif obj.get("mask_polygon"):
            mask = np.zeros((self.h, self.w), dtype=np.uint8)
            pts = np.array(obj["mask_polygon"], dtype=np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(mask, [pts], 255)
        return mask

    def _load_optional_mask(self, path):
        if path and os.path.exists(path):
            m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if m is not None and m.shape[:2] != (self.h, self.w):
                m = cv2.resize(m, (self.w, self.h),
                               interpolation=cv2.INTER_NEAREST)
            return m
        return None

    def filter_ground_planes(self) -> list:
        """
        Removes objects flagged as ground planes (walkable surfaces) from
        self.objects and returns their ids. Mutates self.objects in place.
        """
        ground_ids = {o["id"] for o in self.objects if o.get("is_ground_plane")}
        if ground_ids:
            print(f"  Excluding ground-plane objects: {sorted(ground_ids)}")
        self.objects = [o for o in self.objects if o["id"] not in ground_ids]
        print(f"  {len(self.objects)} objects remain as occluders")
        return list(ground_ids)
