import json
import base64
import requests
from io import BytesIO
from PIL import Image
from .. import config


class InlineDataWrapper:
    """Wrapper to mimic Gemini SDK's inline_data structure."""

    def __init__(self, inline_data_dict):
        self.mime_type = inline_data_dict.get("mimeType", "image/png")
        self._data = inline_data_dict.get("data", "")

    def as_image(self):
        """Decode base64 image data and return PIL Image."""
        image_bytes = base64.b64decode(self._data)
        return Image.open(BytesIO(image_bytes))


class PartWrapper:
    """Wrapper to mimic Gemini SDK's Part structure."""

    def __init__(self, part_dict):
        # Handle text field
        self.text = part_dict.get("text", None)

        # Handle inline data (check both camelCase and snake_case)
        inline_data_raw = part_dict.get("inlineData") or part_dict.get("inline_data")
        self.inline_data = InlineDataWrapper(inline_data_raw) if inline_data_raw else None

    def as_image(self):
        """Convenience method for getting image from inline_data."""
        if self.inline_data:
            return self.inline_data.as_image()
        return None


class ResponseWrapper:
    """Wrapper to mimic Gemini SDK's response structure."""

    def __init__(self, response_json):
        self.parts = []

        # Check if this is OpenAI format (choices) or Gemini format (candidates)
        if "choices" in response_json:
            self._parse_openai_format(response_json)
        elif "candidates" in response_json:
            self._parse_gemini_format(response_json)
        else:
            print(f"⚠️  Unknown API response format")
            print(f"   Expected 'choices' or 'candidates' but got: {list(response_json.keys())}")

    @property
    def text(self):
        """
        Extract text content from all parts and join them.
        Mimics Gemini SDK's response.text property.

        Returns:
            str: Combined text from all parts with text content
        """
        text_parts = []
        for part in self.parts:
            if part.text is not None:
                text_parts.append(part.text)

        return "".join(text_parts) if text_parts else ""

    def _parse_openai_format(self, response_json):
        """Parse OpenAI chat completion format."""
        if not response_json["choices"]:
            return

        choice = response_json["choices"][0]
        if "message" not in choice:
            return

        message = choice["message"]
        content = message.get("content")

        # If content is a list of parts (multimodal)
        if isinstance(content, list):
            for part in content:
                self.parts.append(PartWrapper(part))

        # If content is a string (text only)
        elif isinstance(content, str):
            self.parts.append(PartWrapper({"text": content}))

        # If content is None, check for images or data_urls fields
        elif content is None:
            # Check for images array (TokenRouter format for image generation)
            if "images" in message and message["images"]:
                for img_data in message["images"]:
                    # If it's a dict with url or data
                    if isinstance(img_data, dict):
                        # Check for image_url (nested dict)
                        if "image_url" in img_data:
                            image_url = img_data["image_url"]

                            if isinstance(image_url, dict) and "url" in image_url:
                                url = image_url["url"]
                                # If it's a data URL, extract base64
                                if url.startswith("data:"):
                                    parts = url.split(",", 1)
                                    if len(parts) == 2:
                                        self.parts.append(PartWrapper({
                                            "inlineData": {
                                                "mimeType": "image/png",
                                                "data": parts[1]
                                            }
                                        }))
                            elif isinstance(image_url, str):
                                # image_url is a string directly
                                if image_url.startswith("data:"):
                                    parts = image_url.split(",", 1)
                                    if len(parts) == 2:
                                        self.parts.append(PartWrapper({
                                            "inlineData": {
                                                "mimeType": "image/png",
                                                "data": parts[1]
                                            }
                                        }))

                        # Check for base64 data
                        elif "b64_json" in img_data:
                            self.parts.append(PartWrapper({
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": img_data["b64_json"]
                                }
                            }))
                        # Check for url field
                        elif "url" in img_data:
                            url = img_data["url"]
                            # If it's a data URL, extract base64
                            if url.startswith("data:"):
                                parts = url.split(",", 1)
                                if len(parts) == 2:
                                    self.parts.append(PartWrapper({
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": parts[1]
                                        }
                                    }))

                    # If it's a string (could be base64 or data URL)
                    elif isinstance(img_data, str):
                        if img_data.startswith("data:"):
                            # Data URL format
                            parts = img_data.split(",", 1)
                            if len(parts) == 2:
                                self.parts.append(PartWrapper({
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": parts[1]
                                    }
                                }))
                        else:
                            # Assume it's raw base64
                            self.parts.append(PartWrapper({
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": img_data
                                }
                            }))

            # Check for data_urls (some APIs put images here)
            elif "data_urls" in message:
                for url in message["data_urls"]:
                    # Extract base64 data from data URL
                    if url.startswith("data:"):
                        parts = url.split(",", 1)
                        if len(parts) == 2:
                            self.parts.append(PartWrapper({
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": parts[1]
                                }
                            }))

    def _parse_gemini_format(self, response_json):
        """Parse Gemini API format."""
        if not response_json["candidates"]:
            return

        candidate = response_json["candidates"][0]
        if "content" not in candidate:
            return

        content = candidate["content"]
        if "parts" not in content:
            return

        parts_list = content["parts"]
        for part_dict in parts_list:
            self.parts.append(PartWrapper(part_dict))


def call_tokenrouter_api(prompt, model):
    """
    Call the TokenRouter API with the given prompt and model.
    Returns a response object compatible with Gemini SDK format.

    Args:
        prompt (str): The input prompt to send to the API.
        model (str): The model to use for generation.

    Returns:
        ResponseWrapper: SDK-compatible response object with .parts attribute
    """
    if not config.TOKENROUTER_API_KEY:
        print("⚠️  TOKENROUTER_API_KEY not set. Skipping API call.")
        return None

    response = requests.post(
        url="https://api.tokenrouter.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {config.TOKENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        data=json.dumps({
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        })
    )

    # Check if request was successful
    if response.status_code != 200:
        print(f"⚠️  TokenRouter API error: {response.status_code}")
        print(f"   Response: {response.text}")
        return None

    # Parse JSON and wrap in SDK-compatible format
    response_json = response.json()
    return ResponseWrapper(response_json)