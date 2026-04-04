"""Generate pet actions based on personality using LLM."""
import json
from anthropic import Anthropic
from .. import config


def generate_pet_actions(pet_description):
    """
    Use LLM to generate appropriate actions for the pet based on personality.

    Args:
        pet_description (dict): Pet description with personality traits

    Returns:
        list: List of action names (e.g., ['walk', 'jump', 'wave'])
    """
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set in .env file")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    personality = pet_description.get("personality", [])
    species = pet_description.get("species", "creature")
    special_ability = pet_description.get("special_ability", "")

    prompt = f"""Given this digital pet:
Species: {species}
Personality: {', '.join(personality)}
Special Ability: {special_ability}

Generate 5-7 basic actions that fit this pet's personality. Actions should be:
- Simple animations (walk, jump, wave, dance, etc.)
- Appropriate for the personality
- Suitable for sprite animation

Return ONLY a JSON array of action names, like: ["walk", "jump", "wave", "idle", "celebrate"]"""

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=512,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    response_text = message.content[0].text

    # Parse JSON array from response
    try:
        # Find JSON array in response
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']') + 1
        if start_idx != -1 and end_idx > start_idx:
            actions = json.loads(response_text[start_idx:end_idx])
        else:
            # Fallback to default actions
            actions = ["idle", "walk", "jump", "wave", "celebrate"]
    except json.JSONDecodeError:
        # Fallback to default actions
        actions = ["idle", "walk", "jump", "wave", "celebrate"]

    return actions
