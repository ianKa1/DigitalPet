"""Test pet action generation with Mossling."""
import sys
import json
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generators import generate_pet_actions


def main():
    """Generate actions for Mossling pet."""
    # Load Mossling's pet_info.json
    pet_info_path = Path(__file__).parent.parent / "output" / "pets" / "Mossling" / "pet_info.json"

    if not pet_info_path.exists():
        print(f"❌ Pet info not found: {pet_info_path}")
        return

    print("=" * 60)
    print("Generating Actions for Mossling")
    print("=" * 60)

    with open(pet_info_path, 'r') as f:
        pet_description = json.load(f)

    print(f"\nPet: {pet_description.get('name')}")
    print(f"Species: {pet_description.get('species')}")
    print(f"Personality: {', '.join(pet_description.get('personality', []))}")
    print(f"Special Ability: {pet_description.get('special_ability')}")
    print()

    # Generate actions
    actions = generate_pet_actions(pet_description)

    if actions:
        print("\n" + "=" * 60)
        print("✅ Action Generation Complete!")
        print("=" * 60)

        # Reload and display the updated pet_info.json
        with open(pet_info_path, 'r') as f:
            updated_pet = json.load(f)

        print(f"\nGenerated Actions: {', '.join(updated_pet.get('actions', []))}")
        print("\nAction Descriptions:")
        for action, description in updated_pet.get('action_descriptions', {}).items():
            print(f"  • {action}: {description}")
    else:
        print("\n" + "=" * 60)
        print("❌ Action Generation Failed")
        print("=" * 60)


if __name__ == "__main__":
    main()
