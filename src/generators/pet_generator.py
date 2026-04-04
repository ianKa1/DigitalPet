"""Generate pet personality and appearance using LLM."""
import json
from anthropic import Anthropic
import config


def generate_pet_description():
    """
    Use LLM to generate a unique pet with personality and appearance.

    Returns:
        dict: Pet description with personality traits and appearance details
    """
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set in .env file")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = """Create a unique digital pet. Provide a JSON response with:
    - name: A cute, creative name
    - species: What kind of creature (can be fantasy/hybrid)
    - personality: 3-4 personality traits
    - appearance: Detailed visual description (colors, features, size, etc.)
    - special_ability: One unique ability based on personality

    Be creative and make it endearing!"""

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    # Parse the response
    response_text = message.content[0].text

    # Try to extract JSON from response
    try:
        # Find JSON in the response
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}') + 1
        if start_idx != -1 and end_idx > start_idx:
            pet_data = json.loads(response_text[start_idx:end_idx])
        else:
            # If no JSON found, create structured data from text
            pet_data = {
                "name": "Mystery Pet",
                "species": "Unknown",
                "personality": ["friendly", "curious", "playful"],
                "appearance": response_text,
                "special_ability": "Surprises you every day"
            }
    except json.JSONDecodeError:
        # Fallback if JSON parsing fails
        pet_data = {
            "name": "Mystery Pet",
            "species": "Unknown",
            "personality": ["friendly", "curious", "playful"],
            "appearance": response_text,
            "special_ability": "Surprises you every day"
        }

    return pet_data
