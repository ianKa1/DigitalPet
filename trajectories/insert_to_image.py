"""
insert_to_image.py
------------------
Takes a folder of individual frame PNGs (output from extract_row_animation.py),
lets the user draw a trajectory on the background image, then renders an MP4
with the animation looping along that path.

Usage:
    python insert_to_image.py \
        --frames_dir output/walk \
        --background background.png \
        --output result.mp4

    # With explicit control:
    python insert_to_image.py \
        --frames_dir output/walk \
        --background background.png \
        --output result.mp4 \
        --anim_fps 8 \
        --video_fps 24 \
        --duration 5.0 \
        --scale 150 \
        --preview

Controls (trajectory window):
    Left click      Add waypoint
    Right click     Remove last waypoint
    ENTER           Render
    R               Reset all waypoints
    ESC             Quit

Requirements:
    pip install opencv-python pillow numpy
"""

import os
import re
import cv2
import math
import argparse
import numpy as np
from PIL import Image


# ─────────────────────────────────────────────
# 1. LOAD FRAMES FROM FOLDER
# ─────────────────────────────────────────────

def load_frames_from_folder(frames_dir: str, scale: int = None) -> list:
    """
    Load all PNG frames from a directory, sorted by filename.
    Expects files like frame_000.png, frame_001.png, ... (any prefix, numeric suffix).

    Args:
        frames_dir: Path to folder containing frame PNGs.
        scale:      If set, resize each frame to this width in px (aspect preserved).

    Returns:
        List of BGRA numpy arrays, one per frame, sorted in animation order.
    """
    if not os.path.isdir(frames_dir):
        raise ValueError(f"frames_dir does not exist: {frames_dir}")

    # Collect PNGs only, skip GIFs and other files
    all_files = [f for f in os.listdir(frames_dir) if f.lower().endswith(".png")]
    if not all_files:
        raise ValueError(f"No PNG files found in: {frames_dir}")

    # Sort numerically by the last integer found in the filename
    def sort_key(name):
        nums = re.findall(r'\d+', name)
        return int(nums[-1]) if nums else 0

    all_files.sort(key=sort_key)
    print(f"Found {len(all_files)} PNG frames in '{frames_dir}':")
    for f in all_files:
        print(f"  {f}")

    frames = []
    for fname in all_files:
        path = os.path.join(frames_dir, fname)
        # Load with PIL to handle RGBA PNGs correctly
        pil = Image.open(path).convert("RGBA")

        if scale is not None:
            orig_w, orig_h = pil.size
            ratio = scale / orig_w
            new_size = (scale, max(1, int(orig_h * ratio)))
            pil = pil.resize(new_size, Image.LANCZOS)

        # Convert RGBA → BGRA for OpenCV compositing
        rgba = np.array(pil)
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        frames.append(bgra)

    print(f"✅ Loaded {len(frames)} frames ({frames[0].shape[1]}×{frames[0].shape[0]} px each)")
    return frames


# ─────────────────────────────────────────────
# 2. FRAME PREVIEW
# ─────────────────────────────────────────────

def preview_frames(frames: list, cols: int = 4):
    """Show all loaded frames tiled on a dark canvas. Press any key to continue."""
    if not frames:
        return
    fh, fw = frames[0].shape[:2]
    rows = math.ceil(len(frames) / cols)
    canvas = np.full((rows * fh, cols * fw, 3), 40, dtype=np.uint8)

    for i, f in enumerate(frames):
        col = i % cols
        row = i // cols
        bgr   = f[:, :, :3].astype(np.float32)
        alpha = f[:, :, 3:4].astype(np.float32) / 255.0
        region = canvas[row * fh:(row + 1) * fh, col * fw:(col + 1) * fw].astype(np.float32)
        blended = (bgr * alpha + region * (1 - alpha)).astype(np.uint8)
        canvas[row * fh:(row + 1) * fh, col * fw:(col + 1) * fw] = blended

    cv2.imshow(f"Frame preview — {len(frames)} frames (any key to continue)", canvas)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ─────────────────────────────────────────────
# 3. TRAJECTORY DRAWING UI
# ─────────────────────────────────────────────

