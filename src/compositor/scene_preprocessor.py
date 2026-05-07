"""
scene_preprocessor.py

Generates all scene-level data needed by the compositor:
  - Background metric depth map  (scene_data/bg_depth_meters.npy)
  - Background disparity PNG     (scene_data/bg_disparity.png)
  - Per-object rasterized masks  (scene_data/masks/<id>.png)
  - scene_processed.json with stable per-object base_depth_m values

SEGMENTATION MODE: SAM2 automatic mask generation (no prompts needed).
  All segments are auto-detected. Ground/sky/oversized regions are filtered
  out. Each remaining segment is one scene object with a real pixel mask
  and a stable base_depth_m derived from DepthAnything at the mask base.

  scene.json is only needed for:
    - scene image path
    - depth calibration reference points

Heavy ML imports (transformers, sam2) are done lazily inside preprocess()
so the rest of the compositor package can be imported without them.
"""

import os
import cv2
import json
import numpy as np
from PIL import Image


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

# Inputs
SCENE_JSON      = "scene_data/scene.json"

# Outputs are namespaced under output/processed_scene/<image_basename>/
# so multiple scenes can coexist without clobbering each other. The
# default base directory is the parent; the per-scene subdir name is
# derived from the scene image filename (e.g. street.png -> street/).
OUTPUT_BASE_DIR = "output/processed_scene"

SAM2_CHECKPOINT = "checkpoints/sam2_hiera_large.pt"
SAM2_MODEL_CFG  = "sam2_hiera_l.yaml"

MAX_SEGMENT_AREA_FRAC = 0.35
MIN_SEGMENT_AREA_FRAC = 0.005


# ──────────────────────────────────────────────
# DEPTH ESTIMATION
# ──────────────────────────────────────────────

