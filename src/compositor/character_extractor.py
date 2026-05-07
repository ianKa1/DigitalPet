"""
character_extractor.py

Takes a pet's animation library — a directory of GIFs with white backgrounds,
one per action — and produces:

  output/pets/<name>/animations/extracted/
      canvas.json              # canvas dimensions + foot offsets
      <action>/
          frames/
              frame_0000.png   # centered on shared square canvas
              frame_0001.png
              ...
          masks/
              frame_0000.png   # SAM2 segmentation, aligned to frames/
              frame_0001.png
              ...

Replaces the white-key mask_preprocessor.py with SAM2 video tracking,
which segments the character itself rather than carving away a white
background. This works correctly for white-bodied characters (Fluffball,
the white bunny) where the background-keying approach failed.

Design points carried from extract_character.py:

  - SAM2 video predictor with a single click point on the first frame —
    no manual mask annotation, no per-frame prompting.
  - Per-action: find the max bounding box across that action's frames.
    Then take the GLOBAL max across all actions to get one shared canvas
    size. Centering every frame of every action on the same canvas means
    the foot anchor lands at the same fractional position no matter which
    animation is currently playing — switching `hop -> idle -> hop`
    doesn't make the bunny visually pop.
  - Square canvas with PADDING_FRAC margin so flips/rotations preserve
    frame dimensions.

Note: SAM2 video predictor reads from a directory of image files, not a
GIF, so each action's frames are dumped to a temp `raw_frames/` dir
during processing and cleaned up afterward.
"""

import os
import json
import shutil
import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageSequence


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

SAM2_CHECKPOINT = "checkpoints/sam2_hiera_large.pt"
SAM2_MODEL_CFG  = "sam2_hiera_l.yaml"

# Padding around the tightest character bbox, as a fraction of the largest
# bbox dimension. Same value as extract_character.py for consistency.
PADDING_FRAC = 0.15


# ──────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────

def get_bbox(mask: np.ndarray):
    """Returns (x, y, w, h) bounding box over all non-zero pixels, or None."""
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return None
    return (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min()),
            int(ys.max() - ys.min()))


