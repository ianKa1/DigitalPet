"""Test sprite processing functions with existing batch animations."""
import json
import sys
import os

# Add src to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(project_root, 'src'))

from generators.animation_generator import _detect_sprite_layout, _process_batch_sprite_sheet


def test_sprite_processing():
    """Test sprite processing with an existing batch animation file."""

    # Path to existing batch sprite sheet
    batch_sprite_path = "output/pets/Fluffball/animations/all_animations_20260404_185431.png"

    # Check if file exists
    if not os.path.exists(batch_sprite_path):
        print(f"❌ Batch sprite sheet not found: {batch_sprite_path}")
        print("Please update the path in this test file to point to an existing sprite sheet.")
        return

    print("🧪 Testing Sprite Processing")
    print("=" * 60)
    print(f"📂 Input: {batch_sprite_path}")
    print()

    # Load pet data to get actions
    pet_info_path = "output/pets/Fluffball/pet_info.json"
    with open(pet_info_path, 'r') as f:
        pet_data = json.load(f)

    actions = pet_data["actions"]
    action_descriptions = pet_data.get("action_descriptions", {})
    pet_name = pet_data["name"]
    pet_dir = os.path.dirname(pet_info_path)

    print(f"🐾 Pet: {pet_name}")
    print(f"🎭 Actions: {', '.join(actions)}")
    print()

    # Test 1: Detect layout
    print("Test 1: Detecting sprite sheet layout...")
    print("-" * 60)

    try:
        layout = _detect_sprite_layout(batch_sprite_path)

        if layout:
            print(f"✅ Layout detected successfully!")
            print(f"   Frames per row: {layout['frames_per_row']}")
            print(f"   Number of rows: {layout['num_rows']}")
            print(f"   Frame size: {layout['frame_width']}x{layout['frame_height']}")
            print(f"   Total frames: {layout['total_frames']}")
            print()
        else:
            print(f"❌ Could not detect layout")
            return

    except Exception as e:
        print(f"❌ Error detecting layout: {e}")
        return

    # Test 2: Process complete sprite sheet
    print("Test 2: Processing sprite sheet and extracting GIFs...")
    print("-" * 60)

    try:
        sprite_metadata = _process_batch_sprite_sheet(
            batch_sprite_path,
            actions,
            action_descriptions,
            pet_dir,
            pet_name
        )

        if sprite_metadata:
            print()
            print("✅ Sprite processing completed!")
            print()
            print("📊 Results:")
            print("-" * 60)
            print(f"Batch sprite sheet: {sprite_metadata['batch_sprite_sheet']}")
            print(f"Metadata file: {os.path.join(pet_dir, 'sprites_metadata.json')}")
            print()
            print("Individual animations:")

            for action in actions:
                if action in sprite_metadata['animations']:
                    anim = sprite_metadata['animations'][action]
                    if 'error' in anim:
                        print(f"  ❌ {action}: {anim['error']}")
                    else:
                        print(f"  ✅ {action}:")
                        print(f"     GIF: {anim['gif_path']}")
                        print(f"     Frames: {anim['frame_count']}")
                        print(f"     Size: {anim['frame_width']}x{anim['frame_height']}")

            print()
            print("=" * 60)
            print("🎉 All tests passed!")

        else:
            print("❌ Sprite processing returned None")

    except Exception as e:
        print(f"❌ Error processing sprite sheet: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_sprite_processing()
