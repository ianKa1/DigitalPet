# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DigitalPet is an AI-powered digital pet generator that creates unique pets with personalities and animated sprites through a 4-stage pipeline:

1. **Pet Generation**: LLM generates pet personality and appearance description
2. **Image Creation**: Generate pet's reference image from description
3. **Action Generation**: LLM generates actions based on personality (walk, jump, wave, etc.)
4. **Animation**: Generate sprite animations for each action using Gemini Flash Image API

## Running the Project

```bash
# Run the main pipeline
python run.py

# Or directly
python src/main.py
```

## Setup

```bash
# Activate conda environment
conda activate digital_pet

# Install dependencies (if needed)
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your keys:
# - ANTHROPIC_API_KEY or OPENAI_API_KEY (for LLM)
# - GEMINI_API_KEY (for sprite generation)
# - NANOBANANA_API_KEY (optional, legacy)
```

## Architecture

### Core Pipeline Flow

The pipeline is modular with each stage handled by a dedicated generator:

```
generators/
├── pet_generator.py       - Generate pet personality & appearance (Claude/OpenAI)
├── image_generator.py     - Generate reference image from description
├── action_generator.py    - Generate action list based on personality
└── animation_generator.py - Generate sprite animations (Gemini Flash Image)
```

### Key Systems

**Prompt Management System** (`prompt_manager.py`):
- Centralized prompt templating using JSON files in `src/prompts/`
- Each prompt template has: `system_prompt`, `user_prompt_template`, `variables`
- Use `PromptManager.build_prompt()` for any LLM interaction
- Specialized builders: `build_animation_prompt()`, `build_image_prompt()`, `build_action_generation_prompt()`

**Batch Animation Generation**:
- `generate_sprite_animations_batch()` generates all animations in one API call for consistency
- Creates a single sprite sheet with all actions in grid layout (one action per row)
- Automatically detects grid structure by finding black border lines
- Extracts individual GIFs from batch sprite sheet

**Sprite Sheet Processing** (`animation_generator.py`):
- Grid-based auto-detection: `_detect_grid_structure()` finds black border lines
- Handles non-uniform grids (uses median dimensions)
- Empty cell detection prevents extracting blank frames
- Configurable frame duration and looping

**Output Structure**:
```
output/pets/{pet_name}/
├── pet_info.json           # Complete pet data
├── appearance.png          # Reference image
├── animations/
│   ├── all_animations_{timestamp}.png  # Batch sprite sheet
│   ├── {action1}.gif
│   ├── {action2}.gif
│   └── ...
└── sprites_metadata.json   # Layout info, frame counts, paths
```

## Modifying Prompts

All prompts are in `src/prompts/` as JSON files. To modify generation behavior:

1. Edit the appropriate JSON file (e.g., `animation_generation_batch.json`)
2. Structure: `system_prompt` (optional), `user_prompt_template` (with {variables}), `variables` (list)
3. No code changes needed - PromptManager loads from files
4. See `src/prompts/TEMPLATE_FORMAT.md` for detailed format guide

## Testing

Test files are in `tests/` directory. Note: pytest is not currently installed.

```bash
# Install pytest first
pip install pytest

# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_sprite_processing.py
```

## Current Development Status

The codebase is in active development with the main pipeline functional:
- ✅ Pet personality generation (Claude/OpenAI)
- ✅ Action generation
- ✅ Batch animation generation (Gemini Flash Image)
- ✅ Sprite sheet auto-detection and GIF extraction
- 🚧 Grid detection improvements (feature/naive_move branch)

## Important Notes

- **Python Environment**: This project uses a conda environment named `digital_pet`. Always activate it before running: `conda activate digital_pet`
- **API Keys**: Project requires at minimum ANTHROPIC_API_KEY (or OPENAI_API_KEY) and GEMINI_API_KEY
- **Main Entry Point**: Use `run.py` from project root to properly set up Python path
- **Sprite Sheets**: Grid detection expects black borders between frames (threshold=0.7)
- **Reference Images**: If `appearance.png` exists, it's automatically included in animation prompts for consistency
- **Frame Duration**: Default is 150ms for batch animations, 100ms for sprite utils
