# Prompt Template Format Documentation

This document describes the structure and usage of prompt templates in the DigitalPet project.

## Table of Contents

1. [JSON Template Structure](#json-template-structure)
2. [Field Descriptions](#field-descriptions)
3. [Variable Substitution](#variable-substitution)
4. [Template Types](#template-types)
5. [Best Practices](#best-practices)
6. [Examples](#examples)

---

## JSON Template Structure

All prompt templates follow this JSON structure:

```json
{
  "system_prompt": "string",
  "user_prompt_template": "string with {variables}",
  "variables": ["array", "of", "variable", "names"],
  "output_format": "json_object|json_array|text|image",
  "notes": "optional documentation"
}
```

---

## Field Descriptions

### `system_prompt` (string, required)

**Purpose**: Provides context and instructions about the AI's role and task.

**Guidelines**:
- Describe what expert role the AI should take (e.g., "You are a creative character designer...")
- Explain the high-level goal or responsibility
- Keep it focused and clear
- Typically 1-3 sentences

**Example**:
```json
"system_prompt": "You are a creative character designer specializing in adorable digital pets. Create unique, memorable creatures with distinct personalities and visual appeal."
```

### `user_prompt_template` (string, required)

**Purpose**: The actual prompt sent to the AI, with placeholders for dynamic data.

**Guidelines**:
- Contains the specific instructions and requirements
- Uses `{variable_name}` syntax for placeholders
- Can include examples, constraints, technical specs
- Should be detailed enough to get consistent results

**Special note on JSON in templates**:
- If your template includes example JSON objects, use double braces `{{` and `}}` to escape them
- This prevents Python's `.format()` from treating them as variables

**Example**:
```json
"user_prompt_template": "Create a sprite animation for:\n\nSpecies: {species}\nPersonality: {personality}\n\nRequirements:\n- 4-6 frames\n- Pixel art style"
```

### `variables` (array of strings, required)

**Purpose**: Documents which variables are expected in the template.

**Guidelines**:
- List all `{variable}` placeholders used in `user_prompt_template`
- Order doesn't matter, but alphabetical is common
- Empty array `[]` if no variables needed
- Helps with validation and documentation

**Example**:
```json
"variables": ["species", "personality", "appearance", "action"]
```

### `output_format` (string, optional but recommended)

**Purpose**: Indicates what type of response to expect from the AI.

**Valid values**:
- `"json_object"` - Expects a JSON object like `{"key": "value"}`
- `"json_array"` - Expects a JSON array like `["item1", "item2"]`
- `"text"` - Expects plain text or descriptive response
- `"image"` - Used for image generation APIs

**Example**:
```json
"output_format": "json_array"
```

### `notes` (string, optional)

**Purpose**: Additional documentation, context, or warnings about the template.

**Guidelines**:
- Explain special use cases or considerations
- Document which API this template is designed for
- Add version notes or migration info if relevant

**Example**:
```json
"notes": "This prompt is used for generating sprite animations via image generation APIs like Gemini Flash Image."
```

---

## Variable Substitution

### How Variables Work

Variables in templates use Python's `.format()` method:

```python
template = "Species: {species}, Action: {action}"
data = {"species": "Cloud Bunny", "action": "hop"}
result = template.format(**data)
# Result: "Species: Cloud Bunny, Action: hop"
```

### Common Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `species` | string | Pet's species or creature type | `"Cloud Bunny"` |
| `personality` | string | Comma-separated personality traits | `"playful, curious, gentle"` |
| `appearance` | string | Detailed visual description | `"A fluffy white creature..."` |
| `special_ability` | string | Pet's unique ability | `"Can float on air currents"` |
| `action` | string | Action name | `"hop"` |
| `action_description` | string | Detailed action description | `"Bouncy hopping movement"` |

### Escaping Curly Braces

If you need literal `{` or `}` characters in your template (e.g., in example JSON), double them:

```json
"user_prompt_template": "Example: {{\n  \"name\": \"Example\"\n}}"
```

This renders as:
```
Example: {
  "name": "Example"
}
```

---

## Template Types

### 1. Pet Generation Template

**File**: `pet_generation.json`

**Purpose**: Generate a completely new pet from scratch.

**Variables**: None (creates everything procedurally)

**Output**: JSON object with pet data

**Structure**:
```json
{
  "system_prompt": "Role as creative character designer",
  "user_prompt_template": "Instructions to create unique pet with specific fields",
  "variables": [],
  "output_format": "json_object"
}
```

**Expected output format**:
```json
{
  "name": "string",
  "species": "string",
  "personality": ["array", "of", "traits"],
  "appearance": "detailed description",
  "special_ability": "unique ability"
}
```

---

### 2. Action Generation Template

**File**: `action_generation.json`

**Purpose**: Generate appropriate actions for a pet based on its characteristics.

**Variables**: `species`, `personality`, `special_ability`

**Output**: JSON array of action names

**Structure**:
```json
{
  "system_prompt": "Role as animation designer",
  "user_prompt_template": "Given pet data, generate 5-7 actions",
  "variables": ["species", "personality", "special_ability"],
  "output_format": "json_array"
}
```

**Expected output format**:
```json
["idle", "walk", "jump", "wave", "celebrate"]
```

---

### 3. Image Generation Template

**File**: `image_generation.json`

**Purpose**: Generate the base character image for a pet.

**Variables**: `species`, `personality`, `appearance`

**Output**: Image via API

**Structure**:
```json
{
  "system_prompt": "Role as 2D game character designer",
  "user_prompt_template": "Create character sprite with specifications",
  "variables": ["species", "personality", "appearance"],
  "output_format": "image"
}
```

**Usage**: Sent to image generation API (e.g., Gemini Flash Image, DALL-E, etc.)

---

### 4. Animation Generation Template

**File**: `animation_generation.json`

**Purpose**: Generate sprite sheet animations for specific actions.

**Variables**: `species`, `personality`, `appearance`, `special_ability`, `action`, `action_description`

**Output**: Image (sprite sheet) via API

**Structure**:
```json
{
  "system_prompt": "Role as sprite animation expert",
  "user_prompt_template": "Create sprite sheet with frame-by-frame details",
  "variables": ["species", "personality", "appearance", "special_ability", "action", "action_description"],
  "output_format": "image"
}
```

**Usage**: Most complex template, combines all pet data with specific action details.

---

## Best Practices

### 1. System Prompt Design

✅ **Do**:
- Clearly define the AI's role and expertise
- Keep it concise (1-3 sentences)
- Set the tone and context

❌ **Don't**:
- Make it overly long or complex
- Include specific instructions (those go in user_prompt_template)
- Repeat information from user_prompt_template

### 2. User Prompt Template Design

✅ **Do**:
- Be specific about requirements and constraints
- Include examples when helpful
- Structure with clear sections (headings, bullets)
- Specify output format explicitly

❌ **Don't**:
- Make it ambiguous or open-ended
- Assume the AI knows your project context
- Mix multiple unrelated concerns

### 3. Variable Design

✅ **Do**:
- Use descriptive variable names
- Document all variables in the `variables` array
- Use consistent naming across templates
- Handle missing data gracefully

❌ **Don't**:
- Use single-letter variables
- Create unnecessary variables
- Assume variables will always be present

### 4. Output Format Consistency

✅ **Do**:
- Explicitly state expected output format in the prompt
- Use the `output_format` field to document it
- Include examples of the expected output

❌ **Don't**:
- Assume the AI will guess the format
- Accept variable output structures

---

## Examples

### Example 1: Simple Template (No Variables)

```json
{
  "system_prompt": "You are a creative pet name generator.",
  "user_prompt_template": "Generate 5 cute, creative names for digital pets. Return as a JSON array of strings.",
  "variables": [],
  "output_format": "json_array",
  "notes": "Simple example with no input variables."
}
```

**Usage**:
```python
pm = PromptManager()
prompt = pm.build_prompt("pet_names")
# No data needed
```

---

### Example 2: Template with Variables

```json
{
  "system_prompt": "You are an expert at describing character animations.",
  "user_prompt_template": "Describe a {action} animation for a {species}:\n\nPersonality: {personality}\nAppearance: {appearance}\n\nProvide frame-by-frame description.",
  "variables": ["action", "species", "personality", "appearance"],
  "output_format": "text",
  "notes": "Generates detailed animation descriptions."
}
```

**Usage**:
```python
pm = PromptManager()
data = {
    "action": "jump",
    "species": "Cloud Bunny",
    "personality": "playful, bouncy",
    "appearance": "A fluffy white creature..."
}
prompt = pm.build_prompt("animation_description", data)
```

---

### Example 3: Template with Escaped JSON

```json
{
  "system_prompt": "You are a data formatter.",
  "user_prompt_template": "Format the following data:\n\nName: {name}\nAge: {age}\n\nReturn as JSON:\n{{\n  \"name\": \"value\",\n  \"age\": number\n}}",
  "variables": ["name", "age"],
  "output_format": "json_object",
  "notes": "Note the double braces {{ }} to escape the example JSON."
}
```

**Result**: The example JSON `{ "name": "value", "age": number }` appears literally in the prompt.

---

## Creating New Templates

### Step 1: Define Purpose

What should this template accomplish? Who is the audience (LLM vs. Image API)?

### Step 2: Identify Variables

What dynamic data needs to be inserted? List all `{variable}` placeholders.

### Step 3: Write System Prompt

Establish the AI's role and expertise in 1-3 sentences.

### Step 4: Write User Prompt Template

Create detailed instructions with:
- Clear requirements
- Expected format/structure
- Examples (if helpful)
- Constraints or limitations

### Step 5: Document

Fill in `variables`, `output_format`, and `notes` fields.

### Step 6: Test

Use PromptManager to load and test with sample data:

```python
pm = PromptManager()
prompt = pm.build_prompt("your_template", {"var": "value"})
print(prompt)
```

---

## Migration from .txt to .json

If you have old `.txt` templates:

1. **Create JSON file** with same base name
2. **Split content** into `system_prompt` (if any) and `user_prompt_template`
3. **Identify variables** by finding all `{variable}` patterns
4. **Add metadata** (`variables`, `output_format`, `notes`)
5. **Escape JSON** if template contains example JSON objects
6. **Test** with PromptManager

**Note**: PromptManager supports both formats (falls back to `.txt` if `.json` not found).

---

## Troubleshooting

### Error: "Missing required variable"

**Cause**: Template expects a variable that wasn't provided in data dict.

**Solution**: Check the `variables` array and ensure all are in your data dict.

```python
# Error
pm.build_prompt("animation", {"species": "Bunny"})
# Missing: personality, appearance, etc.

# Fixed
pm.build_prompt("animation", {
    "species": "Bunny",
    "personality": "playful",
    "appearance": "fluffy",
    ...
})
```

### Error: KeyError with JSON characters

**Cause**: Unescaped `{` or `}` in template treated as variable placeholder.

**Solution**: Double all literal braces: `{` → `{{`, `}` → `}}`

### Template not loading

**Cause**: Wrong filename or directory.

**Solution**:
- Ensure file is in `src/prompts/`
- Check filename matches (no typos)
- Include correct extension (`.json` or `.txt`)

---

## Summary

**Key Points**:
- Templates are JSON files with `system_prompt`, `user_prompt_template`, `variables`, `output_format`, and `notes`
- Variables use `{variable_name}` syntax
- Escape literal braces with `{{` and `}}`
- System prompt = role/context, User prompt = specific instructions
- Document all variables and expected output format

**Quick Reference**:
```json
{
  "system_prompt": "AI's role (1-3 sentences)",
  "user_prompt_template": "Detailed instructions with {variables}",
  "variables": ["list", "of", "variables"],
  "output_format": "json_object|json_array|text|image",
  "notes": "Additional context"
}
```

For more examples, see the existing templates in this directory.
