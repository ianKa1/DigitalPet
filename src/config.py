"""Configuration for DigitalPet MVP."""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
# ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Output directories
OUTPUT_DIR = "output"
PETS_DIR = os.path.join(OUTPUT_DIR, "pets")

os.makedirs(PETS_DIR, exist_ok=True)
