# DigitalPet MVP

An AI-powered digital pet generator that creates unique pets with personalities and animated sprites.

## Pipeline

1. **Pet Generation**: Use LLM to create pet personality and appearance description
2. **Image Creation**: Use Nanobanana API to generate the pet's image from description
3. **Action Generation**: Use LLM to generate actions based on personality (walk, jump, wave, etc.)
4. **Animation**: Use Nanobanana API to generate sprite animations for each action

## Tech Stack

- Python 3.12.0
- Gemini API 

## Project Structure
TBD

## Setup

1. **Clone and navigate to the project:**
   ```bash
   cd DigitalPet
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up API keys:**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

5. **Run the generator:**
   Run the whole pipeline
   ```bash
   python -m src.main 
   ```

   Run step 1-3 and step 4 separately (since step 4 is problematic)
   ```bash
   python tests/test_pet_desc_appr_action_desc.py
   python tests/test_animation_generation.py --pet pet_name
   ```

## API Keys Needed

- **Gemini API**: Get from https://aistudio.google.com/

## Current Status

- ✅ Pet personality generation (LLM)
- ✅ Action generation based on personality (LLM)
- ⚠️  Image generation (Nanobanana API integration needed)
- ⚠️  Sprite animation generation (Nanobanana API integration needed)

## Next Steps

1. Add actual Nanobanana API endpoints to `image_generator.py` and `animation_generator.py`
2. Test the complete pipeline
3. Add error handling and retry logic
4. Save pet data to JSON for future reference