"""Generate sprite animations using Gemini Flash Image API."""
import os
import json
from datetime import datetime
from google import genai
from PIL import Image
from .. import config
from ..prompt_manager import PromptManager
from ..utils.tokenrouter_helper import call_tokenrouter_api


def generate_sprite_animations(pet_description, actions, action_descriptions=None):
    """
    Generate sprite animations for each action using Gemini Flash Image API.

    Args:
        pet_description (dict): Pet description with species, personality, appearance, etc.
        actions (list): List of action names
        action_descriptions (dict, optional): Mapping of action names to descriptions

    Returns:
        dict: Mapping of action names to animation file paths
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping animation generation.")
        return {}
    
    if not config.TOKENROUTER_API_KEY:
        print("⚠️  TOKENROUTER_API_KEY not set. Skipping animation generation.")
        return {}

    # Initialize Gemini client and PromptManager
    # client = genai.Client(api_key=config.GEMINI_API_KEY)
    pm = PromptManager()

    animation_paths = {}
    name = pet_description.get("name", "pet")

    # Create pet-specific animation directory
    pet_animations_dir = os.path.join(config.PETS_DIR, name, "animations")
    os.makedirs(pet_animations_dir, exist_ok=True)

    # Load reference image if it exists
    reference_image = None
    reference_image_path = os.path.join(config.PETS_DIR, name, "appearance.png")
    if os.path.exists(reference_image_path):
        try:
            reference_image = Image.open(reference_image_path)
            print(f"  📸 Using reference image: {reference_image_path}")
        except Exception as e:
            print(f"  ⚠️  Could not load reference image: {e}")
            reference_image = None

    for action in actions:
        print(f"  Generating {action} animation...")

        # Get action description if available
        action_desc = None
        if action_descriptions and action in action_descriptions:
            action_desc = action_descriptions[action]

        # Build prompt using PromptManager
        try:
            prompt = pm.build_animation_prompt(
                pet_data=pet_description,
                action=action,
                action_description=action_desc
            )
        except Exception as e:
            print(f"    ❌ Error building prompt: {e}")
            animation_paths[action] = None
            continue

        print(f"    🎬 Generating sprite sheet with Gemini Flash Image...")

        try:
            # Prepare contents with prompt and optional reference image
            contents = []
            if reference_image:
                contents.append(reference_image)
                contents.append("Use this as a reference for the character's appearance:")
            contents.append(prompt)
            
            response = call_tokenrouter_api(contents, model="google/gemini-3.1-flash-image-preview")

            # Process response and save image
            image_saved = False
            for part in response.parts:
                if part.text is not None:
                    print(f"    📝 Response: {part.text[:100]}...")
                elif part.inline_data is not None:
                    # Save the generated sprite sheet
                    image = part.as_image()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(pet_animations_dir, f"{action}_{timestamp}.png")

                    image.save(filename)
                    animation_paths[action] = filename
                    image_saved = True
                    print(f"    ✅ Saved: {filename}")

            if not image_saved:
                print(f"    ⚠️  No image generated for {action}")
                animation_paths[action] = None

        except Exception as e:
            print(f"    ❌ Error generating {action}: {e}")
            animation_paths[action] = None

    return animation_paths


def _find_grid_lines(image, axis='horizontal', threshold=0.8):
    """
    Find grid lines by detecting rows/columns that are mostly black.

    Args:
        image (PIL.Image): Image to analyze
        axis (str): 'horizontal' or 'vertical'
        threshold (float): What percentage of pixels must be black (0.0-1.0)

    Returns:
        list: Coordinates where grid lines are detected
    """
    import numpy as np

    # Convert to grayscale numpy array
    gray = np.array(image.convert('L'))

    # Define "black" as pixels with value < 50
    BLACK_THRESHOLD = 50

    grid_lines = []

    if axis == 'horizontal':
        # Scan each row
        for y in range(gray.shape[0]):
            row = gray[y, :]
            black_ratio = np.sum(row < BLACK_THRESHOLD) / len(row)
            if black_ratio >= threshold:
                # Check if this is part of the previous line (thick border)
                if grid_lines and y - grid_lines[-1] <= 3:
                    continue  # Skip, part of same border
                grid_lines.append(y)
    else:  # vertical
        # Scan each column
        for x in range(gray.shape[1]):
            col = gray[:, x]
            black_ratio = np.sum(col < BLACK_THRESHOLD) / len(col)
            if black_ratio >= threshold:
                # Check if this is part of the previous line (thick border)
                if grid_lines and x - grid_lines[-1] <= 3:
                    continue  # Skip, part of same border
                grid_lines.append(x)

    return grid_lines


def _detect_grid_structure(image_path):
    """
    Detect grid structure by finding black border lines.

    Args:
        image_path (str): Path to sprite sheet image

    Returns:
        dict: {
            'frames_per_row': int,
            'num_rows': int,
            'frame_width': int,
            'frame_height': int,
            'total_frames': int,
            'vertical_lines': list,  # x-coordinates of vertical borders
            'horizontal_lines': list  # y-coordinates of horizontal borders
        }
    """
    img = Image.open(image_path)

    # Find grid lines
    horizontal_lines = _find_grid_lines(img, axis='horizontal', threshold=0.7)
    vertical_lines = _find_grid_lines(img, axis='vertical', threshold=0.7)

    if len(horizontal_lines) < 2 or len(vertical_lines) < 2:
        raise ValueError(f"Could not detect grid structure. Found {len(horizontal_lines)} horizontal and {len(vertical_lines)} vertical lines.")

    # Calculate grid dimensions
    num_rows = len(horizontal_lines) - 1
    num_columns = len(vertical_lines) - 1

    # Calculate frame dimensions (distance between grid lines)
    frame_heights = [horizontal_lines[i+1] - horizontal_lines[i] for i in range(num_rows)]
    frame_widths = [vertical_lines[i+1] - vertical_lines[i] for i in range(num_columns)]

    # Check for reasonable uniformity (allow small variations)
    # Use median size and warn if there's significant variation
    import statistics

    frame_height = int(statistics.median(frame_heights))
    frame_width = int(statistics.median(frame_widths))

    # Warn if variation is significant (>10% difference from median)
    max_height_diff = max(abs(h - frame_height) for h in frame_heights)
    max_width_diff = max(abs(w - frame_width) for w in frame_widths)

    if max_height_diff > frame_height * 0.1:
        print(f"⚠️  Warning: Row heights vary by up to {max_height_diff}px. Using median: {frame_height}px")
    if max_width_diff > frame_width * 0.1:
        print(f"⚠️  Warning: Column widths vary by up to {max_width_diff}px. Using median: {frame_width}px")
    total_frames = num_rows * num_columns

    return {
        'frames_per_row': num_columns,
        'num_rows': num_rows,
        'frame_width': frame_width,
        'frame_height': frame_height,
        'total_frames': total_frames,
        'vertical_lines': vertical_lines,
        'horizontal_lines': horizontal_lines
    }


def _detect_sprite_layout(image_path):
    """
    Auto-detect sprite sheet layout (frames per row, frame dimensions).

    This is the main entry point for layout detection. You can swap out
    the detection method by changing which function is called here.

    Args:
        image_path (str): Path to sprite sheet image

    Returns:
        dict: {
            'frames_per_row': int,
            'num_rows': int,
            'frame_width': int,
            'frame_height': int,
            'total_frames': int
        }
    """
    # Use grid-based detection (looks for black borders)
    return _detect_grid_structure(image_path)


def _is_empty_cell(image, left, top, right, bottom):
    """
    Check if a grid cell contains only background (white/transparent).

    Args:
        image (PIL.Image): The sprite sheet image
        left, top, right, bottom (int): Cell boundaries

    Returns:
        bool: True if cell is empty (>95% white/transparent)
    """
    import numpy as np

    cell = image.crop((left, top, right, bottom))
    cell_array = np.array(cell.convert('L'))

    # Define "background" as pixels with value > 240 (nearly white)
    WHITE_THRESHOLD = 240
    white_ratio = np.sum(cell_array > WHITE_THRESHOLD) / cell_array.size

    return white_ratio > 0.95


def _extract_animation_from_batch(
    batch_sprite_path,
    action_name,
    row_index,
    frames_per_action,
    output_dir,
    layout,
    duration=100
):
    """
    Extract a single animation from batch sprite sheet and create GIF.

    Args:
        batch_sprite_path (str): Path to batch sprite sheet
        action_name (str): Name of the action
        row_index (int): Which row this animation is in (0-indexed)
        frames_per_action (int): How many frames for this action
        output_dir (str): Where to save the GIF
        layout (dict): Layout info including grid lines
        duration (int): Frame duration in ms

    Returns:
        str: Path to created GIF
    """
    img = Image.open(batch_sprite_path)

    # Get grid line positions
    vertical_lines = layout.get('vertical_lines', [])
    horizontal_lines = layout.get('horizontal_lines', [])

    # Border width to exclude (the black lines themselves)
    BORDER_WIDTH = 2

    # Extract frames for this action
    frames = []
    for col_index in range(frames_per_action):
        if vertical_lines and horizontal_lines:
            # Use detected grid lines for precise extraction
            left = vertical_lines[col_index] + BORDER_WIDTH
            right = vertical_lines[col_index + 1] - BORDER_WIDTH
            top = horizontal_lines[row_index] + BORDER_WIDTH
            bottom = horizontal_lines[row_index + 1] - BORDER_WIDTH
        else:
            # Fallback to simple calculation if grid lines not available
            left = col_index * layout['frame_width']
            top = row_index * layout['frame_height']
            right = left + layout['frame_width']
            bottom = top + layout['frame_height']

        # Check if cell is empty
        if _is_empty_cell(img, left, top, right, bottom):
            break  # Stop when we hit empty cells

        frame = img.crop((left, top, right, bottom))
        frames.append(frame)

    # Save as GIF
    gif_path = os.path.join(output_dir, f"{action_name}.gif")

    if frames:
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            optimize=False
        )

    return gif_path


def _process_batch_sprite_sheet(
    batch_sprite_path,
    actions,
    action_descriptions,
    pet_dir,
    pet_name
):
    """
    Process batch sprite sheet: detect layout, extract GIFs, generate metadata.

    Args:
        batch_sprite_path (str): Path to batch sprite sheet
        actions (list): List of action names in order
        action_descriptions (dict): Action descriptions
        pet_dir (str): Pet directory path
        pet_name (str): Pet name

    Returns:
        dict: Sprite metadata
    """
    print(f"\n🔍 Analyzing batch sprite sheet...")

    # Detect layout
    layout = _detect_sprite_layout(batch_sprite_path)

    if not layout:
        raise ValueError("Could not detect sprite sheet layout")

    print(f"✅ Detected layout: {layout['frames_per_row']} frames/row, {layout['num_rows']} rows")
    print(f"   Frame size: {layout['frame_width']}x{layout['frame_height']}")

    # Calculate frames per action
    # Assume each action gets one row
    if layout['num_rows'] == len(actions):
        # One row per action
        frames_per_action = layout['frames_per_row']
        print(f"   {frames_per_action} frames per action")
    else:
        # Divide total frames by number of actions
        frames_per_action = layout['total_frames'] // len(actions)
        print(f"   Estimated {frames_per_action} frames per action")

    # Extract GIFs for each action
    animations_dir = os.path.join(pet_dir, "animations")
    sprite_metadata = {
        "pet_name": pet_name,
        "batch_sprite_sheet": batch_sprite_path,
        "layout": layout,
        "animations": {}
    }

    print(f"\n🎬 Extracting individual animations...")

    for i, action in enumerate(actions):
        print(f"  Extracting {action}...")

        try:
            gif_path = _extract_animation_from_batch(
                batch_sprite_path,
                action,
                row_index=i,
                frames_per_action=frames_per_action,
                output_dir=animations_dir,
                layout=layout,
                duration=150
            )

            sprite_metadata["animations"][action] = {
                "action_name": action,
                "action_description": action_descriptions.get(action, "") if action_descriptions else "",
                "gif_path": gif_path,
                "sprite_sheet_path": batch_sprite_path,
                "row_index": i,
                "frame_count": frames_per_action,
                "frame_width": layout['frame_width'],
                "frame_height": layout['frame_height']
            }

            print(f"    ✅ Saved: {gif_path}")

        except Exception as e:
            print(f"    ❌ Error extracting {action}: {e}")
            sprite_metadata["animations"][action] = {
                "action_name": action,
                "error": str(e)
            }

    # Save metadata
    metadata_path = os.path.join(pet_dir, "sprites_metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(sprite_metadata, f, indent=2)

    print(f"\n✅ Saved metadata: {metadata_path}")

    return sprite_metadata


def generate_sprite_animations_batch(pet_description, actions, action_descriptions=None):
    """
    Generate all sprite animations in a single API call for efficiency and consistency.
    Automatically processes the sprite sheet to extract individual GIFs and metadata.

    Args:
        pet_description (dict): Pet description with species, personality, appearance, etc.
        actions (list): List of action names
        action_descriptions (dict, optional): Mapping of action names to descriptions

    Returns:
        dict: Sprite metadata containing batch sprite sheet path, layout info, and individual animation data
    """
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set. Skipping animation generation.")
        return None
    
    if not config.TOKENROUTER_API_KEY:
        print("⚠️  TOKENROUTER_API_KEY not set. Skipping animation generation.")
        return None

    # Initialize Gemini client and PromptManager
    pm = PromptManager()

    name = pet_description.get("name", "pet")
    species = pet_description.get("species", "creature")
    personality = ", ".join(pet_description.get("personality", []))
    appearance = pet_description.get("appearance", "")
    special_ability = pet_description.get("special_ability", "")

    # Create pet-specific animation directory
    pet_animations_dir = os.path.join(config.PETS_DIR, name, "animations")
    os.makedirs(pet_animations_dir, exist_ok=True)

    # Load reference image if it exists
    reference_image = None
    reference_image_path = os.path.join(config.PETS_DIR, name, "appearance.png")
    if os.path.exists(reference_image_path):
        try:
            reference_image = Image.open(reference_image_path)
            print(f"  📸 Using reference image: {reference_image_path}")
        except Exception as e:
            print(f"  ⚠️  Could not load reference image: {e}")
            reference_image = None

    print(f"  Generating all {len(actions)} animations in one batch...")

    # Build action list with descriptions
    action_details = []
    for action in actions:
        if action_descriptions and action in action_descriptions:
            action_details.append(f"- {action}: {action_descriptions[action]}")
        else:
            action_details.append(f"- {action}")

    actions_text = "\n".join(action_details)

    # Build batch prompt using PromptManager
    try:
        prompt = pm.build_prompt("sprite_animation_generation_batch", {
            "species": species,
            "actions_text": actions_text,
            "appearance": appearance,
            "personality": personality,
            "special_ability": special_ability,
            "num_actions": len(actions)
        })
    except Exception as e:
        print(f"    ❌ Error building batch prompt: {e}")
        return None

    print(f"    🎬 Generating batch sprite sheet with Gemini Flash Image...")
    print(f"    📝 Batch prompt:\n{prompt}...")

    try:
        # Prepare contents with prompt and optional reference image
        contents = []
        if reference_image:
            contents.append(reference_image)
            contents.append("Use this as a reference for the character's appearance in all animations:")
        contents.append(prompt)

        # Call Gemini Flash Image API
        response = call_tokenrouter_api(contents, model="google/gemini-3.1-flash-image-preview")

        # Process response and save image
        for part in response.parts:
            if part.text is not None:
                print(f"    📝 Response: {part.text[:100]}...")
            elif part.inline_data is not None:
                # Save the complete sprite sheet
                image = part.as_image()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(pet_animations_dir, f"all_animations_{timestamp}.png")

                image.save(filename)
                print(f"    ✅ Saved complete sprite sheet: {filename}")

                # Process the sprite sheet to extract individual GIFs
                pet_dir = os.path.join(config.PETS_DIR, name)
                metadata = _process_batch_sprite_sheet(
                    filename,
                    actions,
                    action_descriptions,
                    pet_dir,
                    name
                )
                return metadata

        print(f"    ⚠️  No image generated")
        return None

    except Exception as e:
        print(f"    ❌ Error generating batch animations: {e}")
        return None
