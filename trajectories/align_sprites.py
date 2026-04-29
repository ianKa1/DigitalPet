"""
align_sprites.py
----------------
Align a set of sprite PNG frames so their visible content shares a common center,
then export the aligned frames and a combined animated GIF.

Two alignment methods are available:

  centroid  (default)
      Computes the center of mass of each frame's visible pixels (alpha > 0, or
      non-white if the image has no alpha channel), then translates each frame so
      all centroids coincide.  Fast, stable, and works well for sprites that keep
      roughly the same mass distribution across frames.

  phase
      Uses OpenCV's phase correlation (cv2.phaseCorrelate) to measure the
      pixel-shift between each frame and a chosen reference frame.  Better when
      the sprite changes shape dramatically across frames.  Requires opencv-python.

Usage:
    python align_sprites.py --input_dir frames/ --output_dir aligned/
    python align_sprites.py --input_dir frames/ --output_dir aligned/ --method phase
    python align_sprites.py --input_dir frames/ --output_dir aligned/ --duration 120 --prefix aligned

Requirements:
    pip install pillow numpy
    pip install opencv-python   # only needed for --method phase
"""

import os
import argparse
import numpy as np
from PIL import Image


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def load_rgba(path: str) -> Image.Image:
    """Load a PNG and ensure it is RGBA."""
    return Image.open(path).convert("RGBA")


def visible_mask(img_array: np.ndarray) -> np.ndarray:
    """
    Return a 2-D boolean mask of 'visible' pixels.

    A pixel is visible if its alpha channel > 10.  If the image has no
    meaningful alpha (all 255), fall back to non-white detection.
    """
    alpha = img_array[:, :, 3]
    if alpha.min() == 255:
        # No transparency — treat near-white as background
        r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]
        return ~((r > 240) & (g > 240) & (b > 240))
    return alpha > 10


def centroid(mask: np.ndarray):
    """Return (cy, cx) center of mass of a boolean mask. Returns None if mask is empty."""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return None
    return float(ys.mean()), float(xs.mean())


def shift_image(img: Image.Image, dy: float, dx: float) -> Image.Image:
    """
    Translate an RGBA image by (dx, dy) pixels using affine transform.
    Empty areas are filled with transparent pixels.
    """
    from PIL import ImageTransform
    w, h = img.size
    # PIL's AFFINE transform: output(x,y) = input(ax+by+c, dx+ey+f)
    # For a pure translation by (tx, ty): a=1,b=0,c=-tx, d=0,e=1,f=-ty
    tx, ty = round(dx), round(dy)
    translated = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    translated.paste(img, (tx, ty))
    return translated


# ─────────────────────────────────────────────
# CENTROID ALIGNMENT
# ─────────────────────────────────────────────

def align_by_centroid(frames: list[Image.Image]) -> list[Image.Image]:
    """
    Translate each frame so its visible-pixel centroid lands at the global
    average centroid of all frames.

    Returns a list of aligned RGBA images at the original canvas size.
    """
    arrays = [np.array(f) for f in frames]
    masks  = [visible_mask(a) for a in arrays]

    centroids = []
    for i, mask in enumerate(masks):
        c = centroid(mask)
        if c is None:
            print(f"  ⚠️  Frame {i} appears empty — centroid skipped")
            centroids.append(None)
        else:
            centroids.append(c)

    valid = [c for c in centroids if c is not None]
    if not valid:
        raise ValueError("No visible pixels found in any frame.")

    target_cy = np.mean([c[0] for c in valid])
    target_cx = np.mean([c[1] for c in valid])
    print(f"  Target centroid: ({target_cx:.1f}, {target_cy:.1f})")

    aligned = []
    for i, (frame, c) in enumerate(zip(frames, centroids)):
        if c is None:
            aligned.append(frame)
            continue
        dy = target_cy - c[0]
        dx = target_cx - c[1]
        print(f"  Frame {i:02d}: centroid ({c[1]:.1f}, {c[0]:.1f})  shift ({dx:+.1f}, {dy:+.1f})")
        aligned.append(shift_image(frame, dy, dx))

    return aligned


# ─────────────────────────────────────────────
# PHASE CORRELATION ALIGNMENT
# ─────────────────────────────────────────────

