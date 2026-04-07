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

### pet_desrciption_generation.json
- **Purpose**: Generate a unique pet with personality and appearance using LLM
- **Variables**: None (creates pet from scratch)
- **Output**: JSON object with name, species, personality, appearance, special_ability

### action_desrciption_generation.json
- **Purpose**: Generate appropriate actions for a pet based on its characteristics
- **Variables**: `species`, `personality`, `special_ability`
- **Output**: JSON array of action names

### pet_appearance_generation.json
- **Purpose**: Generate the base pet character image
- **Variables**: `species`, `personality`, `appearance`
- **Output**: Image via image generation API

### sprite_animation_generation.json
- **Purpose**: Generate sprite sheet animations for pet actions (individual)
- **Variables**: `species`, `personality`, `appearance`, `special_ability`, `action`, `action_description`
- **Output**: Image (sprite sheet) via image generation API

### sprite_animation_generation_batch.json
- **Purpose**: Generate all sprite sheet animations in a single batch API call
- **Variables**: `species`, `personality`, `appearance`, `special_ability`, `actions_text`, `num_actions`
- **Output**: Image (combined sprite sheet) via image generation API

## Usage with PromptManager

```python
from prompt_manager import PromptManager

pm = PromptManager()

# Simple usage
prompt = pm.build_prompt("pet_desrciption_generation")

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

## Notes

All prompt templates follow a consistent naming convention:
- `pet_desrciption_generation.json` - Pet personality and description
- `action_desrciption_generation.json` - Action generation
- `pet_appearance_generation.json` - Visual appearance/image
- `sprite_animation_generation.json` - Individual animations
- `sprite_animation_generation_batch.json` - Batch animations