def draw_trajectory_ui(background_path: str, anim_fps: int, video_fps: int, duration: float) -> list:
    """
    Open an interactive window showing the background image.
    User clicks to place waypoints defining the sprite's path.

    Displays current render settings in the window for reference.
    Returns list of (x, y) waypoints, or [] if user pressed ESC.
    """
    bg = cv2.imread(background_path)
    if bg is None:
        raise ValueError(f"Could not load background image: {background_path}")

    waypoints = []
    display   = bg.copy()

    def redraw():
        nonlocal display
        display = bg.copy()

        # Draw lines between waypoints
        for i in range(1, len(waypoints)):
            cv2.line(display, waypoints[i - 1], waypoints[i], (0, 200, 255), 2, cv2.LINE_AA)

        # Draw each waypoint dot + index label
        for i, pt in enumerate(waypoints):
            cv2.circle(display, pt, 7, (0, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(display, pt, 7, (0, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(display, str(i + 1), (pt[0] + 10, pt[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

        # HUD — instructions + current settings
        lines = [
            "Left click: add point  |  Right click: undo  |  R: reset",
            "ENTER: render  |  ESC: quit",
            f"anim_fps={anim_fps}  video_fps={video_fps}  duration={duration}s  "
            f"total_frames={int(video_fps * duration)}",
            f"Waypoints placed: {len(waypoints)}",
        ]
        for j, text in enumerate(lines):
            y = 22 + j * 20
            cv2.putText(display, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(display, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            waypoints.append((x, y))
            redraw()
        elif event == cv2.EVENT_RBUTTONDOWN:
            if waypoints:
                waypoints.pop()
            redraw()

    win = "Draw Trajectory — ENTER to render"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    redraw()

    while True:
        cv2.imshow(win, display)
        key = cv2.waitKey(20) & 0xFF

        if key == 13:  # ENTER
            if len(waypoints) < 2:
                print("⚠️  Place at least 2 points before rendering.")
            else:
                break
        elif key in (ord('r'), ord('R')):
            waypoints.clear()
            redraw()
        elif key == 27:  # ESC
            cv2.destroyAllWindows()
            return []

    cv2.destroyAllWindows()
    print(f"✅ Trajectory: {len(waypoints)} waypoints")
    return waypoints


# ─────────────────────────────────────────────
# 4. TRAJECTORY INTERPOLATION
# ─────────────────────────────────────────────

def interpolate_trajectory(waypoints: list, total_steps: int) -> list:
    """
    Distribute total_steps positions evenly along the polyline defined by waypoints.
    Uses linear interpolation between each consecutive pair of points.
    """
    if len(waypoints) < 2:
        return [waypoints[0]] * total_steps

    # Build cumulative arc-length distances
    dists = [0.0]
    for i in range(1, len(waypoints)):
        dx = waypoints[i][0] - waypoints[i - 1][0]
        dy = waypoints[i][1] - waypoints[i - 1][1]
        dists.append(dists[-1] + math.hypot(dx, dy))

    total_dist = dists[-1]
    if total_dist == 0:
        return [waypoints[0]] * total_steps

    positions = []
    for step in range(total_steps):
        target = (step / max(total_steps - 1, 1)) * total_dist

        # Find which segment contains this target distance
        seg = len(waypoints) - 2
        for i in range(1, len(dists)):
            if dists[i] >= target:
                seg = i - 1
                break

        seg_len = dists[seg + 1] - dists[seg]
        t = 0.0 if seg_len == 0 else (target - dists[seg]) / seg_len
        x = waypoints[seg][0] + t * (waypoints[seg + 1][0] - waypoints[seg][0])
        y = waypoints[seg][1] + t * (waypoints[seg + 1][1] - waypoints[seg][1])
        positions.append((int(x), int(y)))

    return positions


# ─────────────────────────────────────────────
# 5. COMPOSITING
# ─────────────────────────────────────────────

def composite_frame(bg_bgr: np.ndarray, sprite_bgra: np.ndarray, cx: int, cy: int) -> np.ndarray:
    """
    Alpha-blend a BGRA sprite centred at pixel (cx, cy) onto a BGR background.
    Handles sprites that are partially off the edge of the canvas.
    """
    out = bg_bgr.copy()
    bh, bw = out.shape[:2]
    sh, sw = sprite_bgra.shape[:2]

    # Destination rect on the background
    x1, y1 = cx - sw // 2, cy - sh // 2
    x2, y2 = x1 + sw, y1 + sh

    # Clamp to canvas bounds and compute matching source rect
    sx1 = max(0, -x1);   sy1 = max(0, -y1)
    sx2 = sw - max(0, x2 - bw)
    sy2 = sh - max(0, y2 - bh)
    bx1 = max(0, x1);   by1 = max(0, y1)
    bx2 = bx1 + (sx2 - sx1)
    by2 = by1 + (sy2 - sy1)

    if sx2 <= sx1 or sy2 <= sy1:
        return out  # Fully off screen

    src   = sprite_bgra[sy1:sy2, sx1:sx2]
    dst   = out[by1:by2, bx1:bx2].astype(np.float32)
    alpha = src[:, :, 3:4].astype(np.float32) / 255.0
    blended = (src[:, :, :3].astype(np.float32) * alpha + dst * (1.0 - alpha)).astype(np.uint8)
    out[by1:by2, bx1:bx2] = blended
    return out


# ─────────────────────────────────────────────
# 6. RENDERING
# ─────────────────────────────────────────────

def render_video(
    background_path: str,
    sprite_frames: list,
    waypoints: list,
    output_path: str,
    video_fps: int = 24,
    anim_fps: int = 8,
    duration_sec: float = 4.0,
):
    """
    Render the final MP4.

    video_fps controls how smooth the motion looks (output frame rate).
    anim_fps controls how fast the sprite animation cycles (can be lower than video_fps
    to give a hand-drawn / stop-motion feel without slowing down the movement).

    The sprite frames loop continuously as the position advances along the trajectory.

    Args:
        background_path: Path to background image.
        sprite_frames:   List of BGRA numpy arrays.
        waypoints:       List of (x, y) trajectory points.
        output_path:     Output .mp4 path.
        video_fps:       Frames per second of the output video.
        anim_fps:        How many animation frames to advance per second.
                         Lower = slower sprite cycle. Must be <= video_fps.
        duration_sec:    Total travel time in seconds.
    """
    bg = cv2.imread(background_path)
    if bg is None:
        raise ValueError(f"Could not load background: {background_path}")

    h, w  = bg.shape[:2]
    total_video_frames = int(video_fps * duration_sec)
    positions = interpolate_trajectory(waypoints, total_video_frames)

    writer = cv2.VideoWriter(
        output_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        video_fps,
        (w, h)
    )

    n = len(sprite_frames)
    # How many video frames elapse before we advance one animation frame
    anim_step = video_fps / anim_fps

    print(f"\nRendering {total_video_frames} video frames at {video_fps} FPS → {output_path}")
    print(f"Animation cycles at {anim_fps} FPS ({n} frames, loops every {n / anim_fps:.2f}s)")

    for i, (cx, cy) in enumerate(positions):
        # Which animation frame to show at this video frame
        anim_idx = int(i / anim_step) % n
        frame = composite_frame(bg, sprite_frames[anim_idx], cx, cy)
        writer.write(frame)

        if i % video_fps == 0:
            pct = int(100 * i / total_video_frames)
            print(f"  {i}/{total_video_frames}  ({pct}%)")

    writer.release()
    print(f"✅ Saved: {output_path}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Animate frame PNGs along a drawn trajectory on a background image"
    )
    parser.add_argument("--frames_dir",  required=True,
                        help="Folder containing frame_000.png, frame_001.png, ... (output of extract_row_animation.py)")
    parser.add_argument("--background",  required=True,
                        help="Background image path (PNG or JPG)")
    parser.add_argument("--output",      default="result.mp4",
                        help="Output MP4 path (default: result.mp4)")
    parser.add_argument("--video_fps",   type=int,   default=24,
                        help="Output video frame rate — controls smoothness of motion (default: 24)")
    parser.add_argument("--anim_fps",    type=int,   default=8,
                        help="Animation cycle rate — how fast sprite frames advance per second (default: 8). "
                             "Lower = slower/choppier sprite. Must be <= video_fps.")
    parser.add_argument("--duration",    type=float, default=4.0,
                        help="Total travel duration in seconds (default: 4.0)")
    parser.add_argument("--scale",       type=int,   default=None,
                        help="Resize sprite frames to this width in px (default: keep original)")
    parser.add_argument("--preview",     action="store_true",
                        help="Show loaded frames before opening trajectory window")
    args = parser.parse_args()

    # Validate fps relationship
    if args.anim_fps > args.video_fps:
        print(f"⚠️  anim_fps ({args.anim_fps}) > video_fps ({args.video_fps}). "
              f"Clamping anim_fps to {args.video_fps}.")
        args.anim_fps = args.video_fps

    # ── Step 1: Load frames ──────────────────────────────────────────────
    frames = load_frames_from_folder(args.frames_dir, scale=args.scale)

    # ── Step 2: Optional preview ─────────────────────────────────────────
    if args.preview:
        preview_frames(frames)

    # ── Step 3: Draw trajectory ───────────────────────────────────────────
    print("\nOpening background — click to place waypoints, then press ENTER.")
    waypoints = draw_trajectory_ui(
        args.background,
        anim_fps=args.anim_fps,
        video_fps=args.video_fps,
        duration=args.duration,
    )
    if not waypoints:
        print("No trajectory drawn. Exiting.")
        exit(0)

    # ── Step 4: Render ───────────────────────────────────────────────────
    render_video(
        background_path=args.background,
        sprite_frames=frames,
        waypoints=waypoints,
        output_path=args.output,
        video_fps=args.video_fps,
        anim_fps=args.anim_fps,
        duration_sec=args.duration,
    )