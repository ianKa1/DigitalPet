# Prompt Templates

This directory contains prompt templates for each generation step in the pipeline.

## Files

- **pet_generation.txt** - System prompt for generating pet personality and appearance using LLM
- **action_generation.txt** - System prompt for generating actions based on pet personality using LLM
- **image_generation.txt** - Prompt template for generating pet images using Nanobanana API
- **animation_generation.txt** - Prompt template for generating sprite animations using Nanobanana API

## Usage

These prompts are loaded by the generator modules at runtime. You can edit them to customize the generation behavior:

- Modify `pet_generation.txt` to change what attributes pets have
- Modify `action_generation.txt` to change the types of actions generated
- Modify `image_generation.txt` and `animation_generation.txt` to adjust the visual style

## Template Variables

Some prompts use placeholder variables that are filled in at runtime:
- `{species}` - The pet's species
- `{personality}` - The pet's personality traits
- `{special_ability}` - The pet's special ability
- `{appearance}` - The pet's appearance description
- `{action}` - The action being animated

These are replaced using Python's `.format()` method.
