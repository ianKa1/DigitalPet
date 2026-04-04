"""Generate sprite animations using Gemini Flash Image API."""
import os
from datetime import datetime
from google import genai
from PIL import Image
import config
from prompt_manager import PromptManager


def generate_sprite_animations(pet_description, actions, action_descriptions=None):
    """
    Generate sprite animations for each action using Gemini Flash Image API.

    Args:
        pet_description (dict): Pet description with species, personality, appearance, etc.
        actions (list): List of action names
        action_descriptions (dict, optional): Mapping of action names to descriptions

    Returns:
        dict: Mapping of action names to animation file paths
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping animation generation.")
        return {}

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    animation_paths = {}
    name = pet_description.get("name", "pet")

    # Create pet-specific animation directory
    pet_animations_dir = os.path.join(config.PETS_DIR, name, "animations")
    os.makedirs(pet_animations_dir, exist_ok=True)

    # Load reference image if it exists
    reference_image = None
    reference_image_path = os.path.join(config.PETS_DIR, name, "appearance.png")
    if os.path.exists(reference_image_path):
        try:
            reference_image = Image.open(reference_image_path)
            print(f"  📸 Using reference image: {reference_image_path}")
        except Exception as e:
            print(f"  ⚠️  Could not load reference image: {e}")
            reference_image = None

    for action in actions:
        print(f"  Generating {action} animation...")

        # Get action description if available
        action_desc = None
        if action_descriptions and action in action_descriptions:
            action_desc = action_descriptions[action]

        # Build prompt using PromptManager
        try:
            prompt = pm.build_animation_prompt(
                pet_data=pet_description,
                action=action,
                action_description=action_desc
            )
        except Exception as e:
            print(f"    ❌ Error building prompt: {e}")
            animation_paths[action] = None
            continue

        print(f"    🎬 Generating sprite sheet with Gemini Flash Image...")

        try:
            # Prepare contents with prompt and optional reference image
            contents = []
            if reference_image:
                contents.append(reference_image)
                contents.append("Use this as a reference for the character's appearance:")
            contents.append(prompt)

            # Call Gemini Flash Image API
            response = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=contents,
            )

            # Process response and save image
            image_saved = False
            for part in response.parts:
                if part.text is not None:
                    print(f"    📝 Response: {part.text[:100]}...")
                elif part.inline_data is not None:
                    # Save the generated sprite sheet
                    image = part.as_image()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(pet_animations_dir, f"{action}_{timestamp}.png")

                    image.save(filename)
                    animation_paths[action] = filename
                    image_saved = True
                    print(f"    ✅ Saved: {filename}")

            if not image_saved:
                print(f"    ⚠️  No image generated for {action}")
                animation_paths[action] = None

        except Exception as e:
            print(f"    ❌ Error generating {action}: {e}")
            animation_paths[action] = None

    return animation_paths


def generate_sprite_animations_batch(pet_description, actions, action_descriptions=None):
    """
    Generate all sprite animations in a single API call for efficiency and consistency.

    Args:
        pet_description (dict): Pet description with species, personality, appearance, etc.
        actions (list): List of action names
        action_descriptions (dict, optional): Mapping of action names to descriptions

    Returns:
        str: Path to the complete sprite sheet image containing all animations
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping animation generation.")
        return None

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    name = pet_description.get("name", "pet")
    species = pet_description.get("species", "creature")
    personality = ", ".join(pet_description.get("personality", []))
    appearance = pet_description.get("appearance", "")
    special_ability = pet_description.get("special_ability", "")

    # Create pet-specific animation directory
    pet_animations_dir = os.path.join(config.PETS_DIR, name, "animations")
    os.makedirs(pet_animations_dir, exist_ok=True)

    # Load reference image if it exists
    reference_image = None
    reference_image_path = os.path.join(config.PETS_DIR, name, "appearance.png")
    if os.path.exists(reference_image_path):
        try:
            reference_image = Image.open(reference_image_path)
            print(f"  📸 Using reference image: {reference_image_path}")
        except Exception as e:
            print(f"  ⚠️  Could not load reference image: {e}")
            reference_image = None

    print(f"  Generating all {len(actions)} animations in one batch...")

    # Build action list with descriptions
    action_details = []
    for action in actions:
        if action_descriptions and action in action_descriptions:
            action_details.append(f"- {action}: {action_descriptions[action]}")
        else:
            action_details.append(f"- {action}")

    actions_text = "\n".join(action_details)

    # Build batch prompt using PromptManager
    try:
        prompt = pm.build_prompt("animation_generation_batch", {
            "species": species,
            "actions_text": actions_text,
            "appearance": appearance,
            "personality": personality,
            "special_ability": special_ability,
            "num_actions": len(actions)
        })
    except Exception as e:
        print(f"    ❌ Error building batch prompt: {e}")
        return None

    print(f"    🎬 Generating batch sprite sheet with Gemini Flash Image...")
    print(f"    📝 Batch prompt:\n{prompt}...")

    try:
        # Prepare contents with prompt and optional reference image
        contents = []
        if reference_image:
            contents.append(reference_image)
            contents.append("Use this as a reference for the character's appearance in all animations:")
        contents.append(prompt)

        # Call Gemini Flash Image API
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=contents,
        )

        # Process response and save image
        for part in response.parts:
            if part.text is not None:
                print(f"    📝 Response: {part.text[:100]}...")
            elif part.inline_data is not None:
                # Save the complete sprite sheet
                image = part.as_image()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(pet_animations_dir, f"all_animations_{timestamp}.png")

                image.save(filename)
                print(f"    ✅ Saved complete sprite sheet: {filename}")
                return filename

        print(f"    ⚠️  No image generated")
        return None

    except Exception as e:
        print(f"    ❌ Error generating batch animations: {e}")
        return None
