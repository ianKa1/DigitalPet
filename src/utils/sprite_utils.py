"""
Sprite sheet processing utilities for background removal and frame manipulation.
"""

from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image, ImageFilter
import numpy as np
from rembg import remove


def extract_frames(
    image_path: str,
    grid_spec: Tuple[int, int] = (2, 4)
) -> List[Image.Image]:
    """
    Extract individual frames from a sprite sheet using simple grid division.

    Args:
        image_path: Path to the sprite sheet image
        grid_spec: Tuple of (rows, cols) for the grid layout

    Returns:
        List of PIL Image objects, one per frame

    Raises:
        FileNotFoundError: If image_path doesn't exist
        ValueError: If image dimensions don't divide evenly by grid_spec
    """
    img_path = Path(image_path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image = Image.open(image_path)
    width, height = image.size
    rows, cols = grid_spec

    # Simple grid division
    frame_width = width // cols
    frame_height = height // rows

    frames = []
    for row in range(rows):
        for col in range(cols):
            x1 = col * frame_width
            y1 = row * frame_height
            x2 = x1 + frame_width
            y2 = y1 + frame_height

            frame = image.crop((x1, y1, x2, y2))
            frames.append(frame)

    return frames


def remove_background_rembg(
    frame: Image.Image,
    model_name: str = 'u2net',
    alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 270,
    alpha_matting_background_threshold: int = 20,
    alpha_matting_erode_size: int = 5,
    dilate_foreground: int = 3
) -> Image.Image:
    """
    Remove background from a single frame using rembg.

    Args:
        frame: PIL Image object to process
        model_name: rembg model to use ('u2net', 'u2netp', 'silueta', etc.)
        alpha_matting: Enable alpha matting for edge refinement (default: False for safety)
        alpha_matting_foreground_threshold: Higher = keep more pixels as foreground (default: 270)
        alpha_matting_background_threshold: Higher = keep more pixels (default: 20)
        alpha_matting_erode_size: Edge erosion size (default: 5)
        dilate_foreground: Pixels to expand foreground mask (0 = no expansion, default: 3)

    Returns:
        PIL Image with transparent background (RGBA mode)
    """
    # Keep original frame for later
    original_frame = frame.copy()
    if original_frame.mode != 'RGB':
        original_frame = original_frame.convert('RGB')

    if alpha_matting:
        output = remove(
            frame,
            alpha_matting=True,
            alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=alpha_matting_background_threshold,
            alpha_matting_erode_size=alpha_matting_erode_size
        )
    else:
        # Conservative mode - no alpha matting
        output = remove(frame)

    # Ensure RGBA mode
    if output.mode != 'RGBA':
        output = output.convert('RGBA')

    # Post-process: expand foreground mask to be more conservative
    if dilate_foreground > 0:
        from scipy.ndimage import binary_dilation

        # Extract alpha channel from rembg output
        _, _, _, a = output.split()
        alpha_array = np.array(a)

        # Create binary mask (where alpha > very low threshold to catch everything)
        binary_mask = alpha_array > 10  # Very low threshold to catch even faint pixels

        # Dilate the mask aggressively
        structure = np.ones((dilate_foreground * 2 + 1, dilate_foreground * 2 + 1))
        dilated_mask = binary_dilation(binary_mask, structure=structure)

        # Create new alpha: fully opaque in dilated areas, fully transparent elsewhere
        new_alpha = np.where(dilated_mask, 255, 0).astype('uint8')
        new_alpha_img = Image.fromarray(new_alpha, 'L')

        # Use ORIGINAL image RGB values with new dilated alpha
        r_orig, g_orig, b_orig = original_frame.split()
        output = Image.merge('RGBA', (r_orig, g_orig, b_orig, new_alpha_img))

    return output


def reassemble_sprite_sheet(
    frames: List[Image.Image],
    grid_spec: Tuple[int, int],
    padding: int = 0
) -> Image.Image:
    """
    Reassemble processed frames back into a sprite sheet grid.

    Args:
        frames: List of PIL Image objects to reassemble
        grid_spec: Tuple of (rows, cols) for the grid layout
        padding: Pixels of spacing between frames

    Returns:
        PIL Image containing the reassembled sprite sheet (RGBA mode)

    Raises:
        ValueError: If number of frames doesn't match grid_spec
    """
    rows, cols = grid_spec
    expected_count = rows * cols

    if len(frames) != expected_count:
        raise ValueError(
            f"Frame count mismatch: expected {expected_count} frames "
            f"for {rows}x{cols} grid, got {len(frames)}"
        )

    # Get frame dimensions (assume all frames are the same size)
    frame_width, frame_height = frames[0].size

    # Calculate canvas dimensions
    canvas_width = cols * frame_width + (cols - 1) * padding
    canvas_height = rows * frame_height + (rows - 1) * padding

    # Create transparent canvas
    canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))

    # Paste frames
    for i, frame in enumerate(frames):
        row = i // cols
        col = i % cols
        x = col * (frame_width + padding)
        y = row * (frame_height + padding)

        # Paste with alpha channel as mask for proper transparency
        canvas.paste(frame, (x, y), frame if frame.mode == 'RGBA' else None)

    return canvas


