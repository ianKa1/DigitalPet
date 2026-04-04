"""Configuration for DigitalPet MVP."""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NANOBANANA_API_KEY = os.getenv("NANOBANANA_API_KEY")

# Output directories
OUTPUT_DIR = "output"
PETS_DIR = os.path.join(OUTPUT_DIR, "pets")
ANIMATIONS_DIR = os.path.join(OUTPUT_DIR, "animations")

# Create directories if they don't exist
os.makedirs(PETS_DIR, exist_ok=True)
os.makedirs(ANIMATIONS_DIR, exist_ok=True)
