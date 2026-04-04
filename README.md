# DigitalPet MVP

An AI-powered digital pet generator that creates unique pets with personalities and animated sprites.

## Pipeline

1. **Pet Generation**: Use LLM to create pet personality and appearance description
2. **Image Creation**: Use Nanobanana API to generate the pet's image from description
3. **Action Generation**: Use LLM to generate actions based on personality (walk, jump, wave, etc.)
4. **Animation**: Use Nanobanana API to generate sprite animations for each action

## Tech Stack

- Python 3.8+
- Anthropic Claude API (for pet and action generation)
- Nanobanana API (for image and animation generation)

## Project Structure

```
DigitalPet/
├── main.py                  # Main pipeline script
├── config.py                # Configuration and environment setup
├── pet_generator.py         # Step 1: Generate pet personality
├── image_generator.py       # Step 2: Generate pet image
├── action_generator.py      # Step 3: Generate pet actions
├── animation_generator.py   # Step 4: Generate sprite animations
├── requirements.txt         # Python dependencies
├── .env                     # API keys (create from .env.example)
└── output/                  # Generated content
    ├── pets/                # Pet images
    └── animations/          # Sprite animations
```

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
   ```bash
   python main.py
   ```

## API Keys Needed

- **Anthropic API**: Get from https://console.anthropic.com/
- **Nanobanana API**: Add your Nanobanana API key (update image/animation generators with actual API endpoints)

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