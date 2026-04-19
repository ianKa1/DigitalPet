"""Test generating creature action sequence coordinates using Gemini."""
import os
import sys
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import config
from google import genai


def test_get_creature_action_coordinates():
    """
    Ask Gemini to analyze the park image and return coordinates for a creature
    performing a sequence of actions: hop around, stop with curious look,
    bounce and turn to float.
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

    # Prompt for creature action sequence
    prompt = f"""Analyze this park image and design a movement path for a 2D cartoon creature that performs a sequence of actions.

**Task**: Return a JSON object with coordinate waypoints and action transitions for an animated creature.

**Image dimensions**: {img_width}x{img_height} pixels

**Action Sequence**:
1. **Hop around** (frames 0-40): The creature hops playfully across the scene, making small bouncing movements
2. **Stop with curious look** (frames 41-60): The creature stops and looks around curiously at its surroundings
3. **Bounce and turn to float** (frames 61-100): The creature makes a bigger bounce and transitions into floating/hovering

**Requirements**:
- Start position: left side of the image (x around 50-100, y at ground level)

**For hopping action (frames 0-40)**:
- The X-Y path should follow a SMOOTH CURVE along the ground that is semantically appropriate for the background
- Follow natural paths, grass areas, or walkways in the scene
- Avoid obstacles like trees, benches, and other objects
- The overall path direction should be smooth and natural (not zigzag)
- Add small Y-coordinate variations (±10-20 pixels) to show bouncing motion while following the ground curve
- Think of it as the creature hopping along a natural walking path in the park

**For stop action (frames 41-60)**:
- Stop position should be in an open area where the creature can look around
- Creature stays relatively stationary (same X position, minimal Y variation)

**For float action (frames 61-100)**:
- Path can be arbitrary and artistic since the creature is floating in the air
- Gradually rise above ground level
- Can follow any smooth floating pattern (S-curves, gentle arcs, etc.)

- Provide 40-50 total waypoints across all actions
- Each waypoint should include which action is active at that frame

**Output Format** (JSON only, no other text):
{{
    "image_width": {img_width},
    "image_height": {img_height},
    "total_frames": 100,
    "actions": [
        {{
            "action_name": "hop_around",
            "start_frame": 0,
            "end_frame": 40,
            "description": "Creature hops playfully with bouncing motion"
        }},
        {{
            "action_name": "stop_curious",
            "start_frame": 41,
            "end_frame": 60,
            "description": "Creature stops and looks around curiously"
        }},
        {{
            "action_name": "bounce_to_float",
            "start_frame": 61,
            "end_frame": 100,
            "description": "Creature bounces and transitions to floating"
        }}
    ],
    "waypoints": [
        {{"frame": 0, "x": 50, "y": 600, "action": "hop_around"}},
        {{"frame": 2, "x": 60, "y": 580, "action": "hop_around"}},
        {{"frame": 4, "x": 70, "y": 600, "action": "hop_around"}},
        ...
    ],
    "notes": "Brief description of the path and why these positions were chosen"
}}

