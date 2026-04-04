"""Main script to generate a digital pet with personality and animations."""
import json
from generators import (
    generate_pet_description,
    generate_pet_image,
    generate_pet_actions,
    generate_sprite_animations,
)


def main():
    """Run the complete digital pet generation pipeline."""
    print("🐾 Welcome to DigitalPet Generator!")
    print("=" * 50)
    print("\n⚠️  TEST MODE: Only running animation generation (Step 4)")
    print("=" * 50)

    # BLOCKED: Step 1 - Generate pet personality and appearance
    # print("\n📝 Step 1: Generating pet personality and appearance...")
    # pet_description = generate_pet_description()
    # print(f"\n✨ Generated Pet:\n{json.dumps(pet_description, indent=2)}")

    # BLOCKED: Step 2 - Generate pet image
    # print("\n🎨 Step 2: Generating pet image...")
    # pet_image_path = generate_pet_image(pet_description)
    # print(f"✅ Pet image saved to: {pet_image_path}")

    # BLOCKED: Step 3 - Generate actions based on personality
    # print("\n🎭 Step 3: Generating pet actions...")
    # actions = generate_pet_actions(pet_description)
    # print(f"✅ Generated actions: {', '.join(actions)}")

    # Test data for animation generation
    print("\n📋 Using test data from example pet (Fluffball)...")
    pet_description = {
        "name": "Fluffball",
        "species": "Cloud Bunny",
        "personality": ["playful", "curious", "gentle", "bouncy"],
        "appearance": "A small fluffy creature that looks like a bunny made of soft white clouds. Has large sparkly blue eyes, tiny pink nose, and long floppy ears that seem to float. Its body is round and puffy like a cotton ball. Small paws peek out from the fluffy cloud body. Leaves tiny sparkles when it moves.",
        "special_ability": "Can float on air currents and create small rainbow trails"
    }
    actions = ["idle", "hop", "float"]
    print(f"✅ Test pet: {pet_description['name']} ({pet_description['species']})")
    print(f"✅ Test actions: {', '.join(actions)}")

    # Step 4: Generate sprite animations for each action
    print("\n🎬 Step 4: Generating sprite animations...")
    animation_paths = generate_sprite_animations(pet_description, actions)
    print(f"✅ Animations saved!")
    for action, path in animation_paths.items():
        print(f"  - {action}: {path}")

    print("\n🎉 Animation generation test complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
