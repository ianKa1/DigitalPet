"""Test animating a pet GIF along a path on a background image."""
import os
import sys
import json
from pathlib import Path
from PIL import Image, ImageSequence

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_animate_pet_on_path():
    """
    Composite a pet GIF onto a background and animate it along a path.

    This creates a complete animation of the pet moving through the scene.
    """
    # Setup pathsß
    test_dir = Path(__file__).parent
    project_dir = test_dir.parent

    background_path = test_dir / "background" / "park.jpg"
    # Use transparent version if available, otherwise use original
    pet_gif_transparent = test_dir / "output" / "hop_transparent_250.gif"
    pet_gif_original = project_dir / "output" / "pets" / "Fluffball" / "animations" / "hop.gif"
    pet_gif_path = pet_gif_transparent if pet_gif_transparent.exists() else pet_gif_original
    path_json_path = test_dir / "output" / "path_coordinates_interpolated.json"
    output_dir = test_dir / "output"
    output_path = output_dir / "pet_on_path.gif"

    # Verify all files exist
    if not background_path.exists():
        print(f"❌ Background not found: {background_path}")
        return

    if not pet_gif_path.exists():
        print(f"❌ Pet GIF not found: {pet_gif_path}")
        return

    if not path_json_path.exists():
        print(f"❌ Path coordinates not found: {path_json_path}")
        print("   Run test_path_coordinates.py first to generate path data")
        return

    print("🎬 Animating pet along path...")
    print(f"   Background: {background_path.name}")
    print(f"   Pet: {pet_gif_path.name}")
    print(f"   Path: {path_json_path.name}")

    # Load background
    background = Image.open(background_path)
    bg_width, bg_height = background.size
    print(f"\n📐 Background size: {bg_width}x{bg_height}")

    # Load pet GIF frames
    pet_gif = Image.open(pet_gif_path)
    pet_frames = []
    for frame in ImageSequence.Iterator(pet_gif):
        # Convert to RGBA for transparency
        pet_frames.append(frame.convert('RGBA'))

    pet_width, pet_height = pet_frames[0].size
    print(f"🐰 Pet sprite size: {pet_width}x{pet_height}")
    print(f"   Pet frames: {len(pet_frames)}")

    # Load path coordinates
    with open(path_json_path, 'r') as f:
        path_data = json.load(f)

    waypoints = path_data['waypoints']
    print(f"🛤️  Path waypoints: {len(waypoints)}")

    # Create animation frames
    output_frames = []
    frame_duration = 50  # milliseconds per frame

    print("\n🎨 Generating animation frames...")

    for i, point in enumerate(waypoints):
        # Get position (center the pet on the waypoint)
        x = point['x'] - pet_width // 2
        y = point['y'] - pet_height // 2

        # Ensure pet stays within background bounds
        x = max(0, min(x, bg_width - pet_width))
        y = max(0, min(y, bg_height - pet_height))

        # Cycle through pet animation frames
        pet_frame = pet_frames[i % len(pet_frames)]

        # Composite pet onto background
        bg_copy = background.copy().convert('RGBA')
        bg_copy.paste(pet_frame, (x, y), pet_frame)

        # Convert back to RGB for GIF
        output_frames.append(bg_copy.convert('RGB'))

        if (i + 1) % 20 == 0:
            print(f"   Generated {i + 1}/{len(waypoints)} frames...")

    print(f"✅ Generated {len(output_frames)} frames")

    # Save as animated GIF
    print(f"\n💾 Saving animation to: {output_path}")
    output_frames[0].save(
        output_path,
        save_all=True,
        append_images=output_frames[1:],
        duration=frame_duration,
        loop=0,
        optimize=False
    )

    # Calculate animation stats
    total_duration = len(output_frames) * frame_duration / 1000  # seconds
    print(f"✅ Animation saved!")
    print(f"   Total frames: {len(output_frames)}")
    print(f"   Duration: {total_duration:.1f}s")
    print(f"   Frame rate: ~{1000/frame_duration:.0f} fps")
    print(f"   File size: {output_path.stat().st_size / 1024:.1f} KB")

    return output_path


def test_animate_with_speed_variation():
    """
    Advanced version with variable speed along the path.

    Slows down on curves, speeds up on straight sections.
    """
    test_dir = Path(__file__).parent
    project_dir = test_dir.parent

    background_path = test_dir / "background" / "park.jpg"
    pet_gif_path = project_dir / "output" / "pets" / "Fluffball" / "animations" / "hop.gif"
    path_json_path = test_dir / "output" / "path_coordinates.json"  # Use original waypoints
    output_dir = test_dir / "output"
    output_path = output_dir / "pet_on_path_variable_speed.gif"

    if not all([background_path.exists(), pet_gif_path.exists(), path_json_path.exists()]):
        print("⚠️  Required files not found for variable speed test")
        return

    print("\n🎬 Animating with variable speed...")

    # Load data
    background = Image.open(background_path)
    pet_gif = Image.open(pet_gif_path)
    pet_frames = [frame.convert('RGBA') for frame in ImageSequence.Iterator(pet_gif)]
    pet_width, pet_height = pet_frames[0].size

    with open(path_json_path, 'r') as f:
        path_data = json.load(f)

    waypoints = path_data['waypoints']

    # Calculate speed for each segment based on curvature
    output_frames = []
    frame_idx = 0

    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i + 1]

        # Calculate distance
        dx = p2['x'] - p1['x']
        dy = p2['y'] - p1['y']
        distance = (dx**2 + dy**2) ** 0.5

        # More frames = slower movement
        # Adjust based on curve (simplified: use distance)
        num_interpolations = max(5, int(distance / 20))

        # Interpolate between waypoints
        for j in range(num_interpolations):
            t = j / num_interpolations
            x = int(p1['x'] + dx * t - pet_width // 2)
            y = int(p1['y'] + dy * t - pet_height // 2)

            # Bounds check
            x = max(0, min(x, background.width - pet_width))
            y = max(0, min(y, background.height - pet_height))

            # Composite
            pet_frame = pet_frames[frame_idx % len(pet_frames)]
            bg_copy = background.copy().convert('RGBA')
            bg_copy.paste(pet_frame, (x, y), pet_frame)
            output_frames.append(bg_copy.convert('RGB'))

            frame_idx += 1

    # Save
    output_frames[0].save(
        output_path,
        save_all=True,
        append_images=output_frames[1:],
        duration=50,
        loop=0,
        optimize=False
    )

    print(f"✅ Variable speed animation saved: {output_path}")
    print(f"   Frames: {len(output_frames)}")

    return output_path


if __name__ == "__main__":
    print("=" * 60)
    print("Animate Pet on Path Test")
    print("=" * 60)

    print("\n📋 Test 1: Animate pet along interpolated path")
    print("-" * 60)
    result = test_animate_pet_on_path()

    if result:
        print("\n📋 Test 2: Variable speed animation")
        print("-" * 60)
        test_animate_with_speed_variation()

    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)
