# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DigitalPet is an AI-powered digital pet generator that creates unique pets with personalities and animated sprites using Google's Gemini API. The pipeline consists of four main stages:

1. **Pet Generation**: Generate pet personality and appearance description using Gemini 2.5 Flash (text generation)
2. **Image Creation**: Generate pet image from description using Gemini 3.1 Flash Image
3. **Action Generation**: Generate personality-appropriate actions (walk, jump, wave, etc.)
4. **Animation**: Generate sprite animations for each action and extract individual GIFs

## Development Commands

### Setup
```bash
# Create virtual environment (requires Python 3.12.0)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# Note: requirements.txt includes anthropic and openai packages from initial setup,
# but current implementation only uses Gemini API

# Set up API keys
cp .env.example .env
# Edit .env and add GEMINI_API_KEY
```

### Running the Pipeline

**Full pipeline:**
```bash
python -m src.main
# Alternative: python run.py (convenience wrapper)
```

**Run stages 1-3 separately (recommended when debugging):**
```bash
# Steps 1-3: Pet description, image, and action generation
python tests/test_pet_desc_appr_action_desc.py

# Step 4: Animation generation for a specific pet
python tests/test_animation_generation.py --pet pet_name
```

**Testing individual components:**
Run Python test files directly in the `tests/` directory (note: test framework not set up, files are executable scripts).

## Architecture

### Core Generation Pipeline

The main pipeline (`src/main.py`) orchestrates four generator modules located in `src/generators/`:

1. **`pet_description_generator.py`**: Generates pet data (name, species, personality, appearance, special_ability) as JSON and saves to `output/pets/{pet_name}/pet_info.json`

2. **`pet_appearance_generator.py`**: Generates pet image from description and saves to `output/pets/{pet_name}/appearance.png`. This image is used as a reference for subsequent animation generation.

3. **`action_description_generator.py`**: Generates list of actions and detailed descriptions based on personality. Updates the existing `pet_info.json` with `actions` and `action_descriptions` fields.

4. **`sprite_animation_generator.py`**:
   - `generate_sprite_animations()`: Generates individual animations (one API call per action)
   - `generate_sprite_animations_batch()`: Generates all animations in a single batch (more efficient, recommended)

   The batch generator creates a sprite sheet with all animations, then automatically:
   - Detects grid structure by finding black border lines
   - Extracts individual GIF files for each action
   - Generates `sprites_metadata.json` with layout info and animation paths

### Prompt Management System

**`src/prompt_manager.py`**: Centralized prompt template system

- Loads JSON prompt templates from `src/prompts/` directory
- Templates contain `system_prompt`, `user_prompt_template`, and `variables`
- Provides specialized builder methods: `build_image_prompt()`, `build_animation_prompt()`, `build_action_generation_prompt()`
- All LLM calls should use PromptManager rather than hardcoded prompts

**Prompt template files in `src/prompts/`:**
- `pet_desrciption_generation.json` (note: typo in filename)
- `pet_appearance_generation.json`
- `pet_appearance_custom.json`
- `action_desrciption_generation.json` (note: typo in filename)
- `sprite_animation_generation.json`
- `sprite_animation_generation_batch.json`

### Sprite Sheet Processing

**Grid detection system** (in `sprite_animation_generator.py`):
- `_find_grid_lines()`: Detects black border lines by analyzing rows/columns
- `_detect_grid_structure()`: Returns frame dimensions, grid layout, and border coordinates
- `_is_empty_cell()`: Checks if a grid cell is empty (>95% white/transparent)
- `_extract_animation_from_batch()`: Extracts frames using detected grid lines, stops at empty cells, creates GIF
- `_process_batch_sprite_sheet()`: Main orchestrator that detects layout, extracts all GIFs, generates metadata

### Output Structure

```
output/
  pets/
    {PetName}/
      pet_info.json          # Pet data with actions and descriptions
      appearance.png         # Reference image
      animations/
        all_animations_*.png # Batch sprite sheet
        {action}.gif         # Individual animation GIFs
      sprites_metadata.json  # Layout and animation metadata
```

## Configuration

**`src/config.py`**: Configuration settings
- Loads environment variables from `.env`
- Requires `GEMINI_API_KEY`
- Sets output directories (`output/`, `output/pets/`)

## API Usage

**Gemini Models:**
- Text generation: `gemini-2.5-flash`
- Image generation: `gemini-3.1-flash-image-preview`

**Image generation pattern:**
```python
from google import genai
from PIL import Image

client = genai.Client(api_key=config.GEMINI_API_KEY)

# With reference image
reference_image = Image.open(path)
contents = [reference_image, "Reference description:", prompt]

response = client.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=contents
)

# Extract image from response
for part in response.parts:
    if part.inline_data is not None:
        image = part.as_image()
        image.save(filename)
```

## Known Issues

- Typos in prompt template filenames (`desrciption` instead of `description`)
- `sprite_utils.py` marked as "very ugly" and contains legacy sprite extraction code
- Animation generation (step 4) is noted as "problematic" in README
- No formal test framework - test files are executable scripts
