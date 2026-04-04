# Prompt Templates

This directory contains structured prompt templates for each generation step in the pipeline.

## Template Format

All templates are now in JSON format with the following structure:

```json
{
  "system_prompt": "Instructions about the task and model role",
  "user_prompt_template": "The actual prompt with {variable} placeholders",
  "variables": ["list", "of", "expected", "variables"],
  "output_format": "json_object|json_array|text|image",
  "notes": "Additional documentation"
}
```

## Available Templates

### pet_generation.json
- **Purpose**: Generate a unique pet with personality and appearance using LLM
- **Variables**: None (creates pet from scratch)
- **Output**: JSON object with name, species, personality, appearance, special_ability

### action_generation.json
- **Purpose**: Generate appropriate actions for a pet based on its characteristics
- **Variables**: `species`, `personality`, `special_ability`
- **Output**: JSON array of action names

### image_generation.json
- **Purpose**: Generate the base pet character image
- **Variables**: `species`, `personality`, `appearance`
- **Output**: Image via image generation API

### animation_generation.json
- **Purpose**: Generate sprite sheet animations for pet actions
- **Variables**: `species`, `personality`, `appearance`, `special_ability`, `action`, `action_description`
- **Output**: Image (sprite sheet) via image generation API

## Usage with PromptManager

```python
from prompt_manager import PromptManager

pm = PromptManager()

# Simple usage
prompt = pm.build_prompt("pet_generation")

# With data substitution
prompt = pm.build_animation_prompt(
    pet_data={
        "species": "Cloud Bunny",
        "personality": ["playful", "curious"],
        "appearance": "A fluffy white bunny made of clouds...",
        "special_ability": "Can float on air currents"
    },
    action="hop",
    action_description="bouncy hopping movement"
)
```

## Backwards Compatibility

The PromptManager also supports old `.txt` format templates for backwards compatibility. If a `.json` template is not found, it will fall back to loading the `.txt` version.

## Customization

To customize prompts:
1. Edit the JSON files to change system prompts or user prompt templates
2. Add or remove variables as needed
3. The PromptManager will automatically reload templates (caching is per-session)

## Legacy Files

The old `.txt` format templates are kept for reference:
- `pet_generation.txt`
- `action_generation.txt`
- `image_generation.txt`
- `animation_generation.txt`

These can be safely removed once all generators are migrated to use PromptManager.
