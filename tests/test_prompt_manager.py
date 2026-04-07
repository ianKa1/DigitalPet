"""Test script demonstrating the PromptManager usage."""
import sys
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from prompt_manager import PromptManager


def main():
    """Test the PromptManager with different templates."""
    pm = PromptManager()

    print("=" * 70)
    print("PromptManager Test Script")
    print("=" * 70)

    # Test 1: Pet Generation (no variables needed)
    print("\n1. Pet Generation Prompt:")
    print("-" * 70)
    pet_prompt = pm.build_prompt("pet_generation")
    print(pet_prompt[:300] + "...")
    print(f"\nVariables: {pm.get_template_variables('pet_generation')}")

    # Test 2: Action Generation
    print("\n\n2. Action Generation Prompt:")
    print("-" * 70)
    pet_data = {
        "species": "Cloud Bunny",
        "personality": ["playful", "curious", "gentle"],
        "special_ability": "Can float on air currents and create rainbow trails"
    }
    action_prompt = pm.build_action_generation_prompt(pet_data)
    print(action_prompt[:300] + "...")
    print(f"\nVariables: {pm.get_template_variables('action_generation')}")

    # Test 3: Image Generation
    print("\n\n3. Image Generation Prompt:")
    print("-" * 70)
    pet_data_full = {
        "species": "Cloud Bunny",
        "personality": ["playful", "curious", "gentle", "bouncy"],
        "appearance": "A small fluffy creature that looks like a bunny made of soft white clouds. Has large sparkly blue eyes, tiny pink nose, and long floppy ears that seem to float."
    }
    image_prompt = pm.build_image_prompt(pet_data_full)
    print(image_prompt[:300] + "...")
    print(f"\nVariables: {pm.get_template_variables('image_generation')}")

    # Test 4: Animation Generation
    print("\n\n4. Animation Generation Prompt:")
    print("-" * 70)
    animation_prompt = pm.build_animation_prompt(
        pet_data=pet_data_full,
        action="hop",
        action_description="Bouncy hopping movement with ears flopping"
    )
    print(animation_prompt[:300] + "...")
    print(f"\nVariables: {pm.get_template_variables('animation_generation')}")

    # Test 5: Show full animation prompt
    print("\n\n5. Full Animation Prompt Example:")
    print("-" * 70)
    print(animation_prompt)

    print("\n" + "=" * 70)
    print("All tests completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
