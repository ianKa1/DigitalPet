"""
sprite_to_frames.py
-------------------------
Takes a multi-action sprite sheet (one action per row), lets the user pick
which row to extract, removes solid white background, saves each frame as its
own PNG, and produces a combined animated GIF.

Built on top of the grid detection logic from the original codebase.

Usage:
    # Auto-detect grid, prompt user to pick row interactively:
    python extract_row_animation.py --input sprite_sheet.png --output_dir frames/

    # Specify row directly (0-indexed), explicit grid size:
    python extract_row_animation.py --input sprite_sheet.png --output_dir frames/ \
        --cols 4 --rows 5 --row 2 --duration 120

Requirements:
    pip install pillow numpy
"""

import os
import argparse
import statistics
import numpy as np
from PIL import Image


# ─────────────────────────────────────────────
# GRID DETECTION (from original codebase)
# ─────────────────────────────────────────────

def _find_grid_lines(image: Image.Image, axis: str = 'horizontal', threshold: float = 0.7) -> list:
    """
    Scan rows (horizontal) or columns (vertical) looking for dark border lines.

    A line is detected when >threshold fraction of pixels in that row/col are
    darker than BLACK_THRESHOLD (value < 50 in greyscale).

    Returns list of pixel coordinates where grid lines were found.
    """
    gray = np.array(image.convert('L'))
    BLACK_THRESHOLD = 50
    grid_lines = []

    if axis == 'horizontal':
        for y in range(gray.shape[0]):
            row = gray[y, :]
            if np.sum(row < BLACK_THRESHOLD) / len(row) >= threshold:
                if grid_lines and y - grid_lines[-1] <= 3:
                    continue  # Part of same thick border — skip
                grid_lines.append(y)
    else:
        for x in range(gray.shape[1]):
            col = gray[:, x]
            if np.sum(col < BLACK_THRESHOLD) / len(col) >= threshold:
                if grid_lines and x - grid_lines[-1] <= 3:
                    continue
                grid_lines.append(x)

    return grid_lines


def detect_grid_structure(image_path: str) -> dict:
    """
    Auto-detect grid layout by finding black border lines in the sprite sheet.

    Returns dict with:
        frames_per_row, num_rows, frame_width, frame_height,
        total_frames, vertical_lines, horizontal_lines
    """
    img = Image.open(image_path)
    h_lines = _find_grid_lines(img, axis='horizontal', threshold=0.7)
    v_lines = _find_grid_lines(img, axis='vertical',   threshold=0.7)

    if len(h_lines) < 2 or len(v_lines) < 2:
        raise ValueError(
            f"Could not auto-detect grid lines "
            f"({len(h_lines)} horizontal, {len(v_lines)} vertical found). "
            f"Please pass --cols and --rows explicitly."
        )

    num_rows = len(h_lines) - 1
    num_cols = len(v_lines) - 1

    frame_heights = [h_lines[i + 1] - h_lines[i] for i in range(num_rows)]
    frame_widths  = [v_lines[i + 1] - v_lines[i] for i in range(num_cols)]
    frame_h = int(statistics.median(frame_heights))
    frame_w = int(statistics.median(frame_widths))

    print(f"Auto-detected grid: {num_cols} cols × {num_rows} rows  ({frame_w}×{frame_h} px per frame)")
    return {
        'frames_per_row':   num_cols,
        'num_rows':         num_rows,
        'frame_width':      frame_w,
        'frame_height':     frame_h,
        'total_frames':     num_rows * num_cols,
        'vertical_lines':   v_lines,
        'horizontal_lines': h_lines,
    }