def estimate_background_depth(image_path: str,
                              scene_cfg: dict,
                              output_dir: str) -> np.ndarray:
    """
    Runs DepthAnything on the scene image and converts raw disparity
    to metric depth (meters) using two reference points from scene.json.
    """
    from transformers import pipeline  # lazy import

    print("Loading DepthAnything V2...")
    depth_pipe = pipeline(
        task="depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=0,
    )

    img_pil = Image.open(image_path).convert("RGB")
    result  = depth_pipe(img_pil)
    disp    = np.array(result["depth"]).astype(np.float64)

    disp_u8 = cv2.normalize(disp, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    cv2.imwrite(os.path.join(output_dir, "bg_disparity.png"), disp_u8)

    ref  = scene_cfg["scene"]["reference_points"]
    near = ref["near"]
    far  = ref["far"]

    ny, nx = near["image_pos"][1], near["image_pos"][0]
    fy, fx = far["image_pos"][1],  far["image_pos"][0]
    d_near = float(disp[ny, nx])
    d_far  = float(disp[fy, fx])
    z_near = float(near["metric_depth_m"])
    z_far  = float(far["metric_depth_m"])

    print("\nCalibration sanity check:")
    print(f"  Near {near['image_pos']}  disparity={d_near:.1f}  target={z_near}m")
    print(f"  Far  {far['image_pos']}  disparity={d_far:.1f}  target={z_far}m")
    if d_near > d_far:
        print(f"  ✓ Ordering correct (near {d_near:.1f} > far {d_far:.1f})")
    else:
        print(f"  ✗ WARNING: near disparity ({d_near:.1f}) <= far ({d_far:.1f})")
        print(f"    Reference points may be swapped or mis-aimed.")

    A = np.array([[1.0 / d_near, 1.0],
                  [1.0 / d_far,  1.0]])
    b_vec = np.array([z_near, z_far])
    try:
        a_coef, b_coef = np.linalg.solve(A, b_vec)
    except np.linalg.LinAlgError:
        print("Warning: could not solve calibration system, falling back to a=1, b=0")
        a_coef, b_coef = 1.0, 0.0

    depth_m = a_coef / (disp + 1e-6) + b_coef
    depth_m = np.clip(depth_m, 0.1, 200.0).astype(np.float32)

    print(f"Depth calibration: a={a_coef:.3f}  b={b_coef:.3f}")
    return depth_m


# ──────────────────────────────────────────────
# SEGMENTATION HELPERS
# ──────────────────────────────────────────────

def _sample_base_depth(depth_m: np.ndarray, mask: np.ndarray) -> tuple:
    """
    Stable depth for a segment = median depth across the bottom 10% of
    its mask pixels. Returns (base_depth_m, ground_anchor_y).
    """
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        h = depth_m.shape[0]
        return float(depth_m[h // 2, depth_m.shape[1] // 2]), h // 2

    bottom_thresh = np.percentile(ys, 90)
    bottom_ys = ys[ys >= bottom_thresh]
    bottom_xs = xs[ys >= bottom_thresh]
    depths = depth_m[bottom_ys, bottom_xs]
    ground_anchor_y = int(np.max(ys))
    return float(np.median(depths)), ground_anchor_y


def _compute_bottom_edge(mask: np.ndarray) -> np.ndarray:
    """For each x column, lowest (max-y) pixel in the mask, or -1."""
    h, w = mask.shape
    bottom_edge = np.full(w, -1, dtype=np.int32)
    for x in range(w):
        col = mask[:, x]
        ys = np.where(col > 0)[0]
        if len(ys) > 0:
            bottom_edge[x] = int(ys.max())
    return bottom_edge


def _compute_eroded_mask(mask: np.ndarray, erosion_px: int = 10) -> np.ndarray:
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (erosion_px * 2 + 1, erosion_px * 2 + 1)
    )
    return cv2.erode(mask, kernel, iterations=1)


def _is_valid_segment(mask: np.ndarray, image_area: int) -> bool:
    area = int(mask.sum())
    frac = area / image_area
    return MIN_SEGMENT_AREA_FRAC <= frac <= MAX_SEGMENT_AREA_FRAC


def _is_ground_plane(mask: np.ndarray, image_h: int, image_w: int) -> bool:
    """
    A segment is flagged as a ground plane if it meets ANY of these criteria:

      1. Very wide and low  — original desk/floor filter
         width_frac > 0.6 AND centroid_y > 0.5
      2. Flat horizontal surface — catches keyboards, trays, shelves
         width_frac > 0.3 AND centroid_y > 0.5 AND aspect_ratio < 0.4

    TODO: tighten per-scene or replace with semantic labels (SAM2 +
    GroundingDINO) so surfaces can be explicitly tagged.
    """
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return False

    width_frac      = (xs.max() - xs.min()) / image_w
    height_frac     = (ys.max() - ys.min()) / image_h
    centroid_y_frac = float(np.mean(ys)) / image_h
    aspect_ratio    = height_frac / (width_frac + 1e-6)

    if width_frac > 0.6 and centroid_y_frac > 0.5:
        return True
    if width_frac > 0.3 and centroid_y_frac > 0.5 and aspect_ratio < 0.4:
        return True
    return False


def _save_debug_overlay(bg_image: np.ndarray, objects: list, output_path: str):
    overlay = bg_image.copy()
    colours = [
        (255, 80,  80),  (80,  255, 80),  (80,  80,  255),
        (255, 255, 80),  (255, 80,  255), (80,  255, 255),
        (200, 140, 80),  (140, 80,  200),
    ]
    for i, obj in enumerate(objects):
        mask = cv2.imread(obj["mask_path"], cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        colour = colours[i % len(colours)]
        coloured = np.zeros_like(bg_image)
        coloured[mask > 0] = colour
        overlay = cv2.addWeighted(overlay, 1.0, coloured, 0.4, 0)

        ys, xs = np.where(mask > 0)
        if len(ys):
            cy, cx = int(np.mean(ys)), int(np.mean(xs))
            label = f"{obj['id']}  {obj['base_depth_m']:.1f}m"
            cv2.putText(overlay, label, (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)

    cv2.imwrite(output_path, overlay)
    print(f"Debug overlay saved → {output_path}")


# ──────────────────────────────────────────────
# SEGMENTATION (SAM2 auto)
# ──────────────────────────────────────────────

def segment_scene(scene_cfg: dict,
                  depth_m: np.ndarray,
                  bg_image: np.ndarray,
                  masks_dir: str,
                  sam2_checkpoint: str,
                  sam2_model_cfg: str) -> list:
    """SAM2 automatic mask generation, with area + ground-plane filtering."""
    from sam2.build_sam import build_sam2  # lazy
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator

    h, w = bg_image.shape[:2]
    image_area = h * w

    print("Loading SAM2 for automatic scene segmentation...")
    sam2_model = build_sam2(sam2_model_cfg, sam2_checkpoint, device="cuda")
    mask_generator = SAM2AutomaticMaskGenerator(
        model=sam2_model,
        points_per_side=32,
        pred_iou_thresh=0.80,
        stability_score_thresh=0.90,
        box_nms_thresh=0.70,
    )

    image_rgb = cv2.cvtColor(bg_image, cv2.COLOR_BGR2RGB)
    print("Running SAM2 automatic mask generation...")
    sam_masks = mask_generator.generate(image_rgb)
    print(f"SAM2 proposed {len(sam_masks)} segments before filtering.")

    sam_masks.sort(key=lambda m: m["area"], reverse=True)

    objects_out = []
    kept = 0

    for sam_mask in sam_masks:
        bool_mask = sam_mask["segmentation"]
        uint_mask = bool_mask.astype(np.uint8) * 255

        if not _is_valid_segment(bool_mask, image_area):
            continue
        if _is_ground_plane(bool_mask, h, w):
            print(f"  Skipping ground plane segment (area={sam_mask['area']}px)")
            continue

        obj_id = f"obj_{kept:03d}"
        base_depth_m, ground_anchor_y = _sample_base_depth(depth_m, uint_mask)
        bottom_edge = _compute_bottom_edge(uint_mask)
        eroded_mask = _compute_eroded_mask(uint_mask, erosion_px=10)

        mask_path        = os.path.join(masks_dir, f"{obj_id}.png")
        eroded_mask_path = os.path.join(masks_dir, f"{obj_id}_eroded.png")
        bottom_edge_path = os.path.join(masks_dir, f"{obj_id}_bottom_edge.npy")

        cv2.imwrite(mask_path, uint_mask)
        cv2.imwrite(eroded_mask_path, eroded_mask)
        np.save(bottom_edge_path, bottom_edge)

        ys_m, xs_m = np.where(uint_mask > 0)
        objects_out.append({
            "id":               obj_id,
            "label":            "",
            "mask_path":        mask_path,
            "eroded_mask_path": eroded_mask_path,
            "bottom_edge_path": bottom_edge_path,
            "ground_anchor_y":  ground_anchor_y,
            "base_depth_m":     base_depth_m,
            "x_min":            int(xs_m.min()) if len(xs_m) else 0,
            "x_max":            int(xs_m.max()) if len(xs_m) else w,
            "y_min":            int(ys_m.min()) if len(ys_m) else 0,
            "y_max":            int(ys_m.max()) if len(ys_m) else h,
        })

        print(f"  [{obj_id}]  area={sam_mask['area']}px  "
              f"base_depth={base_depth_m:.2f}m  anchor_y={ground_anchor_y}")
        kept += 1

    print(f"\nKept {kept} / {len(sam_masks)} segments after filtering.")
    return objects_out


def write_processed_scene(scene_cfg: dict,
                           objects: list,
                           depth_map_path: str,
                           output_path: str):
    out = {
        "scene": scene_cfg["scene"],
        "depth_map_path": depth_map_path,
        "objects": objects,
    }
    out["scene"]["depth_map_path"] = depth_map_path
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nProcessed scene saved → {output_path}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def preprocess(scene_json_path: str = SCENE_JSON,
               output_dir: str = None,
               output_base_dir: str = OUTPUT_BASE_DIR,
               sam2_checkpoint: str = SAM2_CHECKPOINT,
               sam2_model_cfg: str = SAM2_MODEL_CFG):
    """
    Run all scene preprocessing steps and write scene_processed.json.

    Args:
        scene_json_path: input config (image path + depth ref points)
        output_dir: explicit output directory. If None (default), derived
                    from the scene image filename so multiple processed
                    scenes can coexist:
                        testing_background/street.png
                        -> output/processed_scene/street/
        output_base_dir: parent directory used when output_dir is None.
        sam2_checkpoint, sam2_model_cfg: SAM2 model paths.

    Returns the path to the processed scene JSON.
    """
    with open(scene_json_path) as f:
        scene_cfg = json.load(f)

    image_path = scene_cfg["scene"]["image_path"]
    bg_image   = cv2.imread(image_path)
    if bg_image is None:
        raise FileNotFoundError(f"Scene image not found: {image_path}")

    # Derive output_dir from the scene image's basename when not given.
    # Each scene gets its own subdir under output/processed_scene/ so
    # processing a new scene doesn't clobber a previous one.
    if output_dir is None:
        scene_name = os.path.splitext(os.path.basename(image_path))[0]
        output_dir = os.path.join(output_base_dir, scene_name)
        print(f"Output dir auto-derived from scene image: {output_dir}")

    masks_dir = os.path.join(output_dir, "masks")
    os.makedirs(masks_dir, exist_ok=True)

    print(f"\n── Step 1: Depth estimation for {image_path}")
    depth_m = estimate_background_depth(image_path, scene_cfg, output_dir)
    depth_npy = os.path.join(output_dir, "bg_depth_meters.npy")
    np.save(depth_npy, depth_m)
    print(f"Metric depth map saved → {depth_npy}")

    print(f"\n── Step 2: Scene segmentation (SAM2 auto mode)")
    objects = segment_scene(scene_cfg, depth_m, bg_image,
                            masks_dir, sam2_checkpoint, sam2_model_cfg)

    print(f"\n── Step 3: Writing processed scene JSON")
    out_path = os.path.join(output_dir, "scene_processed.json")
    write_processed_scene(scene_cfg, objects,
                          depth_map_path=depth_npy, output_path=out_path)

    print(f"\n── Step 4: Saving debug overlay")
    _save_debug_overlay(
        bg_image, objects,
        output_path=os.path.join(output_dir, "debug_segments.png"),
    )

    print("\nPreprocessing complete.")
    print(f"⚠  Check {output_dir}/debug_segments.png to verify segments")
    print( "   look correct before running the compositor.")
    return out_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-json", default=SCENE_JSON,
                        help="Input scene config JSON")
    parser.add_argument("--output-dir", default=None,
                        help="Explicit output directory. If omitted, "
                             "derived from scene image filename: "
                             "<base>/<image_basename>/")
    parser.add_argument("--output-base-dir", default=OUTPUT_BASE_DIR,
                        help="Parent directory for auto-derived output "
                             "(default: output/processed_scene)")
    args = parser.parse_args()
    preprocess(args.scene_json,
               output_dir=args.output_dir,
               output_base_dir=args.output_base_dir)