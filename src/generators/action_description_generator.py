"""Generate pet actions based on personality using LLM."""
import json
import os
from google import genai
from .. import config
from ..prompt_manager import PromptManager


def generate_pet_actions(pet_description):
    """
    Use LLM to generate appropriate actions for the pet based on personality.
    Updates the pet_info.json file with actions and action_descriptions.

    Args:
        pet_description (dict): Pet description with personality traits

    Returns:
        list: List of action names (e.g., ['walk', 'jump', 'wave'])
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping action generation.")
        return []

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    # Build prompt using PromptManager
    try:
        prompt = pm.build_prompt("action_desrciption_generation", {
            "species": pet_description.get("species", "creature"),
            "personality": ", ".join(pet_description.get("personality", [])),
            "special_ability": pet_description.get("special_ability", "")
        })
    except Exception as e:
        print(f"❌ Error building action prompt: {e}")
        return []

    print(f"🎭 Generating pet actions with Gemini...")
    print(f"   Pet: {pet_description.get('name', 'Unknown')} ({pet_description.get('species', 'Unknown')})")

    # Call Gemini API
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        # Parse JSON response
        json_text = response.text.strip()

        # Clean up markdown code blocks if present
        if json_text.startswith('```'):
            lines = json_text.split('\n')
            json_text = '\n'.join(lines[1:-1])

        action_data = json.loads(json_text)

        actions = action_data.get("actions", [])
        action_descriptions = action_data.get("action_descriptions", {})

        print(f"   ✅ Generated {len(actions)} actions: {', '.join(actions)}")

        # Load existing pet_info.json and update it
        pet_name = pet_description.get("name", "UnknownPet")
        pet_dir = os.path.join(config.PETS_DIR, pet_name)
        pet_info_path = os.path.join(pet_dir, "pet_info.json")

        if os.path.exists(pet_info_path):
            with open(pet_info_path, 'r') as f:
                pet_info = json.load(f)

            # Add actions and descriptions
            pet_info["actions"] = actions
            pet_info["action_descriptions"] = action_descriptions

            # Save updated pet_info.json
            with open(pet_info_path, 'w') as f:
                json.dump(pet_info, f, indent=2)

            print(f"   ✅ Updated: {pet_info_path}")
        else:
            print(f"   ⚠️  pet_info.json not found at: {pet_info_path}")

        return actions

    except json.JSONDecodeError as e:
        print(f"   ❌ Error parsing JSON response: {e}")
        return []
    except Exception as e:
        print(f"   ❌ Error generating actions: {e}")
        return []
