"""Test getting path coordinates from Gemini instead of generating path images."""
import os
import sys
import json
from pathlib import Path
from PIL import Image, ImageDraw

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import config
from google import genai


def test_get_path_coordinates():
    """
    Ask Gemini to analyze an image and return path coordinates as JSON.

    This is better than generating an image because we get precise pixel
    coordinates that can be used for animation.
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping test.")
        return

    # Setup
    test_dir = Path(__file__).parent
    background_path = test_dir / "background" / "park.jpg"
    output_dir = test_dir / "output"
    output_dir.mkdir(exist_ok=True)

    if not background_path.exists():
        print(f"❌ Background image not found: {background_path}")
        return

    print(f"📸 Loading background image: {background_path}")
    background_image = Image.open(background_path)
    img_width, img_height = background_image.size
    print(f"   Image size: {img_width}x{img_height}")

    # Prompt asking for JSON coordinates
    prompt = f"""Analyze this park image and design a smooth walking path for a 2D cartoon character.

**Task**: Return a JSON object with a list of (x, y) coordinate points that form a natural walking path.

**Requirements**:
- Image dimensions: {img_width}x{img_height} pixels
- Start from the left side (x around 50-100)
- End on the right side (x around {img_width-100}-{img_width-50})
- Path should follow the ground level and natural surfaces
- Avoid obstacles like trees, benches, and other objects
- Use 15-25 waypoints for a smooth curve
- Y-coordinates should reflect realistic ground elevation
- Points should be evenly spaced along the path

**Output Format** (JSON only, no other text):
{{
    "path_name": "walking_path",
    "image_width": {img_width},
    "image_height": {img_height},
    "waypoints": [
        {{"x": 50, "y": 600}},
        {{"x": 150, "y": 590}},
        ...
    ],
    "description": "Brief description of the path route"
}}

Return ONLY valid JSON, nothing else."""

    print("\n🎬 Asking Gemini for path coordinates...")
    print(f"📝 Requesting {15}-{25} waypoints\n")

    try:
        # Initialize Gemini client (use regular model, not Flash Image)
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Call Gemini with vision capabilities
        response = client.models.generate_content(
            model='gemini-3.1-flash-image-preview',  # Use the working model
            contents=[background_image, prompt]
        )

        # Extract JSON response
        if response.text:
            # Clean JSON (remove markdown code blocks if present)
            json_text = response.text.strip()
            if json_text.startswith('```'):
                # Remove markdown code block markers
                lines = json_text.split('\n')
                json_text = '\n'.join(lines[1:-1])  # Remove first and last lines

            # Parse JSON
            path_data = json.loads(json_text)

            print("✅ Received path coordinates!")
            print(f"   Path name: {path_data.get('path_name', 'unknown')}")
            print(f"   Number of waypoints: {len(path_data.get('waypoints', []))}")
            print(f"   Description: {path_data.get('description', 'N/A')}")

            # Save JSON
            json_output = output_dir / "path_coordinates.json"
            with open(json_output, 'w') as f:
                json.dump(path_data, f, indent=2)
            print(f"\n💾 Saved coordinates to: {json_output}")

            # Visualize the path by drawing it on the background
            visualize_path(background_image, path_data, output_dir / "path_visualized.png")

            return path_data
        else:
            print("❌ No response text")
            print(f"Response: {response}")

    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON response: {e}")
        print(f"Raw response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def visualize_path(background_image, path_data, output_path):
    """Draw the path coordinates on the background image for visualization."""
    img = background_image.copy()
    draw = ImageDraw.Draw(img)

    waypoints = path_data.get('waypoints', [])
    if len(waypoints) < 2:
        print("⚠️  Not enough waypoints to draw path")
        return

    # Draw the path as connected lines
    points = [(p['x'], p['y']) for p in waypoints]
    draw.line(points, fill='white', width=4)

    # Draw waypoint markers
    for i, point in enumerate(points):
        x, y = point
        # Draw small circles at waypoints
        r = 5
        draw.ellipse([x-r, y-r, x+r, y+r], fill='yellow', outline='red', width=2)

        # Label first and last points
        if i == 0:
            draw.text((x+10, y-10), "START", fill='lime')
        elif i == len(points) - 1:
            draw.text((x+10, y-10), "END", fill='red')

    # Save
    img.save(output_path)
    print(f"   🎨 Visualized path saved to: {output_path}")
    print(f"   Path length: {len(points)} waypoints")


def test_interpolate_path():
    """Test interpolating between waypoints for smooth animation."""
    output_dir = Path(__file__).parent / "output"
    json_path = output_dir / "path_coordinates.json"

    if not json_path.exists():
        print("⚠️  Run test_get_path_coordinates() first to generate coordinates")
        return

    with open(json_path, 'r') as f:
        path_data = json.load(f)

    waypoints = path_data.get('waypoints', [])
    print(f"\n🎮 Interpolating path for smooth animation...")
    print(f"   Original waypoints: {len(waypoints)}")

    # Interpolate to get more points for smoother animation
    interpolated = interpolate_waypoints(waypoints, points_per_segment=10)
    print(f"   Interpolated points: {len(interpolated)}")
    print(f"   This gives you {len(interpolated)} animation frames!")

    # Save interpolated path
    interpolated_data = {
        **path_data,
        'waypoints': interpolated,
        'interpolated': True
    }

    interpolated_path = output_dir / "path_coordinates_interpolated.json"
    with open(interpolated_path, 'w') as f:
        json.dump(interpolated_data, f, indent=2)
    print(f"   💾 Saved to: {interpolated_path}")

    return interpolated


def interpolate_waypoints(waypoints, points_per_segment=10):
    """Linear interpolation between waypoints."""
    if len(waypoints) < 2:
        return waypoints

    interpolated = []

    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i + 1]

        # Add the current point
        interpolated.append(p1)

        # Interpolate between p1 and p2
        for j in range(1, points_per_segment):
            t = j / points_per_segment
            x = int(p1['x'] + (p2['x'] - p1['x']) * t)
            y = int(p1['y'] + (p2['y'] - p1['y']) * t)
            interpolated.append({'x': x, 'y': y})

    # Add the last point
    interpolated.append(waypoints[-1])

    return interpolated


if __name__ == "__main__":
    print("=" * 60)
    print("Path Coordinates Test")
    print("=" * 60)

    print("\n📋 Test 1: Get path coordinates from Gemini")
    print("-" * 60)
    path_data = test_get_path_coordinates()

    if path_data:
        print("\n📋 Test 2: Interpolate path for animation")
        print("-" * 60)
        test_interpolate_path()

    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)
