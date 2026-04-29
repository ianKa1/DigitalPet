"""Generate pet actions based on personality using LLM."""
import json
import os
from google import genai
from .. import config
from ..prompt_manager import PromptManager
from ..utils.tokenrouter_helper import call_tokenrouter_api


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
        response = call_tokenrouter_api(prompt, model="google/gemini-3-flash-preview")

        if response is None:
            print(f"   ❌ API request failed")
            return []

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
    
    
def generate_single_action_description(pet_description, rough_action_name, rough_action_desc):
    """
    Generate a single optimized action based on user's rough description.
    Adds the action to the pet's existing actions in pet_info.json.

    Args:
        pet_description (dict): Pet description with personality traits
        rough_action_desc (str): User's rough idea for an action (e.g., "I want it to do something happy")

    Returns:
        str: The generated action name, or None if failed
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping action generation.")
        return None

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    # Build prompt using PromptManager
    try:
        prompt = pm.build_prompt("single_action_generation", {
            "species": pet_description.get("species", "creature"),
            "personality": ", ".join(pet_description.get("personality", [])),
            "special_ability": pet_description.get("special_ability", ""),
            "user_action_idea": rough_action_desc
        })
    except Exception as e:
        print(f"❌ Error building action prompt: {e}")
        return None

    print(f"🎭 Generating custom action for {pet_description.get('name', 'Unknown')}...")
    print(f"   User idea: \"{rough_action_desc}\"")

    # Call Gemini API
    try:
        response = call_tokenrouter_api(prompt, model="google/gemini-3-flash-preview")

        if response is None:
            print(f"   ❌ API request failed")
            return None

        # Parse JSON response
        json_text = response.text.strip()

        # Clean up markdown code blocks if present
        if json_text.startswith('```'):
            lines = json_text.split('\n')
            json_text = '\n'.join(lines[1:-1])

        action_data = json.loads(json_text)

        action_name = action_data.get("action")
        action_description = action_data.get("description")

        if not action_name or not action_description:
            print(f"   ❌ Invalid response: missing action or description")
            return None

        print(f"   ✅ Generated action: '{action_name}'")
        print(f"   Description: {action_description[:80]}...")

        # Load existing pet_info.json and update it
        pet_name = pet_description.get("name", "UnknownPet")
        pet_dir = os.path.join(config.PETS_DIR, pet_name)
        pet_info_path = os.path.join(pet_dir, "pet_info.json")

        if os.path.exists(pet_info_path):
            with open(pet_info_path, 'r') as f:
                pet_info = json.load(f)

            # Initialize actions and action_descriptions if they don't exist
            if "actions" not in pet_info:
                pet_info["actions"] = []
            if "action_descriptions" not in pet_info:
                pet_info["action_descriptions"] = {}

            # TODO: Use users' action name
            action_name = rough_action_name
            # Check if action already exists
            if action_name in pet_info["actions"]:
                print(f"   ⚠️  Action '{action_name}' already exists, updating description...")
            else:
                # Add new action to the list
                pet_info["actions"].append(action_name)

            # Add/update action description
            pet_info["action_descriptions"][action_name] = action_description

            # Save updated pet_info.json
            with open(pet_info_path, 'w') as f:
                json.dump(pet_info, f, indent=2)

            print(f"   ✅ Updated: {pet_info_path}")
            print(f"   Total actions: {len(pet_info['actions'])}")

        else:
            print(f"   ⚠️  pet_info.json not found at: {pet_info_path}")
            return None

        return action_name

    except json.JSONDecodeError as e:
        print(f"   ❌ Error parsing JSON response: {e}")
        print(f"   Response text: {json_text[:200]}...")
        return None
    except Exception as e:
        print(f"   ❌ Error generating action: {e}")
        return None