def align_by_phase(frames: list[Image.Image], ref_index: int = 0) -> list[Image.Image]:
    """
    Measure pixel shifts relative to a reference frame using phase correlation,
    then translate each frame to cancel that shift.

    Frames are padded to a common canvas size before correlation (phaseCorrelate
    requires identical dimensions).  The final output is cropped back to the
    original maximum bounding box.

    Requires opencv-python.
    """
    try:
        import cv2
    except ImportError:
        raise ImportError("opencv-python is required for phase alignment: pip install opencv-python")

    # Pad every frame to the same canvas (max width × max height)
    max_w = max(f.width  for f in frames)
    max_h = max(f.height for f in frames)

    def pad_to_canvas(img: Image.Image) -> Image.Image:
        if img.size == (max_w, max_h):
            return img
        canvas = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
        canvas.paste(img, (0, 0))
        return canvas

    def to_gray_float(img: Image.Image) -> np.ndarray:
        return np.array(img.convert("L"), dtype=np.float32)

    padded = [pad_to_canvas(f) for f in frames]
    ref_gray = to_gray_float(padded[ref_index])

    aligned = []
    for i, frame in enumerate(padded):
        if i == ref_index:
            aligned.append(frame)
            continue

        gray = to_gray_float(frame)
        (dx, dy), _ = cv2.phaseCorrelate(ref_gray, gray)
        print(f"  Frame {i:02d}: phase shift ({dx:+.2f}, {dy:+.2f})")
        # phaseCorrelate returns how much 'gray' is shifted relative to ref.
        # To bring frame back to ref position, translate by (-dx, 0).
        # Only avoid horizontal shift since vertical misalignment is often intentional (e.g. jump frames).
        aligned.append(shift_image(frame, 0, -dx))

    return aligned


# ─────────────────────────────────────────────
# SAVING
# ─────────────────────────────────────────────

def save_pngs(frames: list[Image.Image], output_dir: str, prefix: str = "aligned") -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, frame in enumerate(frames):
        path = os.path.join(output_dir, f"{prefix}_{i:03d}.png")
        frame.save(path, "PNG")
        paths.append(path)
        print(f"  Saved {path}")
    print(f"✅ {len(frames)} aligned PNGs → {output_dir}")
    return paths


def save_gif(
    frames: list[Image.Image],
    output_path: str,
    duration_ms: int = 120,
    loop: int = 0,
) -> None:
    if not frames:
        raise ValueError("No frames to save.")
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=loop,
        optimize=False,
        disposal=2,
    )
    print(f"✅ GIF → {output_path}  ({len(frames)} frames @ {duration_ms}ms)")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Align sprite frames to a common center → aligned PNGs + GIF"
    )
    parser.add_argument("--input_dir",  required=True, help="Folder containing input PNG frames")
    parser.add_argument("--output_dir", required=True, help="Folder to save aligned PNGs and GIF")
    parser.add_argument("--method",     default="centroid", choices=["centroid", "phase"],
                        help="Alignment method: 'centroid' (default) or 'phase' (requires opencv)")
    parser.add_argument("--ref",        type=int, default=0,
                        help="Reference frame index for phase alignment (default: 0)")
    parser.add_argument("--duration",   type=int, default=120,
                        help="Frame duration in ms for output GIF (default: 120)")
    parser.add_argument("--prefix",     default="aligned",
                        help="Filename prefix for output PNGs (default: 'aligned')")
    parser.add_argument("--gif_name",   default="aligned_animation.gif",
                        help="Output GIF filename (default: aligned_animation.gif)")
    args = parser.parse_args()

    # ── Load frames ─────────────────────────────────────────────────────────
    png_files = sorted(
        f for f in os.listdir(args.input_dir) if f.lower().endswith(".png")
    )
    if not png_files:
        print(f"❌ No PNG files found in {args.input_dir}")
        exit(1)

    print(f"Loading {len(png_files)} frames from {args.input_dir}...")
    frames = [load_rgba(os.path.join(args.input_dir, f)) for f in png_files]

    # ── Align ────────────────────────────────────────────────────────────────
    print(f"\nAligning with method: {args.method}")
    if args.method == "centroid":
        aligned = align_by_centroid(frames)
    else:
        aligned = align_by_phase(frames, ref_index=args.ref)

    # ── Save PNGs ────────────────────────────────────────────────────────────
    print()
    save_pngs(aligned, args.output_dir, prefix=args.prefix)

    # ── Save GIF ─────────────────────────────────────────────────────────────
    gif_path = os.path.join(args.output_dir, args.gif_name)
    save_gif(aligned, gif_path, duration_ms=args.duration)
