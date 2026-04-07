import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    print("\n⚠️  TEST MODE: Running Steps 1-3 (pet generation, image, actions)")
    print("=" * 50)

    # Step 1 - Generate pet personality and appearance
    print("\n📝 Step 1: Generating pet personality and appearance...")
    pet_description = generate_pet_description()
    print(f"\n✨ Generated Pet:\n{json.dumps(pet_description, indent=2)}")

    # Step 2 - Generate pet image
    print("\n🎨 Step 2: Generating pet image...")
    pet_image_path = generate_pet_image(pet_description)
    print(f"✅ Pet image saved to: {pet_image_path}")

    # Step 3 - Generate actions based on personality
    print("\n🎭 Step 3: Generating pet actions...")
    actions = generate_pet_actions(pet_description)
    print(f"✅ Generated actions: {', '.join(actions)}")
    
    
if __name__ == "__main__":
    main()

    
