"""Test custom pet image generation with specific species, color, and personality."""
import sys
import argparse
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generators import generate_custom_pet_image


def main():
    """Generate a custom pet image from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate a custom pet image with specified characteristics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Blue bunny
  python test_custom_pet_image.py --species bunny --color blue --personality "playful, curious, gentle" --name blue_bunny

  # Green dragon
  python test_custom_pet_image.py --species "small dragon" --color "emerald green" --personality "mischievous, energetic" --name green_dragon

  # Purple fox
  python test_custom_pet_image.py --species fox --color purple --personality "wise, calm, mysterious" --name purple_fox
        """
    )

    parser.add_argument(
        "--species",
        type=str,
        required=True,
        help="Type of creature (e.g., 'bunny', 'dragon', 'fox')"
    )

    parser.add_argument(
        "--color",
        type=str,
        required=True,
        help="Overall color theme (e.g., 'blue', 'green', 'purple')"
    )

    parser.add_argument(
        "--personality",
        type=str,
        required=True,
        help="Personality traits (e.g., 'playful, curious, gentle')"
    )

    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="Output file name (without .png extension)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print(f"Generating Custom Pet: {args.name}")
    print("=" * 60)

    image_path = generate_custom_pet_image(
        species=args.species,
        color=args.color,
        personality=args.personality,
        output_name=args.name
    )

    if image_path:
        print("\n" + "=" * 60)
        print("✅ Generation Complete!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Generation Failed")
        print("=" * 60)


if __name__ == "__main__":
    main()