def detect_grid_manual(image_path: str, cols: int, rows: int) -> dict:
    """
    Build a grid layout by dividing the image evenly into cols × rows cells.
    Use this when the sprite sheet has no visible border lines.
    """
    img = Image.open(image_path)
    w, h = img.size
    frame_w = w // cols
    frame_h = h // rows

    h_lines = [i * frame_h for i in range(rows + 1)]
    v_lines = [i * frame_w for i in range(cols + 1)]

    print(f"Manual grid: {cols} cols × {rows} rows  ({frame_w}×{frame_h} px per frame)")
    return {
        'frames_per_row':   cols,
        'num_rows':         rows,
        'frame_width':      frame_w,
        'frame_height':     frame_h,
        'total_frames':     cols * rows,
        'vertical_lines':   v_lines,
        'horizontal_lines': h_lines,
    }


# ─────────────────────────────────────────────
# ROW SELECTION
# ─────────────────────────────────────────────

def pick_row_interactively(num_rows: int) -> int:
    """
    Print a numbered list of rows and ask the user to choose one.
    Returns 0-indexed row number.
    """
    print(f"\nThis sprite sheet has {num_rows} row(s).")
    print("Each row is one animation. Which row do you want to extract?")
    for i in range(num_rows):
        print(f"  [{i}]  Row {i}  (e.g. action #{i + 1})")

    while True:
        try:
            choice = int(input(f"\nEnter row number (0 – {num_rows - 1}): ").strip())
            if 0 <= choice < num_rows:
                return choice
            print(f"  Please enter a number between 0 and {num_rows - 1}.")
        except ValueError:
            print("  Invalid input — please type a number.")


# ─────────────────────────────────────────────
# BACKGROUND REMOVAL
# ─────────────────────────────────────────────

def remove_white_bg(frame: Image.Image, tolerance: int = 20) -> Image.Image:
    """
    Remove solid white (or near-white) background from a frame.

    Pixels where R, G, B are all above (255 - tolerance) become transparent.
    Lower tolerance = only pure white removed.
    Higher tolerance = more off-white shades removed (use carefully or edges suffer).

    Returns RGBA image.
    """
    rgba = frame.convert("RGBA")
    data = np.array(rgba, dtype=np.int32)

    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]
    cutoff = 255 - tolerance

    is_white = (r >= cutoff) & (g >= cutoff) & (b >= cutoff)
    data[:, :, 3] = np.where(is_white, 0, data[:, :, 3])

    return Image.fromarray(data.astype(np.uint8), "RGBA")


# ─────────────────────────────────────────────
# FRAME EXTRACTION
# ─────────────────────────────────────────────

def _is_empty_cell(image: Image.Image, left: int, top: int, right: int, bottom: int) -> bool:
    """Returns True if the cell is >95% white/transparent — i.e. an empty padding slot."""
    cell = image.crop((left, top, right, bottom))
    arr = np.array(cell.convert('L'))
    return np.sum(arr > 240) / arr.size > 0.95


def extract_row_frames(
    image_path: str,
    layout: dict,
    row_index: int,
    remove_bg: bool = True,
    bg_tolerance: int = 20,
) -> list:
    """
    Extract every frame from a single row of the sprite sheet.

    Args:
        image_path:   Path to the sprite sheet PNG.
        layout:       Grid layout dict (from detect_grid_structure or detect_grid_manual).
        row_index:    Which row to extract (0-indexed).
        remove_bg:    Whether to remove the white background.
        bg_tolerance: Tolerance for white background detection (0–255, default 20).

    Returns:
        List of RGBA PIL Images, one per frame (empty cells skipped).
    """
    img = Image.open(image_path).convert("RGBA")
    v_lines = layout['vertical_lines']
    h_lines = layout['horizontal_lines']
    BORDER  = 2  # inset from grid line to avoid capturing the border itself
    cols    = layout['frames_per_row']

    frames = []
    for col in range(cols):
        left   = v_lines[col]         + BORDER
        right  = v_lines[col + 1]     - BORDER
        top    = h_lines[row_index]   + BORDER
        bottom = h_lines[row_index + 1] - BORDER

        if _is_empty_cell(img, left, top, right, bottom):
            print(f"  Skipping empty cell at col {col}")
            continue

        frame = img.crop((left, top, right, bottom))

        if remove_bg:
            frame = remove_white_bg(frame, tolerance=bg_tolerance)

        frames.append(frame)

    print(f"Extracted {len(frames)} frames from row {row_index}")
    return frames


