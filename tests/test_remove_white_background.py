"""Utility to remove white background from GIF and make it transparent."""
import sys
from pathlib import Path
from PIL import Image, ImageSequence
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def remove_white_background(input_gif_path, output_gif_path, threshold=240):
    """
    Convert white (or near-white) pixels in a GIF to transparent.

    Args:
        input_gif_path: Path to input GIF
        output_gif_path: Path to save transparent GIF
        threshold: RGB value threshold (0-255). Pixels with R, G, B all above
                   this value will become transparent. Default 240 makes
                   near-white pixels transparent.

    Returns:
        str: Path to output GIF
    """
    print(f"🎨 Removing white background from: {input_gif_path.name}")
    print(f"   Threshold: {threshold} (pixels with R,G,B > {threshold} become transparent)")

    # Load GIF
    gif = Image.open(input_gif_path)

    # Process each frame
    transparent_frames = []
    frame_count = 0

    for frame in ImageSequence.Iterator(gif):
        frame_count += 1

        # Convert to RGBA
        frame_rgba = frame.convert('RGBA')

        # Convert to numpy array for easier manipulation
        data = np.array(frame_rgba)

        # Get RGB channels
        r, g, b, a = data.T

        # Find white (or near-white) pixels
        # White pixels are where R, G, and B are all above threshold
        white_areas = (r > threshold) & (g > threshold) & (b > threshold)

        # Set alpha to 0 (transparent) for white pixels
        data[white_areas.T] = [255, 255, 255, 0]

        # Convert back to PIL Image
        transparent_frame = Image.fromarray(data)
        transparent_frames.append(transparent_frame)

    print(f"   Processed {frame_count} frames")

    # Save as transparent GIF
    if transparent_frames:
        # Get original GIF duration
        try:
            duration = gif.info.get('duration', 100)
        except:
            duration = 100

        transparent_frames[0].save(
            output_gif_path,
            save_all=True,
            append_images=transparent_frames[1:],
            duration=duration,
            loop=0,
            disposal=2,  # Clear frame before rendering next
            transparency=0,  # Enable transparency
            optimize=False
        )

        print(f"✅ Saved transparent GIF: {output_gif_path}")
        print(f"   Original size: {input_gif_path.stat().st_size / 1024:.1f} KB")
        print(f"   New size: {output_gif_path.stat().st_size / 1024:.1f} KB")

        return output_gif_path
    else:
        print("❌ No frames processed")
        return None


def test_remove_white_background():
    """Test removing white background from hop.gif."""
    test_dir = Path(__file__).parent
    project_dir = test_dir.parent

    input_gif = project_dir / "output" / "pets" / "Fluffball" / "animations" / "hop.gif"
    output_dir = test_dir / "output"
    output_gif = output_dir / "hop_transparent.gif"

    if not input_gif.exists():
        print(f"❌ Input GIF not found: {input_gif}")
        return

    # Remove white background
    result = remove_white_background(input_gif, output_gif, threshold=240)

    if result:
        # Show before/after comparison
        print("\n📊 Comparison:")
        print("   Before: White background")
        print("   After: Transparent background")
        print(f"\n💡 You can adjust threshold (currently 240):")
        print("   - Lower threshold (e.g., 200): More aggressive, removes light grays too")
        print("   - Higher threshold (e.g., 250): Only removes pure white")

    return result


def test_different_thresholds():
    """Test different threshold values to find the best one."""
    test_dir = Path(__file__).parent
    project_dir = test_dir.parent

    input_gif = project_dir / "output" / "pets" / "Fluffball" / "animations" / "hop.gif"
    output_dir = test_dir / "output"

    if not input_gif.exists():
        print(f"❌ Input GIF not found: {input_gif}")
        return

    print("\n🧪 Testing different thresholds...")
    print("-" * 60)

    thresholds = [200, 220, 240, 250]

    for threshold in thresholds:
        output_gif = output_dir / f"hop_transparent_{threshold}.gif"
        print(f"\n🎯 Threshold: {threshold}")
        remove_white_background(input_gif, output_gif, threshold=threshold)


if __name__ == "__main__":
    print("=" * 60)
    print("Remove White Background Test")
    print("=" * 60)

    print("\n📋 Test 1: Remove white background (threshold=240)")
    print("-" * 60)
    result = test_remove_white_background()

    if result:
        print("\n📋 Test 2: Try different thresholds")
        print("-" * 60)
        test_different_thresholds()

    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)
    print("\n💡 Next step: Use hop_transparent.gif in test_animate_pet_on_path.py")
