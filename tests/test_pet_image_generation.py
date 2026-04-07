"""Test pet image generation using Gemini Flash Image API."""
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generators import generate_pet_image


def test_generate_mossling_image():
    """Load Mossling's pet info and generate its appearance image."""

    # Load Mossling's pet data
    pet_info_path = "output/pets/Mossling/pet_info.json"

    print(f"📂 Loading pet data from: {pet_info_path}")

    with open(pet_info_path, 'r') as f:
        pet_data = json.load(f)

    print(f"✅ Loaded pet: {pet_data['name']} ({pet_data['species']})")
    print(f"   Personality: {', '.join(pet_data['personality'])}")
    print(f"   Special ability: {pet_data['special_ability']}")
    print()

    # Generate pet image
    print("🎨 Generating pet appearance image...")
    print()

    image_path = generate_pet_image(pet_data)

    if image_path:
        print()
        print(f"🎉 Success! Image saved to: {image_path}")
    else:
        print()
        print("❌ Image generation failed")

    return image_path


if __name__ == "__main__":
    test_generate_mossling_image()
