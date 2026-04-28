"""Generate pet images using Gemini Flash Image API."""
import os
from datetime import datetime
from google import genai
from .. import config
from ..prompt_manager import PromptManager
from ..utils.tokenrouter_helper import call_tokenrouter_api


def generate_pet_image(pet_description):
    """
    Generate an image of the pet using Gemini Flash Image API.

    Args:
        pet_description (dict): Pet description from LLM

    Returns:
        str: Path to saved image
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping image generation.")
        return None

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    # Build prompt using PromptManager
    try:
        prompt = pm.build_image_prompt(pet_description)
    except Exception as e:
        print(f"❌ Error building image prompt: {e}")
        return None

    print(f"📸 Generating pet image with Gemini Flash Image...")
    print(f"   Pet: {pet_description.get('name', 'Unknown')} ({pet_description.get('species', 'Unknown')})")

    # Call Gemini Flash Image API via TokenRouter
    try:
        # response = client.models.generate_content(
        #     model="gemini-3.1-flash-image-preview",
        #     contents=prompt
        # )
        response = call_tokenrouter_api(prompt, model="google/gemini-3.1-flash-image-preview")

        if response is None:
            return None

        # Process response and save image
        image_saved = False
        for part in response.parts:
            if part.text is not None:
                print(f"   📝 Response: {part.text[:100]}...")
            elif part.inline_data is not None:
                # Save the generated image
                image = part.as_image()

                # Get pet directory
                pet_name = pet_description.get("name", "UnknownPet")
                pet_dir = os.path.join(config.PETS_DIR, pet_name)
                os.makedirs(pet_dir, exist_ok=True)

                # Save as appearance.png
                filename = os.path.join(pet_dir, "appearance.png")
                image.save(filename)

                print(f"   ✅ Saved: {filename}")
                image_saved = True
                return filename

        if not image_saved:
            print(f"   ⚠️  No image generated")
            return None

    except Exception as e:
        print(f"   ❌ Error generating image: {e}")
        return None

# TODO: the quality is worse than the default pet image generation.
def generate_custom_pet_image(species, color, personality, output_name=None):
    """
    Generate a custom pet image with specified characteristics.

    Args:
        species (str): Type of creature (e.g., "bunny", "dragon", "fox")
        color (str): Overall color theme (e.g., "blue", "green", "purple")
        personality (str): Personality traits (e.g., "playful, curious")
        output_name (str, optional): Name for the output file. If None, uses species name.

    Returns:
        str: Path to saved image
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping image generation.")
        return None

    # Initialize Gemini client and PromptManager
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    # Build prompt using custom template
    try:
        prompt = pm.build_prompt("pet_appearance_custom", {
            "species": species,
            "color": color,
            "personality": personality
        })
    except Exception as e:
        print(f"❌ Error building custom image prompt: {e}")
        return None

    print(f"📸 Generating custom pet image...")
    print(f"   Species: {species}")
    print(f"   Color theme: {color}")
    print(f"   Personality: {personality}")

    # Call Gemini Flash Image API via TokenRouter
    try:
        # response = client.models.generate_content(
        #     model="gemini-3.1-flash-image-preview",
        #     contents=prompt
        # )
        response = call_tokenrouter_api(prompt, model="google/gemini-3.1-flash-image-preview")

        if response is None:
            return None

        # Process response and save image
        image_saved = False
        for part in response.parts:
            if part.text is not None:
                print(f"   📝 Response: {part.text[:100]}...")
            elif part.inline_data is not None:
                # Save the generated image
                image = part.as_image()

                # Create output directory
                output_dir = os.path.join(config.OUTPUT_DIR, "custom_pets")
                os.makedirs(output_dir, exist_ok=True)

                # Generate filename
                if output_name is None:
                    output_name = species.replace(" ", "_").lower()
                filename = os.path.join(output_dir, f"{output_name}.png")

                image.save(filename)

                print(f"   ✅ Saved: {filename}")
                image_saved = True
                return filename

        if not image_saved:
            print(f"   ⚠️  No image generated")
            return None

    except Exception as e:
        print(f"   ❌ Error generating custom image: {e}")
        return None
