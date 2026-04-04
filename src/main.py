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

    # Step 1: Generate pet personality and appearance
    print("\n📝 Step 1: Generating pet personality and appearance...")
    pet_description = generate_pet_description()
    print(f"\n✨ Generated Pet:\n{json.dumps(pet_description, indent=2)}")

    # Step 2: Generate pet image
    print("\n🎨 Step 2: Generating pet image...")
    pet_image_path = generate_pet_image(pet_description)
    print(f"✅ Pet image saved to: {pet_image_path}")

    # Step 3: Generate actions based on personality
    print("\n🎭 Step 3: Generating pet actions...")
    actions = generate_pet_actions(pet_description)
    print(f"✅ Generated actions: {', '.join(actions)}")

    # Step 4: Generate sprite animations for each action
    print("\n🎬 Step 4: Generating sprite animations...")
    animation_paths = generate_sprite_animations(pet_description, actions)
    print(f"✅ Animations saved!")
    for action, path in animation_paths.items():
        print(f"  - {action}: {path}")

    print("\n🎉 Digital pet generation complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
