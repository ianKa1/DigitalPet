"""Test script for batch animation generation."""
import sys
import json
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from generators import generate_sprite_animations_batch


def main():
    """Test batch animation generation with Fluffball."""
    print("=" * 70)
    print("Batch Animation Generation Test")
    print("=" * 70)

    # Load Fluffball pet data
    print("\n📋 Loading Fluffball pet data...")
    with open("output/pets/Fluffball/pet_info.json", "r") as f:
        pet_data = json.load(f)

    # Extract pet description
    pet_description = {
        "name": pet_data["name"],
        "species": pet_data["species"],
        "personality": pet_data["personality"],
        "appearance": pet_data["appearance"],
        "special_ability": pet_data["special_ability"]
    }

    # Use all actions
    actions = pet_data["actions"]
    action_descriptions = pet_data.get("action_descriptions", {})

    print(f"✅ Pet: {pet_description['name']} ({pet_description['species']})")
    print(f"✅ Actions to generate: {', '.join(actions)}")

    # Generate all animations in one batch
    print("\n🎬 Generating batch sprite sheet...")
    sprite_sheet_path = generate_sprite_animations_batch(
        pet_description,
        actions,
        action_descriptions
    )

    if sprite_sheet_path:
        print(f"\n✅ Complete sprite sheet saved: {sprite_sheet_path}")
    else:
        print(f"\n❌ Batch animation generation failed")

    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
