"""Generate pet personality and appearance using LLM."""
import json
import os
from datetime import datetime
from google import genai
from .. import config
from ..prompt_manager import PromptManager


def generate_pet_description():
    """
    Use LLM to generate a unique pet with personality and appearance.

    Returns:
        dict: Pet description with personality traits and appearance details
    """
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env file")

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    # Build prompt using PromptManager
    try:
        prompt = pm.build_prompt("pet_desrciption_generation")
    except Exception as e:
        raise ValueError(f"Error loading prompt template: {e}")
    
    print("🔍 Generated prompt for pet description:")
    print(prompt)

    # Call Gemini API
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        response_text = response.text
    except Exception as e:
        raise ValueError(f"Error calling Gemini API: {e}")

    # Parse the response
    # Try to extract JSON from response
    try:
        # Clean JSON (remove markdown code blocks if present)
        json_text = response_text.strip()
        if json_text.startswith('```'):
            lines = json_text.split('\n')
            # Remove first line (```json) and last line (```)
            json_text = '\n'.join(lines[1:-1])

        # Find JSON in the response
        start_idx = json_text.find('{')
        end_idx = json_text.rfind('}') + 1
        if start_idx != -1 and end_idx > start_idx:
            pet_data = json.loads(json_text[start_idx:end_idx])
        else:
            # If no JSON found, create structured data from text
            pet_data = {
                "name": "Mystery Pet",
                "species": "Unknown",
                "personality": ["friendly", "curious", "playful"],
                "appearance": response_text,
                "special_ability": "Surprises you every day"
            }
    except json.JSONDecodeError as e:
        # Fallback if JSON parsing fails
        print(f"Warning: JSON parsing failed: {e}")
        print(f"Response text: {response_text[:200]}...")
        pet_data = {
            "name": "Mystery Pet",
            "species": "Unknown",
            "personality": ["friendly", "curious", "playful"],
            "appearance": response_text,
            "special_ability": "Surprises you every day"
        }

    # Add metadata
    pet_data["created_at"] = datetime.now().isoformat() + "Z"
    pet_data["generation_metadata"] = {
        "llm_model": "gemini-2.5-flash",
        "image_generated": False,
        "animations_generated": []
    }

    # Create pet directory and save data
    # TODO: when to save the pet data?
    pet_name = pet_data.get("name", "UnknownPet")
    pet_dir = os.path.join(config.PETS_DIR, pet_name)
    os.makedirs(pet_dir, exist_ok=True)

    # Save pet info to JSON file
    pet_info_path = os.path.join(pet_dir, "pet_info.json")
    with open(pet_info_path, 'w') as f:
        json.dump(pet_data, f, indent=2)

    print(f"✅ Pet data saved to: {pet_info_path}")

    return pet_data
