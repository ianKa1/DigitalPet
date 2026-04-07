"""Prompt management system for loading and composing prompts."""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class PromptManager:
    """Manages prompt templates and composition."""

    def __init__(self, prompts_dir: str = "src/prompts"):
        """
        Initialize the PromptManager.

        Args:
            prompts_dir: Directory containing prompt template files
        """
        self.prompts_dir = Path(prompts_dir)
        self._templates_cache = {}

    def load_template(self, template_name: str) -> Dict[str, Any]:
        """
        Load a prompt template from file.

        Args:
            template_name: Name of the template (e.g., "pet_generation", "animation_generation")

        Returns:
            dict: Template data including system_prompt, user_prompt_template, etc.
        """
        # Check cache first
        if template_name in self._templates_cache:
            return self._templates_cache[template_name]

        # Try JSON format first
        json_path = self.prompts_dir / f"{template_name}.json"
        if json_path.exists():
            with open(json_path, 'r') as f:
                template = json.load(f)
                self._templates_cache[template_name] = template
                return template

        # Fallback to old .txt format
        txt_path = self.prompts_dir / f"{template_name}.txt"
        if txt_path.exists():
            with open(txt_path, 'r') as f:
                content = f.read()
                # Convert old format to new structure
                template = {
                    "system_prompt": "",
                    "user_prompt_template": content,
                    "variables": []
                }
                self._templates_cache[template_name] = template
                return template

        raise FileNotFoundError(f"Template '{template_name}' not found in {self.prompts_dir}")

    def build_prompt(
        self,
        template_name: str,
        data: Optional[Dict[str, Any]] = None,
        include_system: bool = True
    ) -> str:
        """
        Build a complete prompt from a template and data.

        Args:
            template_name: Name of the template to use
            data: Dictionary of variables to substitute into the template
            include_system: Whether to include the system prompt

        Returns:
            str: Complete formatted prompt
        """
        template = self.load_template(template_name)
        data = data or {}

        # Build the prompt parts
        parts = []

        # Add system prompt if requested and available
        if include_system and template.get("system_prompt"):
            parts.append(template["system_prompt"])

        # Format user prompt template with data
        user_prompt = template["user_prompt_template"]
        try:
            user_prompt = user_prompt.format(**data)
        except KeyError as e:
            raise ValueError(f"Missing required variable in template '{template_name}': {e}")

        parts.append(user_prompt)

        # Join with double newline
        return "\n\n".join(parts)

    def build_animation_prompt(
        self,
        pet_data: Dict[str, Any],
        action: str,
        action_description: Optional[str] = None
    ) -> str:
        """
        Build a prompt specifically for animation generation.

        Args:
            pet_data: Pet information (species, personality, appearance, etc.)
            action: Action name (e.g., "hop", "float")
            action_description: Optional detailed description of the action

        Returns:
            str: Complete animation generation prompt
        """
        # Prepare data for template
        data = {
            "species": pet_data.get("species", "creature"),
            "personality": ", ".join(pet_data.get("personality", [])),
            "appearance": pet_data.get("appearance", ""),
            "special_ability": pet_data.get("special_ability", ""),
            "action": action,
            "action_description": action_description or f"{action}ing"
        }

        return self.build_prompt("sprite_animation_generation", data)

    def build_image_prompt(
        self,
        pet_data: Dict[str, Any]
    ) -> str:
        """
        Build a prompt specifically for image generation.

        Args:
            pet_data: Pet information (species, personality, appearance, etc.)

        Returns:
            str: Complete image generation prompt
        """
        data = {
            "species": pet_data.get("species", "creature"),
            "appearance": pet_data.get("appearance", ""),
            "personality": ", ".join(pet_data.get("personality", []))
        }

        return self.build_prompt("pet_appearance_generation", data)

    def build_action_generation_prompt(
        self,
        pet_data: Dict[str, Any]
    ) -> str:
        """
        Build a prompt for generating pet actions.

        Args:
            pet_data: Pet information (species, personality, special_ability, etc.)

        Returns:
            str: Complete action generation prompt
        """
        data = {
            "species": pet_data.get("species", "creature"),
            "personality": ", ".join(pet_data.get("personality", [])),
            "special_ability": pet_data.get("special_ability", "")
        }

        return self.build_prompt("action_desrciption_generation", data)

    def get_template_variables(self, template_name: str) -> list:
        """
        Get the list of variables expected by a template.

        Args:
            template_name: Name of the template

        Returns:
            list: List of variable names
        """
        template = self.load_template(template_name)
        return template.get("variables", [])

    def clear_cache(self):
        """Clear the template cache."""
        self._templates_cache = {}


# Convenience function for quick access
def get_prompt_manager() -> PromptManager:
    """Get a PromptManager instance."""
    return PromptManager()
