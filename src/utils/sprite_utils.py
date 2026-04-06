"""Utility functions for working with sprite sheets and animations."""
from PIL import Image
import os

# TODO: code is very ugly
def extract_gif_from_sprite_sheet(
    sprite_sheet_path,
    output_path,
    num_frames=None,
    frame_width=None,
    frame_height=None,
    duration=100,
    loop=0
):
    """
    Extract individual frames from a sprite sheet and create an animated GIF.

    Args:
        sprite_sheet_path (str): Path to the sprite sheet image
        output_path (str): Path where the GIF should be saved
        num_frames (int, optional): Number of frames in the sprite sheet.
                                    If None, will try to auto-detect.
        frame_width (int, optional): Width of each frame. If None, will auto-detect.
        frame_height (int, optional): Height of each frame. If None, uses sheet height.
        duration (int): Duration of each frame in milliseconds (default: 100ms)
        loop (int): Number of times to loop (0 = infinite loop)

    Returns:
        str: Path to the created GIF file
    """
    # Load sprite sheet
    sprite_sheet = Image.open(sprite_sheet_path)
    sheet_width, sheet_height = sprite_sheet.size

    # Auto-detect frame dimensions if not provided
    if frame_height is None:
        frame_height = sheet_height

    if frame_width is None and num_frames:
        frame_width = sheet_width // num_frames
    elif frame_width is None:
        # Assume square frames
        frame_width = frame_height

    if num_frames is None:
        num_frames = sheet_width // frame_width

    print(f"Extracting {num_frames} frames from sprite sheet...")
    print(f"Frame dimensions: {frame_width}x{frame_height}")

    # Extract individual frames
    frames = []
    for i in range(num_frames):
        left = i * frame_width
        top = 0
        right = left + frame_width
        bottom = frame_height

        # Crop the frame
        frame = sprite_sheet.crop((left, top, right, bottom))
        frames.append(frame)

    # Save as animated GIF
    if frames:
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=loop,
            optimize=False
        )
        print(f"✅ Created animated GIF: {output_path}")
        return output_path
    else:
        print("❌ No frames extracted")
        return None


def extract_frames_from_sprite_sheet(
    sprite_sheet_path,
    output_dir,
    num_frames=None,
    frame_width=None,
    frame_height=None,
    prefix="frame"
):
    """
    Extract individual frames from a sprite sheet and save as separate images.

    Args:
        sprite_sheet_path (str): Path to the sprite sheet image
        output_dir (str): Directory where frames should be saved
        num_frames (int, optional): Number of frames in the sprite sheet
        frame_width (int, optional): Width of each frame
        frame_height (int, optional): Height of each frame
        prefix (str): Prefix for frame filenames (default: "frame")

    Returns:
        list: Paths to the extracted frame images
    """
    # Load sprite sheet
    sprite_sheet = Image.open(sprite_sheet_path)
    sheet_width, sheet_height = sprite_sheet.size

    # Auto-detect frame dimensions if not provided
    if frame_height is None:
        frame_height = sheet_height

    if frame_width is None and num_frames:
        frame_width = sheet_width // num_frames
    elif frame_width is None:
        frame_width = frame_height

    if num_frames is None:
        num_frames = sheet_width // frame_width

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    print(f"Extracting {num_frames} frames from sprite sheet...")

    # Extract and save individual frames
    frame_paths = []
    for i in range(num_frames):
        left = i * frame_width
        top = 0
        right = left + frame_width
        bottom = frame_height

        # Crop the frame
        frame = sprite_sheet.crop((left, top, right, bottom))

        # Save frame
        frame_path = os.path.join(output_dir, f"{prefix}_{i:03d}.png")
        frame.save(frame_path)
        frame_paths.append(frame_path)

    print(f"✅ Extracted {len(frame_paths)} frames to {output_dir}")
    return frame_paths


def create_gif_from_frames(frame_paths, output_path, duration=100, loop=0):
    """
    Create an animated GIF from a list of frame images.

    Args:
        frame_paths (list): List of paths to frame images
        output_path (str): Path where the GIF should be saved
        duration (int): Duration of each frame in milliseconds
        loop (int): Number of times to loop (0 = infinite)

    Returns:
        str: Path to the created GIF file
    """
    if not frame_paths:
        print("❌ No frames provided")
        return None

    # Load all frames
    frames = [Image.open(path) for path in frame_paths]

    # Save as animated GIF
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=loop,
        optimize=False
    )

    print(f"✅ Created animated GIF: {output_path}")
    return output_path
