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

        # Per-object masks and stable base depths.
        # Note: the labeler's mask-deduplication step already removes
        # redundant alternate segmentations from the JSON before saving,
        # so by this point objects[] should already be one-mask-per-
        # physical-object. We also tolerate the older format where
        # redundant masks were kept in the list and recorded in a
        # `redundant_masks` field (for backward compatibility with any
        # scene_processed.json that hasn't been regenerated yet).
        redundant_ids = set()
        for entry in data.get("redundant_masks", []) or []:
            if isinstance(entry, dict) and entry.get("id"):
                redundant_ids.add(entry["id"])
            elif isinstance(entry, str):
                redundant_ids.add(entry)

        self.objects = []
        for obj in data.get("objects", []):
            if obj["id"] in redundant_ids:
                continue
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
                # Default to True (treat as a real object) when the field is
                # absent — preserves behaviour for scenes preprocessed before
                # the labeler existed.
                "is_object":       bool(obj.get("is_object", True)),
            })

        if redundant_ids:
            print(f"Scene loaded: {self.w}×{self.h}  |  "
                  f"{len(self.objects)} objects  "
                  f"(excluded {len(redundant_ids)} redundant masks)")
        else:
            print(f"Scene loaded: {self.w}×{self.h}  |  "
                  f"{len(self.objects)} objects")
        for o in self.objects:
            print(f"  [{o['id']}]  base_depth={o['base_depth_m']:.2f}m")

    def resolve_object_ref(self, ref: str) -> list:
        """
        Look up scene objects by reference string. Returns a list of
        matching object dicts (could be 0, 1, or many).

        Resolution order:
          1. Exact ID match → returns a single-element list. IDs are
             unique by construction.
          2. Label match → returns all objects sharing that label.
             Labels can map to multiple SAM2 segments — same physical
             object kept as multiple entries because they over-segmented
             during preprocessing — so the list form is the natural
             representation here.

        Returns an empty list if nothing matches.
        """
        if ref is None:
            return []
        # IDs are unique, so an ID match terminates the search
        for obj in self.objects:
            if obj["id"] == ref:
                return [obj]
        # Otherwise look up by label, returning ALL matches.
        # Case-insensitive and whitespace-normalised so labels like
        # "Computer Mouse" and "computer mouse" resolve the same.
        ref_norm = ref.strip().lower()
        matches = [obj for obj in self.objects
                   if obj.get("label", "").strip().lower() == ref_norm]
        return matches

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

    def filter_noise(self) -> list:
        """
        Removes objects flagged as non-objects (sky, gradients, lighting
        artifacts, etc.) by the labeler's `is_object: false` annotation.
        Mutates self.objects in place; returns the ids removed.

        Safe to call on scenes that haven't been labeled — objects without
        an `is_object` field default to True (treated as real objects), so
        nothing gets filtered.
        """
        noise_ids = {o["id"] for o in self.objects if not o.get("is_object", True)}
        if noise_ids:
            print(f"  Excluding non-object segments (labeler is_object=false): "
                  f"{sorted(noise_ids)}")
        self.objects = [o for o in self.objects if o["id"] not in noise_ids]
        if noise_ids:
            print(f"  {len(self.objects)} objects remain as occluders")
        return list(noise_ids)