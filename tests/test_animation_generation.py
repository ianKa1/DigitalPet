"""Test sprite animation generation using existing pet data."""
import sys
import json
import argparse
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generators import generate_sprite_animations_batch
from src import config


def list_available_pets():
    """List all available pets in output/pets directory."""
    pets_dir = Path(config.PETS_DIR)
    if not pets_dir.exists():
        return []

    pets = []
    for pet_path in pets_dir.iterdir():
        if pet_path.is_dir() and (pet_path / "pet_info.json").exists():
            pets.append(pet_path.name)

    return sorted(pets)


def load_pet_data(pet_name):
    """Load pet data from pet_info.json."""
    pet_info_path = Path(config.PETS_DIR) / pet_name / "pet_info.json"

    if not pet_info_path.exists():
        raise FileNotFoundError(f"Pet info not found: {pet_info_path}")

    with open(pet_info_path, 'r') as f:
        return json.load(f)


def main():
    """Run sprite animation generation for an existing pet."""
    parser = argparse.ArgumentParser(
        description="Generate sprite animations for an existing pet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available pets
  python test_animation_generation.py --list

  # Generate animations for a specific pet
  python test_animation_generation.py --pet Mossling
  python test_animation_generation.py --pet Nimbusnout
        """
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available pets"
    )

    parser.add_argument(
        "--pet",
        type=str,
        help="Name of the pet to generate animations for"
    )

    args = parser.parse_args()

    # List available pets
    available_pets = list_available_pets()

    if args.list:
        print("=" * 60)
        print("Available Pets")
        print("=" * 60)
        if available_pets:
            for pet in available_pets:
                print(f"  • {pet}")
        else:
            print("  No pets found in output/pets/")
        print()
        return

    # Determine which pet to use
    if args.pet:
        pet_name = args.pet
    elif available_pets:
        pet_name = available_pets[0]
        print(f"ℹ️  No pet specified, using first available: {pet_name}")
    else:
        print("❌ No pets found in output/pets/")
        print("   Run main.py first to generate a pet, or use --list to see available pets")
        return

    # Verify pet exists
    if pet_name not in available_pets:
        print(f"❌ Pet '{pet_name}' not found")
        print(f"   Available pets: {', '.join(available_pets)}")
        return

    print("=" * 60)
    print(f"Generating Sprite Animations for: {pet_name}")
    print("=" * 60)

    # Load pet data
    try:
        pet_data = load_pet_data(pet_name)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    print(f"\nPet: {pet_data.get('name')}")
    print(f"Species: {pet_data.get('species')}")
    print(f"Personality: {', '.join(pet_data.get('personality', []))}")

    # Check if pet has actions
    actions = pet_data.get('actions', [])
    if not actions:
        print("\n❌ This pet has no actions defined")
        print("   Run test_pet_actions.py first to generate actions")
        return

    print(f"Actions: {', '.join(actions)}")
    print()

    # Step 4: Generate sprite animations
    print("🎬 Step 4: Generating sprite animations...")
    sprite_metadata = generate_sprite_animations_batch(pet_data, actions)

    if sprite_metadata:
        print("\n" + "=" * 60)
        print("✅ Animation Generation Complete!")
        print("=" * 60)
        print(f"\nBatch sprite sheet: {sprite_metadata['batch_sprite_sheet']}")
        print(f"Extracted {len(sprite_metadata['animations'])} individual GIFs:\n")

        for action in actions:
            if action in sprite_metadata['animations']:
                anim = sprite_metadata['animations'][action]
                if 'error' in anim:
                    print(f"  ❌ {action}: {anim['error']}")
                else:
                    print(f"  ✅ {action}: {anim['gif_path']}")
    else:
        print("\n" + "=" * 60)
        print("❌ Animation Generation Failed")
        print("=" * 60)


if __name__ == "__main__":
    main()