def process_sprite_sheet(
    input_path: str,
    output_path: str,
    grid_spec: Tuple[int, int] = (2, 4),
    model_name: str = 'u2net',
    recombine: bool = True,
    padding: int = 0,
    save_individual_frames: bool = False,
    alpha_matting: bool = False,
    dilate_foreground: int = 3
) -> None:
    """
    Process a sprite sheet to remove backgrounds from all frames.

    Args:
        input_path: Path to input sprite sheet
        output_path: Path for output file(s)
        grid_spec: Tuple of (rows, cols) for the grid layout
        model_name: rembg model to use
        recombine: If True, reassemble into single sprite sheet;
                   if False, save individual frames
        padding: Pixels of spacing between frames (only used if recombine=True)
        save_individual_frames: If True, save individual frames in addition to
                                combined sheet (only used if recombine=True)
        alpha_matting: Enable alpha matting for edge refinement (False = more conservative)
        dilate_foreground: Pixels to expand foreground mask (higher = more conservative)
    """
    print(f"Processing: {input_path}")

    # Extract frames
    print(f"  Extracting {grid_spec[0]}x{grid_spec[1]} frames...")
    frames = extract_frames(input_path, grid_spec)

    # Process each frame
    mode = "with alpha matting" if alpha_matting else f"conservative mode (dilate={dilate_foreground})"
    print(f"  Removing backgrounds using {model_name} ({mode})...")
    processed_frames = []
    for i, frame in enumerate(frames, 1):
        print(f"    Frame {i}/{len(frames)}", end='\r')
        processed = remove_background_rembg(
            frame,
            model_name,
            alpha_matting=alpha_matting,
            dilate_foreground=dilate_foreground
        )
        processed_frames.append(processed)
    print(f"    Completed {len(frames)} frames")

    # Save output
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    if recombine:
        # Reassemble sprite sheet
        print(f"  Reassembling sprite sheet...")
        combined = reassemble_sprite_sheet(processed_frames, grid_spec, padding)
        combined.save(output_path)
        print(f"  Saved: {output_path}")

        # Optionally save individual frames too
        if save_individual_frames:
            frame_dir = output_path_obj.parent / f"{output_path_obj.stem}_frames"
            frame_dir.mkdir(exist_ok=True)
            for i, frame in enumerate(processed_frames):
                frame_path = frame_dir / f"frame_{i:02d}.png"
                frame.save(frame_path)
            print(f"  Saved individual frames to: {frame_dir}")
    else:
        # Save individual frames only
        frame_dir = output_path_obj.parent / output_path_obj.stem
        frame_dir.mkdir(exist_ok=True)
        for i, frame in enumerate(processed_frames):
            frame_path = frame_dir / f"frame_{i:02d}.png"
            frame.save(frame_path)
        print(f"  Saved individual frames to: {frame_dir}")


def create_gif_from_frames(
    frames: List[Image.Image],
    output_path: str,
    duration: int = 100,
    loop: int = 0
) -> None:
    """
    Create an animated GIF from a list of frames.

    Args:
        frames: List of PIL Image objects
        output_path: Path for output GIF file
        duration: Duration of each frame in milliseconds (default: 100ms)
        loop: Number of loops (0 = infinite loop)
    """
    if not frames:
        raise ValueError("No frames provided")

    # Ensure output directory exists
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Save as animated GIF
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=loop,
        disposal=2,  # Clear frame before rendering next
        optimize=False  # Keep quality high
    )


def process_animation_directory(
    input_dir: str,
    output_dir: str,
    pattern: str = '*.png',
    grid_spec: Tuple[int, int] = (2, 4),
    model_name: str = 'u2net',
    recombine: bool = True,
    padding: int = 0,
    suffix: str = '_transparent'
) -> None:
    """
    Process all sprite sheets in a directory.

    Args:
        input_dir: Directory containing sprite sheets
        output_dir: Directory for processed outputs
        pattern: Glob pattern for files to process
        grid_spec: Tuple of (rows, cols) for the grid layout
        model_name: rembg model to use
        recombine: If True, reassemble into single sprite sheet
        padding: Pixels of spacing between frames
        suffix: Suffix to add to output filenames
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all matching files
    files = sorted(input_path.glob(pattern))

    if not files:
        print(f"No files found matching pattern '{pattern}' in {input_dir}")
        return

    print(f"Found {len(files)} files to process\n")

    for i, img_file in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {img_file.name}")

        # Generate output filename
        output_filename = f"{img_file.stem}{suffix}{img_file.suffix}"
        output_file = output_path / output_filename

        try:
            process_sprite_sheet(
                str(img_file),
                str(output_file),
                grid_spec=grid_spec,
                model_name=model_name,
                recombine=recombine,
                padding=padding
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        print()  # Blank line between files

    print(f"Batch processing complete! Output saved to: {output_dir}")
