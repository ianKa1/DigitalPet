"""Main script to generate a digital pet with personality and animations."""
import json
from src.generators import (
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
    print("\n⚠️  TEST MODE: Only running animation generation (Step 1)")
    print("=" * 50)

    # Step 1 - Generate pet personality and appearance
    print("\n📝 Step 1: Generating pet personality and appearance...")
    pet_description = generate_pet_description()
    print(f"\n✨ Generated Pet:\n{json.dumps(pet_description, indent=2)}")

    # Step 2 - Generate pet image
    print("\n🎨 Step 2: Generating pet image...")
    pet_image_path = generate_pet_image(pet_description)
    print(f"✅ Pet image saved to: {pet_image_path}")

    # BLOCKED: Step 3 - Generate actions based on personality
    # print("\n🎭 Step 3: Generating pet actions...")
    # actions = generate_pet_actions(pet_description)
    # print(f"✅ Generated actions: {', '.join(actions)}")

    # Load test data from example pet (Fluffball)
    # print("\n📋 Loading test data from Fluffball example pet...")
    # with open("output/pets/Fluffball/pet_info.json", "r") as f:
    #     pet_data = json.load(f)

    # # Extract pet description and actions
    # pet_description = {
    #     "name": pet_data["name"],
    #     "species": pet_data["species"],
    #     "personality": pet_data["personality"],
    #     "appearance": pet_data["appearance"],
    #     "special_ability": pet_data["special_ability"]
    # }
    # actions = pet_data["actions"]
    # action_descriptions = pet_data.get("action_descriptions", {})

    # print(f"✅ Test pet: {pet_description['name']} ({pet_description['species']})")
    # print(f"✅ Test actions: {', '.join(actions)}")

    # # Step 4: Generate sprite animations (includes sprite sheet processing)
    # print("\n🎬 Step 4: Generating sprite animations...")
    # sprite_metadata = generate_sprite_animations_batch(pet_description, actions, action_descriptions)

    # if sprite_metadata:
    #     print(f"✅ Animation generation complete!")
    #     print(f"   Batch sprite sheet: {sprite_metadata['batch_sprite_sheet']}")
    #     print(f"   Extracted {len(sprite_metadata['animations'])} individual GIFs:")
    #     for action in actions:
    #         if action in sprite_metadata['animations']:
    #             anim = sprite_metadata['animations'][action]
    #             if 'error' in anim:
    #                 print(f"     ❌ {action}: {anim['error']}")
    #             else:
    #                 print(f"     ✅ {action}: {anim['gif_path']}")
    # else:
    #     print("❌ Animation generation failed")

    print("\n🎉 Pipeline test complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