Return ONLY valid JSON, nothing else."""

    print("\n🎬 Asking Gemini for creature action coordinates...")
    print(f"📝 Requesting action sequence: hop → stop curious → bounce to float\n")

    try:
        # Initialize Gemini client
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Call Gemini with vision capabilities
        response = client.models.generate_content(
            model='gemini-3.1-flash-image-preview',
            contents=[background_image, prompt]
        )

        # Extract JSON response
        if response.text:
            # Clean JSON (remove markdown code blocks if present)
            json_text = response.text.strip()
            if json_text.startswith('```'):
                # Remove markdown code block markers
                lines = json_text.split('\n')
                json_text = '\n'.join(lines[1:-1])

            # Parse JSON
            action_data = json.loads(json_text)

            print("✅ Received creature action coordinates!")
            print(f"   Total frames: {action_data.get('total_frames', 0)}")
            print(f"   Number of actions: {len(action_data.get('actions', []))}")
            print(f"   Number of waypoints: {len(action_data.get('waypoints', []))}")

            # Display action details
            print("\n📋 Action Breakdown:")
            for action in action_data.get('actions', []):
                print(f"   • {action['action_name']}: frames {action['start_frame']}-{action['end_frame']}")
                print(f"     {action['description']}")

            print(f"\n💡 Notes: {action_data.get('notes', 'N/A')}")

            # Save JSON
            json_output = output_dir / "creature_action_coordinates.json"
            with open(json_output, 'w') as f:
                json.dump(action_data, f, indent=2)
            print(f"\n💾 Saved coordinates to: {json_output}")

            # Visualize the path
            visualize_action_path(
                background_image,
                action_data,
                output_dir / "creature_action_visualized.png"
            )

            return action_data
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


def visualize_action_path(background_image, action_data, output_path):
    """Draw the creature action path on the background image with color-coded actions."""
    img = background_image.copy()
    draw = ImageDraw.Draw(img)

    waypoints = action_data.get('waypoints', [])
    actions = action_data.get('actions', [])

    if len(waypoints) < 2:
        print("⚠️  Not enough waypoints to draw path")
        return

    # Define colors for each action
    action_colors = {
        'hop_around': 'yellow',
        'stop_curious': 'cyan',
        'bounce_to_float': 'magenta'
    }

    print(f"\n   🎨 Visualizing creature action path...")

    # Draw lines between waypoints, colored by action
    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i + 1]

        x1, y1 = p1['x'], p1['y']
        x2, y2 = p2['x'], p2['y']
        action = p1.get('action', 'unknown')

        color = action_colors.get(action, 'white')
        draw.line([(x1, y1), (x2, y2)], fill=color, width=3)

    # Draw waypoint markers
    for i, point in enumerate(waypoints):
        x, y = point['x'], point['y']
        frame = point.get('frame', i)
        action = point.get('action', 'unknown')

        # Draw small circles at waypoints
        r = 4
        color = action_colors.get(action, 'white')
        draw.ellipse([x-r, y-r, x+r, y+r], fill=color, outline='white', width=1)

        # Label start, action transitions, and end
        if i == 0:
            draw.text((x+10, y-15), "START", fill='lime')
        elif i == len(waypoints) - 1:
            draw.text((x+10, y-15), "END", fill='red')
        # Mark action transitions
        elif i > 0 and waypoints[i-1].get('action') != action:
            draw.text((x+10, y-15), action.upper(), fill=color)

    # Add legend
    legend_x, legend_y = 10, 10
    draw.rectangle([legend_x, legend_y, legend_x + 200, legend_y + 100],
                   fill='black', outline='white', width=2)

    y_offset = legend_y + 10
    draw.text((legend_x + 10, y_offset), "Action Legend:", fill='white')
    y_offset += 20

    for action in actions:
        action_name = action['action_name']
        color = action_colors.get(action_name, 'white')
        frames = f"f{action['start_frame']}-{action['end_frame']}"

        # Draw color indicator
        draw.rectangle([legend_x + 10, y_offset, legend_x + 25, y_offset + 10],
                      fill=color)
        draw.text((legend_x + 30, y_offset - 2), f"{action_name} ({frames})",
                 fill='white')
        y_offset += 18

    # Save
    img.save(output_path)
    print(f"   ✅ Visualized path saved to: {output_path}")
    print(f"   Total waypoints: {len(waypoints)}")


def validate_action_sequence(action_data):
    """Validate the action sequence data for completeness and correctness."""
    print("\n🔍 Validating action sequence data...")

    issues = []
    warnings = []

    # Check required fields
    required_fields = ['image_width', 'image_height', 'total_frames', 'actions', 'waypoints']
    for field in required_fields:
        if field not in action_data:
            issues.append(f"Missing required field: {field}")

    if issues:
        print("   ❌ Validation failed:")
        for issue in issues:
            print(f"      • {issue}")
        return False

    # Validate actions
    actions = action_data.get('actions', [])
    expected_actions = ['hop_around', 'stop_curious', 'bounce_to_float']

    for expected in expected_actions:
        if not any(a['action_name'] == expected for a in actions):
            warnings.append(f"Expected action '{expected}' not found")

    # Check action frame continuity
    actions_sorted = sorted(actions, key=lambda a: a['start_frame'])
    for i in range(len(actions_sorted) - 1):
        if actions_sorted[i]['end_frame'] + 1 != actions_sorted[i + 1]['start_frame']:
            warnings.append(f"Frame gap between actions: {actions_sorted[i]['action_name']} and {actions_sorted[i + 1]['action_name']}")

    # Validate waypoints
    waypoints = action_data.get('waypoints', [])
    img_width = action_data['image_width']
    img_height = action_data['image_height']

    if len(waypoints) < 40:
        warnings.append(f"Only {len(waypoints)} waypoints (recommended: 40-50)")

    for i, wp in enumerate(waypoints):
        if wp['x'] < 0 or wp['x'] > img_width:
            issues.append(f"Waypoint {i} x-coordinate out of bounds: {wp['x']}")
        if wp['y'] < 0 or wp['y'] > img_height:
            issues.append(f"Waypoint {i} y-coordinate out of bounds: {wp['y']}")

    # Check if path starts on left and progresses
    if waypoints:
        first_x = waypoints[0]['x']
        if first_x > 200:
            warnings.append(f"Path starts far from left edge (x={first_x})")

    # Print results
    if issues:
        print("   ❌ Validation failed:")
        for issue in issues:
            print(f"      • {issue}")
        return False

    if warnings:
        print("   ⚠️  Validation passed with warnings:")
        for warning in warnings:
            print(f"      • {warning}")
    else:
        print("   ✅ Validation passed!")

    return True


if __name__ == "__main__":
    print("=" * 70)
    print("Creature Action Sequence Coordinates Test")
    print("=" * 70)

    print("\n📋 Test: Generate creature action coordinates")
    print("-" * 70)
    action_data = test_get_creature_action_coordinates()

    if action_data:
        print("\n📋 Validating action sequence data")
        print("-" * 70)
        validate_action_sequence(action_data)

    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)