def auto_pick_click_points(first_frame_bgr: np.ndarray,
                           n_points: int = 5,
                           white_threshold: int = 235) -> list:
    """
    Pick several click points on the character without manual annotation.

    SAM2 takes much better-looking masks when given a *cluster* of
    positive points than a single click. With one click on, say, the
    bunny's belly, SAM2 can drift into segmenting just the belly or
    latch onto a high-contrast feature next to the click. With 5-6
    points scattered across the body, the prompt is unambiguous:
    "all of these are the same object."

    Strategy: find the largest connected component of non-white pixels
    (the body), then scatter `n_points` random samples inside it. The
    sampling is deterministic (seeded) so the click set is reproducible
    across runs.

    Returns a list of (x, y) tuples — at least 1 point, up to n_points.
    """
    gray = cv2.cvtColor(first_frame_bgr, cv2.COLOR_BGR2GRAY)
    char_mask = (gray < white_threshold).astype(np.uint8)

    if char_mask.sum() == 0:
        # No non-white pixels — fall back to image centre, single point
        h, w = first_frame_bgr.shape[:2]
        return [(w // 2, h // 2)]

    # Largest connected non-white component = body
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        char_mask, connectivity=8
    )
    if n_labels <= 1:
        ys, xs = np.where(char_mask > 0)
    else:
        areas = stats[1:, cv2.CC_STAT_AREA]
        biggest = 1 + int(np.argmax(areas))
        ys, xs = np.where(labels == biggest)

    # Always include the median as the anchor point — same logic as
    # the previous single-click version, robust to ear/feature drag.
    anchor_x = int(np.median(xs))
    anchor_y = int(np.median(ys))
    points = [(anchor_x, anchor_y)]

    if len(xs) < n_points or n_points <= 1:
        return points

    # Sample additional points uniformly from the body pixels.
    # Seeded so the result is reproducible — running the extractor
    # twice on the same GIF gives the same prompt set.
    rng = np.random.default_rng(seed=42)
    extra_idx = rng.choice(len(xs), size=n_points - 1, replace=False)
    for idx in extra_idx:
        points.append((int(xs[idx]), int(ys[idx])))

    return points


def gif_to_jpgs(gif_path: Path, raw_dir: Path) -> tuple:
    """
    Decode a GIF into JPG frames in raw_dir/0000.jpg, 0001.jpg, ...
    SAM2's video predictor reads from a directory of image files, so we
    have to dump frames to disk even though they originated as a GIF.

    Critical: PIL's GIF decoder uses lazy/shared state across frames. If
    you do `list(ImageSequence.Iterator(gif))` and *then* iterate the
    list calling `.convert()` on each item, every conversion reads the
    GIF's *current* internal frame — which is the last one — so all
    your "different frames" come out identical. The fix is to seek and
    materialise each frame inside the same loop pass.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    gif = Image.open(gif_path)
    n_frames = getattr(gif, "n_frames", 1)
    w, h = gif.size

    for i in range(n_frames):
        gif.seek(i)
        # .copy() forces PIL to materialise this specific frame's pixels
        # into a standalone Image, breaking the shared-state link.
        frame = gif.copy().convert("RGB")
        bgr = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(raw_dir / f"{i:04d}.jpg"), bgr)

    return n_frames, w, h


# ──────────────────────────────────────────────
# SAM2 SEGMENTATION
# ──────────────────────────────────────────────

def segment_action_with_sam2(predictor, raw_dir: Path,
                              click_points: list,
                              frame_w: int, frame_h: int,
                              n_frames: int) -> dict:
    """
    Run SAM2 video tracking over the dumped frames in raw_dir using a
    cluster of positive click points on the first frame.

    All points are labelled positive (label=1) — they're all telling
    SAM2 "this is part of the object." With multiple clicks across
    the body, SAM2 reliably segments the whole character rather than
    drifting to a single high-contrast feature near the click.

    click_points: list of (x, y) tuples, all in frame coordinates of
                  frame 0.

    Returns: dict mapping frame_idx -> uint8 H×W mask (or None if no mask).
    """
    inference_state = predictor.init_state(video_path=str(raw_dir))

    # Reset any previous state — important since we reuse the predictor
    # across multiple actions in the same run.
    predictor.reset_state(inference_state)

    points = [[int(x), int(y)] for (x, y) in click_points]
    labels = [1] * len(points)

    predictor.add_new_points_or_box(
        inference_state=inference_state,
        frame_idx=0,
        obj_id=1,
        points=points,
        labels=labels,
    )

    # Pre-fill so we can tell the difference between "SAM2 yielded for
    # this frame but with bad logits" and "SAM2 didn't yield at all".
    sam_masks = {i: None for i in range(n_frames)}

    n_yielded = 0
    n_logit_negative = 0
    n_empty_after_threshold = 0

    for out_frame_idx, out_obj_ids, out_mask_logits in \
            predictor.propagate_in_video(inference_state):
        n_yielded += 1
        logit = out_mask_logits[0].squeeze()

        if logit.ndim == 0:
            continue

        # Compute on CPU for predictable comparison behaviour
        logit_max = float(logit.max().item())
        if logit_max <= 0:
            n_logit_negative += 1
            continue

        mask = (logit > 0.0).cpu().numpy().astype(np.uint8) * 255

        # SAM2 sometimes returns a mask whose max logit is just barely
        # positive but the resulting binary mask is all zeros.
        if mask.sum() == 0:
            n_empty_after_threshold += 1
            continue

        if mask.shape[:2] != (frame_h, frame_w):
            mask = cv2.resize(mask, (frame_w, frame_h),
                              interpolation=cv2.INTER_NEAREST)
        sam_masks[out_frame_idx] = mask

    if n_yielded < n_frames:
        print(f"     [debug] SAM2 yielded {n_yielded}/{n_frames} frames "
              f"(propagation stopped early)")
    if n_logit_negative or n_empty_after_threshold:
        print(f"     [debug] {n_logit_negative}/{n_frames} frames had "
              f"logit_max<=0; {n_empty_after_threshold}/{n_frames} "
              f"thresholded to empty mask")

    return sam_masks


# ──────────────────────────────────────────────
# CANVAS COMPUTATION
# ──────────────────────────────────────────────

def compute_max_bbox_for_action(sam_masks: dict) -> tuple:
    """Returns (max_w, max_h) across all valid masks for one action."""
    max_w, max_h = 0, 0
    for mask in sam_masks.values():
        if mask is None:
            continue
        bbox = get_bbox(mask)
        if bbox:
            _, _, w, h = bbox
            max_w = max(max_w, w)
            max_h = max(max_h, h)
    return max_w, max_h


def derive_shared_canvas(per_action_max_bboxes: dict) -> int:
    """
    Given {action: (max_w, max_h)}, return the shared square canvas
    size: the largest dimension across all actions, padded by PADDING_FRAC
    on every side.

    Sharing one canvas across all actions is what gives the runtime the
    property that the foot anchor lands at the same fractional position
    regardless of which animation is active. Without that, switching
    actions would visually shift the character.
    """
    max_dim = 0
    for action, (w, h) in per_action_max_bboxes.items():
        max_dim = max(max_dim, w, h)
    if max_dim == 0:
        raise ValueError("No valid character bboxes found in any action.")
    pad = int(max_dim * PADDING_FRAC)
    return max_dim + pad * 2


# ──────────────────────────────────────────────
# CENTERING
# ──────────────────────────────────────────────

def center_frame_on_canvas(raw_frame: np.ndarray,
                           mask: np.ndarray,
                           canvas: int) -> tuple:
    """
    Crop the raw frame and mask to the character's bbox, then paste them
    centered on a white square canvas of the given size.

    Returns (canvas_img_bgr, canvas_mask).
    """
    canvas_img  = np.ones((canvas, canvas, 3), dtype=np.uint8) * 255
    canvas_mask = np.zeros((canvas, canvas),   dtype=np.uint8)

    if mask is None:
        return canvas_img, canvas_mask

    bbox = get_bbox(mask)
    if bbox is None:
        return canvas_img, canvas_mask

    x, y, w, h = bbox
    char_crop = raw_frame[y:y + h, x:x + w]
    mask_crop = mask[y:y + h, x:x + w]

    # Centre the character bbox on the square canvas
    ox = (canvas - w) // 2
    oy = (canvas - h) // 2

    # Defensive clamp in case the bbox somehow exceeds the canvas
    oy2 = min(oy + h, canvas)
    ox2 = min(ox + w, canvas)
    ch  = oy2 - oy
    cw  = ox2 - ox

    canvas_img [oy:oy2, ox:ox2] = char_crop[:ch, :cw]
    canvas_mask[oy:oy2, ox:ox2] = mask_crop[:ch, :cw]
    return canvas_img, canvas_mask


# ──────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────

def extract_pet(animations_dir: str,
                output_subdir: str = "extracted",
                click_x: int = None,
                click_y: int = None,
                per_action_clicks: dict = None,
                sam2_checkpoint: str = SAM2_CHECKPOINT,
                sam2_model_cfg: str = SAM2_MODEL_CFG):
    """
    Run SAM2-based extraction over every GIF in `animations_dir`.

    Args:
        animations_dir: e.g. 'output/pets/Fluffball/animations'
        output_subdir:  written under animations_dir
        click_x, click_y: SAM2 prompt point used for ALL actions. If None
                          (default), auto_pick_click_point picks one per
                          action by finding the centroid of non-white
                          pixels in that action's first frame.
        per_action_clicks: dict mapping {action_name: (x, y)} for actions
                           that need manual override (e.g. front-facing
                           poses where the auto-click might land on a
                           facial feature).
        sam2_checkpoint, sam2_model_cfg: SAM2 model weights and config.

    Output structure:
        <animations_dir>/<output_subdir>/
            canvas.json
            <action>/
                frames/frame_NNNN.png
                masks/frame_NNNN.png
    """
    # Lazy import — keeps the rest of the package usable without SAM2 deps
    from sam2.build_sam import build_sam2_video_predictor

    animations_dir = Path(animations_dir)
    if not animations_dir.is_dir():
        raise FileNotFoundError(f"Animations dir not found: {animations_dir}")

    output_dir = animations_dir / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    per_action_clicks = per_action_clicks or {}

    # Discover GIFs at the top level (skip subfolders like temp/, masks/,
    # extracted/ that are byproducts of various pipeline steps).
    gif_paths = sorted(p for p in animations_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".gif")
    if not gif_paths:
        print(f"  ⚠️  No GIFs found in {animations_dir}")
        return None

    print(f"🎭 SAM2 extraction for {len(gif_paths)} animations")
    print(f"   output → {output_dir}")

    # Build the SAM2 predictor once — reused across all actions
    print("\nLoading SAM2 video predictor...")
    predictor = build_sam2_video_predictor(sam2_model_cfg, sam2_checkpoint)

    # ── Pass 1: dump frames + run SAM2 + collect per-action masks/bboxes ──
    per_action_data = {}   # action -> dict of {raw_dir, sam_masks, w, h, n_frames}
    per_action_max  = {}   # action -> (max_w, max_h)

    for gif_path in gif_paths:
        action = gif_path.stem
        raw_dir = output_dir / action / "raw_frames"

        # Step 1: dump GIF frames to temporary JPGs for SAM2
        print(f"\n── {action}: dumping frames...")
        n_frames, w, h = gif_to_jpgs(gif_path, raw_dir)
        print(f"   {n_frames} frames, {w}×{h}")

        # Step 2: SAM2 tracking
        # Click priority: per-action override > global override > auto-pick.
        # The auto-pick case generates a CLUSTER of points across the body,
        # which gives much cleaner masks than a single click (especially on
        # front-facing poses where one click can land on a facial feature).
        first_frame_bgr = cv2.imread(str(raw_dir / "0000.jpg"))
        if action in per_action_clicks:
            click_points = [per_action_clicks[action]]
            click_source = "per-action override (1 point)"
        elif click_x is not None and click_y is not None:
            click_points = [(click_x, click_y)]
            click_source = "global override (1 point)"
        else:
            click_points = auto_pick_click_points(first_frame_bgr,
                                                  n_points=5)
            click_source = f"auto-picked ({len(click_points)} points on body)"
        print(f"   SAM2 clicks {click_points} — {click_source}")

        # Save a verify image for debugging (one per action) — draw all
        # click points so you can see whether they all landed on the bunny
        verify_dst = output_dir / action / "verify_click.png"
        verify_src = first_frame_bgr.copy()
        for (px, py) in click_points:
            cv2.circle(verify_src, (px, py), 6, (0, 0, 255), -1)
        cv2.imwrite(str(verify_dst), verify_src)

        sam_masks = segment_action_with_sam2(
            predictor, raw_dir, click_points, w, h, n_frames
        )
        n_valid = sum(v is not None for v in sam_masks.values())
        print(f"   SAM2 produced {n_valid}/{n_frames} valid masks")

        if n_valid == 0:
            print(f"   ⚠️  No valid masks. Try --click-x / --click-y. "
                  f"See {verify_dst}")
            continue

        max_w, max_h = compute_max_bbox_for_action(sam_masks)
        per_action_data[action] = {
            "raw_dir":   raw_dir,
            "sam_masks": sam_masks,
            "w": w, "h": h, "n_frames": n_frames,
        }
        per_action_max[action] = (max_w, max_h)
        print(f"   max bbox: {max_w}×{max_h}")

    if not per_action_data:
        print("\n❌ No actions yielded valid masks. Aborting.")
        return None

    # ── Pass 2: derive shared canvas size ──
    canvas = derive_shared_canvas(per_action_max)
    print(f"\n── Shared canvas size: {canvas}×{canvas}px")
    print(f"   (largest character dimension across all actions, "
          f"+ {int(PADDING_FRAC * 100)}% padding)")

    # ── Pass 3: centre every frame of every action on the shared canvas ──
    print("\n── Centering and writing output...")
    for action, data in per_action_data.items():
        frames_dir = output_dir / action / "frames"
        masks_dir  = output_dir / action / "masks"
        frames_dir.mkdir(parents=True, exist_ok=True)
        masks_dir.mkdir(parents=True, exist_ok=True)

        raw_dir   = data["raw_dir"]
        sam_masks = data["sam_masks"]
        n_frames  = data["n_frames"]

        for i in range(n_frames):
            raw_frame = cv2.imread(str(raw_dir / f"{i:04d}.jpg"))
            mask      = sam_masks.get(i)
            canvas_img, canvas_mask = center_frame_on_canvas(
                raw_frame, mask, canvas
            )
            cv2.imwrite(str(frames_dir / f"frame_{i:04d}.png"), canvas_img)
            cv2.imwrite(str(masks_dir  / f"frame_{i:04d}.png"), canvas_mask)

        # Clean up raw frames — they were temp scaffolding for SAM2
        shutil.rmtree(raw_dir, ignore_errors=True)
        print(f"   ✅ {action}: {n_frames} frames")

    # ── Pass 4: write canvas.json with metadata for the runtime ──
    # foot_offset_y_frac = 0.95 is a sensible default but the user should
    # tweak it after eyeballing the output. We record the centering math
    # we actually used so AnimationLibrary can pick the right offset later.
    canvas_meta = {
        "canvas_size":         canvas,
        "padding_frac":        PADDING_FRAC,
        "actions": {
            action: {
                "frame_count":     data["n_frames"],
                "source_size":     [data["w"], data["h"]],
                "max_bbox":        list(per_action_max[action]),
            }
            for action, data in per_action_data.items()
        },
        # Defaults — override per-pet in character.json after inspecting frames
        "default_foot_offset_x_frac": 0.5,
        "default_foot_offset_y_frac": 0.95,
    }
    canvas_json_path = output_dir / "canvas.json"
    with open(canvas_json_path, "w") as f:
        json.dump(canvas_meta, f, indent=2)
    print(f"\n📋 Wrote canvas metadata: {canvas_json_path}")

    print("\n" + "=" * 60)
    print("Extraction complete.")
    print("=" * 60)
    print(f"Update your character.json with:")
    print(f'  "frames_dir":         "{output_dir}"')
    print(f'  "native_height_px":   {canvas}')
    print(f'  "foot_offset_x_frac": 0.5')
    print(f'  "foot_offset_y_frac": 0.95   <- tune after inspecting frames')
    return output_dir


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract a pet's animation library with SAM2 segmentation.",
    )
    parser.add_argument(
        "--animations-dir",
        required=True,
        help="Path to a pet's animations directory, "
             "e.g. output/pets/Fluffball/animations",
    )
    parser.add_argument("--click-x", type=int, default=None,
                        help="SAM2 click X for ALL actions "
                             "(default: auto-pick non-white centroid)")
    parser.add_argument("--click-y", type=int, default=None,
                        help="SAM2 click Y for ALL actions "
                             "(default: auto-pick non-white centroid)")
    parser.add_argument(
        "--click", action="append", default=[],
        metavar="ACTION:X,Y",
        help="Per-action click override, repeatable. "
             "e.g. --click curious_look:60,90 --click hop:70,100",
    )
    parser.add_argument("--sam2-checkpoint", default=SAM2_CHECKPOINT)
    parser.add_argument("--sam2-config",     default=SAM2_MODEL_CFG)
    args = parser.parse_args()

    # Parse per-action click overrides into a dict
    per_action_clicks = {}
    for spec in args.click:
        try:
            action, xy = spec.split(":")
            x_str, y_str = xy.split(",")
            per_action_clicks[action.strip()] = (int(x_str), int(y_str))
        except ValueError:
            parser.error(f"Bad --click spec: {spec!r} "
                         f"(expected ACTION:X,Y)")

    extract_pet(
        animations_dir=args.animations_dir,
        click_x=args.click_x,
        click_y=args.click_y,
        per_action_clicks=per_action_clicks,
        sam2_checkpoint=args.sam2_checkpoint,
        sam2_model_cfg=args.sam2_config,
    )