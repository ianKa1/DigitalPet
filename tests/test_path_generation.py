"""Test path generation on real-world backgrounds using Gemini Flash Image."""
import os
import sys
from pathlib import Path
from PIL import Image

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import config
from google import genai


def test_generate_path_on_background():
    """
    Test generating a reasonable path for a 2D cartoon character on a real-world image.

    This test asks Gemini to draw a white path line that a 2D character could follow
    across a background image (like a park scene).
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping path generation test.")
        return

    # Setup
    test_dir = Path(__file__).parent
    background_path = test_dir / "background" / "park.jpg"
    output_dir = test_dir / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "park_with_path.png"

    if not background_path.exists():
        print(f"❌ Background image not found: {background_path}")
        return

    print(f"📸 Loading background image: {background_path}")
    background_image = Image.open(background_path)

    # Refined prompt for path generation
    prompt = """Draw a smooth, curved white path line on this image that would be suitable for a 2D cartoon character to walk along.

Requirements for the path:
- The path should be a continuous white line (3-5 pixels thick for visibility)
- Start from the left side of the image and end on the right side
- The path should follow realistic movement patterns:
  * Follow the ground level and natural surfaces
  * Avoid obstacles like trees, benches, or other objects
  * Use gentle curves that look natural for walking
  * Can include slight elevation changes if there are hills or steps
- The path should be clearly visible against the background
- Make it look like a route a small pet or character would naturally take through this scene

Style: Simple white line path overlay, clean and minimalistic, suitable for a 2D platformer or pet simulation game."""

    print("🎬 Asking Gemini to generate path...")
    print(f"\n📝 Prompt:\n{prompt}\n")

    try:
        # Initialize Gemini client
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Prepare contents with background image and prompt
        contents = [
            background_image,
            prompt
        ]

        # Call Gemini Flash Image API
        response = client.models.generate_content(
            model='gemini-3.1-flash-image-preview',
            contents=contents
        )

        # Extract and save the generated image
        if response.candidates and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # Save the image
                        image_data = part.inline_data.data
                        with open(output_path, 'wb') as f:
                            f.write(image_data)

                        print(f"✅ Path generated successfully!")
                        print(f"   Output saved to: {output_path}")

                        # Verify the image
                        result_image = Image.open(output_path)
                        print(f"   Image size: {result_image.size}")
                        print(f"   Image mode: {result_image.mode}")

                        return output_path

        print("❌ No image data in response")
        print(f"Response: {response}")

    except Exception as e:
        print(f"❌ Error generating path: {e}")
        import traceback
        traceback.print_exc()


def test_generate_multiple_path_styles():
    """
    Test generating different path styles (simple walk, jumping arc, flying).
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping test.")
        return

    test_dir = Path(__file__).parent
    background_path = test_dir / "background" / "park.jpg"
    output_dir = test_dir / "output"
    output_dir.mkdir(exist_ok=True)

    if not background_path.exists():
        print(f"❌ Background image not found: {background_path}")
        return

    background_image = Image.open(background_path)
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    # Different path styles
    path_styles = {
        "walking": "Draw a white walking path that follows the ground level, with gentle curves",
        "hopping": "Draw a white dotted path showing hopping/jumping arcs, with small parabolic curves above the ground",
        "flying": "Draw a white flowing path that floats above the ground, with smooth S-curves through the air"
    }

    for style_name, style_prompt in path_styles.items():
        print(f"\n🎨 Generating {style_name} path...")

        full_prompt = f"""{style_prompt}.

The path should:
- Start from the left side and end on the right side
- Be clearly visible as a white line (3-5 pixels thick)
- Look natural for a 2D cartoon character's movement
- Avoid major obstacles in the scene

Style: Clean white line suitable for a 2D game path visualization."""

        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-image-preview',
                contents=[background_image, full_prompt]
            )

            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            output_path = output_dir / f"park_path_{style_name}.png"
                            with open(output_path, 'wb') as f:
                                f.write(part.inline_data.data)
                            print(f"   ✅ Saved: {output_path}")

        except Exception as e:
            print(f"   ❌ Error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Path Generation Test")
    print("=" * 60)

    print("\n📋 Test 1: Generate single walking path")
    print("-" * 60)
    test_generate_path_on_background()

    print("\n\n📋 Test 2: Generate multiple path styles")
    print("-" * 60)
    test_generate_multiple_path_styles()

    print("\n" + "=" * 60)
    print("All tests complete!")
    print("=" * 60)
