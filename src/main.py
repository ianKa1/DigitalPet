"""Main script to generate a digital pet with personality and animations."""
import json
from generators import (
    generate_pet_description,
    generate_pet_image,
    generate_pet_actions,
    generate_sprite_animations,
    generate_sprite_animations_batch
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

    # Load test data from example pet (Fluffball)
    print("\n📋 Loading test data from Fluffball example pet...")
    with open("output/pets/Fluffball/pet_info.json", "r") as f:
        pet_data = json.load(f)

    # Extract pet description and actions
    pet_description = {
        "name": pet_data["name"],
        "species": pet_data["species"],
        "personality": pet_data["personality"],
        "appearance": pet_data["appearance"],
        "special_ability": pet_data["special_ability"]
    }
    actions = pet_data["actions"]
    action_descriptions = pet_data.get("action_descriptions", {})

    print(f"✅ Test pet: {pet_description['name']} ({pet_description['species']})")
    print(f"✅ Test actions: {', '.join(actions)}")

    # Step 4: Generate sprite animations for each action
    print("\n🎬 Step 4: Generating sprite animations...")
    animation_paths = generate_sprite_animations_batch(pet_description, actions, action_descriptions)
    print(f"✅ Animations saved!")
    if type(animation_paths) is dict:
        for action, path in animation_paths.items():
            print(f"  - {action}: {path}")
    else:
        print(f" - Animations all in one: {animation_paths}")
    print("\n🎉 Animation generation test complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
