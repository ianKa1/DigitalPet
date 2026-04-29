"""
Generate default action patterns and animations for an existing pet.
This script loads the default action patterns and creates custom animations for each one.
"""
import sys
import json
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generators import generate_single_action_description, generate_sprite_animations
from src import config


def main():
    """Generate default action patterns and animations for Snow pet."""

    # Pet name
    pet_name = "Snow"

    print("=" * 60)
    print(f"Generating Default Action Patterns for: {pet_name}")
    print("=" * 60)

    # Load pet data
    pet_info_path = Path(config.PETS_DIR) / pet_name / "pet_info.json"

    if not pet_info_path.exists():
        print(f"❌ Pet not found: {pet_info_path}")
        print(f"   Make sure the '{pet_name}' pet exists first")
        return 1

    with open(pet_info_path, 'r') as f:
        pet_data = json.load(f)

    print(f"\n✓ Loaded pet: {pet_data.get('name')}")
    print(f"  Species: {pet_data.get('species')}")
    print(f"  Personality: {', '.join(pet_data.get('personality', []))}")

    # Load default action patterns
    default_patterns_path = Path("src/generators/default_action_pattern.json")

    if not default_patterns_path.exists():
        print(f"\n❌ Default patterns not found: {default_patterns_path}")
        return 1

    with open(default_patterns_path, 'r') as f:
        default_patterns = json.load(f)

    actions = default_patterns.get("actions", [])
    action_descriptions = default_patterns.get("action_descriptions", {})

    print(f"\n✓ Loaded {len(actions)} default action patterns")
    print(f"  Actions: {', '.join(actions)}")

    # Generate action descriptions for each default pattern
    print("\n" + "=" * 60)
    print("Step 1: Generating Action Descriptions")
    print("=" * 60)

    generated_actions = []

    for action_name in actions:
        action_desc = action_descriptions.get(action_name, "")

        print(f"\n{len(generated_actions) + 1}. Generating '{action_name}'...")

        result = generate_single_action_description(
            pet_description=pet_data,
            rough_action_name=action_name,
            rough_action_desc=action_desc
        )

        if result:
            generated_actions.append(action_name)
            print(f"   ✅ Action '{action_name}' added to pet")
        else:
            print(f"   ❌ Failed to generate '{action_name}'")

    print(f"\n✓ Successfully generated {len(generated_actions)}/{len(actions)} actions")

    # Reload pet data to get updated actions
    with open(pet_info_path, 'r') as f:
        updated_pet_data = json.load(f)

    # Generate sprite animations for each action
    print("\n" + "=" * 60)
    print("Step 2: Generating Sprite Animations")
    print("=" * 60)

    animation_results = {}
    MAX_RETRIES = 2  # Maximum retry attempts per action

    for i, action_name in enumerate(generated_actions, 1):
        print(f"\n{i}/{len(generated_actions)}: Generating animation for '{action_name}'...")

        # Try generating with retries
        animation_path = None
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                print(f"   🔄 Retry attempt {attempt}/{MAX_RETRIES}...")

            animations = generate_sprite_animations(
                pet_description=updated_pet_data,
                actions=[action_name],
                action_descriptions=updated_pet_data.get("action_descriptions", {})
            )

            if animations and action_name in animations:
                animation_path = animations[action_name]
                if animation_path:
                    animation_results[action_name] = animation_path
                    print(f"   ✅ Animation saved: {animation_path}")
                    break  # Success, exit retry loop
                else:
                    print(f"   ❌ Attempt {attempt} failed: No animation generated")
            else:
                print(f"   ❌ Attempt {attempt} failed: No response from API")

        # Final check after all retries
        if action_name not in animation_results:
            print(f"   ❌ Failed after {MAX_RETRIES} attempts")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nActions generated: {len(generated_actions)}/{len(actions)}")
    print(f"Animations created: {len(animation_results)}/{len(generated_actions)}")

    if animation_results:
        print(f"\n✓ Successfully created animations:")
        for action, path in animation_results.items():
            print(f"  • {action}: {path}")

    if len(animation_results) < len(generated_actions):
        failed = set(generated_actions) - set(animation_results.keys())
        print(f"\n⚠️  Failed to create animations for:")
        for action in failed:
            print(f"  • {action}")

    print("\n" + "=" * 60)
    print("✅ Complete!")
    print("=" * 60)

    return 0 if len(animation_results) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
