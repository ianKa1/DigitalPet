import sys
import json
import argparse
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.generators import generate_pet_image
from src import config


def main():
    """Generate pet image from existing pet_info.json file."""
    parser = argparse.ArgumentParser(
        description="Generate pet appearance image from pet_info.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate image for a specific pet
  python run_appearance_gen.py --path output/pets/Mossling/pet_info.json

  # Using relative path
  python run_appearance_gen.py --path ../output/pets/Nimbusnout/pet_info.json
        """
    )

    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to pet_info.json file"
    )

    args = parser.parse_args()

    # Convert to Path object and verify file exists
    pet_info_path = Path(args.path)

    if not pet_info_path.exists():
        print(f"❌ File not found: {pet_info_path}")
        return 1

    if not pet_info_path.is_file():
        print(f"❌ Not a file: {pet_info_path}")
        return 1

    if pet_info_path.name != "pet_info.json":
        print(f"⚠️  Warning: File name is '{pet_info_path.name}', expected 'pet_info.json'")

    # Load pet data
    print("=" * 60)
    print(f"Loading pet data from: {pet_info_path}")
    print("=" * 60)

    try:
        with open(pet_info_path, 'r') as f:
            pet_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON file: {e}")
        return 1
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return 1

    # Display pet info
    print(f"\nPet: {pet_data.get('name', 'Unknown')}")
    print(f"Species: {pet_data.get('species', 'Unknown')}")
    print(f"Personality: {', '.join(pet_data.get('personality', []))}")
    print()

    # Generate pet image
    print("🎨 Step 2: Generating pet appearance image...")
    print()

    image_path = generate_pet_image(pet_data)

    if image_path:
        print()
        print("=" * 60)
        print("✅ Image Generation Complete!")
        print("=" * 60)
        print(f"Image saved to: {image_path}")

        # Verify the image is in the same directory as pet_info.json
        expected_dir = pet_info_path.parent
        actual_dir = Path(image_path).parent

        if expected_dir.resolve() == actual_dir.resolve():
            print(f"✓ Image saved in same directory as pet_info.json")
        else:
            print(f"⚠️  Image saved to different location:")
            print(f"   Expected: {expected_dir}")
            print(f"   Actual: {actual_dir}")

        return 0
    else:
        print()
        print("=" * 60)
        print("❌ Image Generation Failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