# ─────────────────────────────────────────────
# SAVING
# ─────────────────────────────────────────────

def save_frames_as_pngs(frames: list, output_dir: str, prefix: str = "frame") -> list:
    """
    Save each frame as an individual PNG file.

    Files are named: {prefix}_000.png, {prefix}_001.png, ...

    Returns list of saved file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, frame in enumerate(frames):
        path = os.path.join(output_dir, f"{prefix}_{i:03d}.png")
        frame.save(path, "PNG")
        paths.append(path)
        print(f"  Saved {path}")
    print(f"✅ {len(frames)} PNGs saved → {output_dir}")
    return paths


def save_frames_as_gif(
    frames: list,
    output_path: str,
    duration_ms: int = 120,
    loop: int = 0,
) -> None:
    """
    Save a list of RGBA PIL Images as an animated GIF.

    Args:
        frames:      List of PIL Images.
        output_path: Where to save the .gif file.
        duration_ms: Display time per frame in milliseconds.
        loop:        0 = loop forever, N = play N times.
    """
    if not frames:
        raise ValueError("No frames to save.")

    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=loop,
        optimize=False,
        disposal=2,  # Clear frame before drawing next — prevents ghosting with transparency
    )
    print(f"✅ Animated GIF saved → {output_path}  ({len(frames)} frames @ {duration_ms}ms each)")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract one animation row from a sprite sheet → individual PNGs + animated GIF"
    )
    parser.add_argument("--input",      required=True,        help="Path to sprite sheet PNG")
    parser.add_argument("--output_dir", required=True,        help="Directory to save output PNGs and GIF")
    parser.add_argument("--cols",       type=int, default=None, help="Columns in sprite sheet (auto-detect if omitted)")
    parser.add_argument("--rows",       type=int, default=None, help="Rows in sprite sheet (auto-detect if omitted)")
    parser.add_argument("--row",        type=int, default=None, help="Row index to extract (0-indexed). Prompts interactively if omitted.")
    parser.add_argument("--duration",   type=int, default=120, help="Frame duration in ms for GIF (default: 120)")
    parser.add_argument("--tolerance",  type=int, default=20,  help="White bg removal tolerance 0-255 (default: 20)")
    parser.add_argument("--no_bg",      action="store_true",   help="Skip background removal")
    parser.add_argument("--prefix",     default="frame",       help="Filename prefix for output PNGs (default: 'frame')")
    parser.add_argument("--gif_name",   default="animation.gif", help="Output GIF filename (default: animation.gif)")
    args = parser.parse_args()

    # ── Step 1: Detect grid ──────────────────────────────────────────────
    if args.cols and args.rows:
        layout = detect_grid_manual(args.input, args.cols, args.rows)
    else:
        layout = detect_grid_structure(args.input)

    # ── Step 2: Pick row ─────────────────────────────────────────────────
    row_index = args.row if args.row is not None else pick_row_interactively(layout['num_rows'])
    if not (0 <= row_index < layout['num_rows']):
        raise ValueError(f"Row {row_index} is out of range (sheet has {layout['num_rows']} rows, 0-indexed).")
    print(f"\nExtracting row {row_index}...")

    # ── Step 3: Extract frames ───────────────────────────────────────────
    frames = extract_row_frames(
        image_path=args.input,
        layout=layout,
        row_index=row_index,
        remove_bg=not args.no_bg,
        bg_tolerance=args.tolerance,
    )

    if not frames:
        print("❌ No frames extracted. Check --cols/--rows and --row values.")
        exit(1)

    # ── Step 4: Save individual PNGs ─────────────────────────────────────
    save_frames_as_pngs(frames, output_dir=args.output_dir, prefix=args.prefix)

    # ── Step 5: Save animated GIF ─────────────────────────────────────────
    gif_path = os.path.join(args.output_dir, args.gif_name)
    save_frames_as_gif(frames, output_path=gif_path, duration_ms=args.duration)