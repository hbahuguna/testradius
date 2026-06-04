import json
import re
from typing import Dict, Optional, Type, Any
from pydantic import BaseModel, ValidationError
import logging

logger = logging.getLogger(__name__)

class JSONSentinel:
    """Hardened JSON parser and Pydantic validator with repair logic."""

    @staticmethod
    def clean_json_string(raw_content: str) -> str:
        """Robustly extract the first valid JSON structure (array or object)."""
        content = raw_content.strip()
        
        # Remove common markdown clutter if it wraps the whole thing
        if content.startswith("```json"):
            content = content.replace("```json", "", 1)
        if content.startswith("```"):
            content = content.replace("```", "", 1)
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        # Find the first '[' or '{'
        start_idx = -1
        target_char = ''
        for i, char in enumerate(content):
            if char in ('[', '{'):
                start_idx = i
                target_char = ']' if char == '[' else '}'
                break
        
        if start_idx == -1:
            return content

        # Find the balanced closing character
        depth = 0
        for i in range(start_idx, len(content)):
            char = content[i]
            if char == ('[' if target_char == ']' else '{'):
                depth += 1
            elif char == target_char:
                depth -= 1
                if depth == 0:
                    return content[start_idx:i+1]
            
        # If not balanced, just return the content from start_idx
        return content[start_idx:].strip()

    @staticmethod
    def parse_and_validate(content: str, schema: Type[BaseModel]) -> Any:
        """Attempt to parse and validate against a Pydantic schema."""
        clean_content = JSONSentinel.clean_json_string(content)
        
        try:
            data = json.loads(clean_content)
            # Pydantic V2 compatibility
            if hasattr(schema, "model_validate"):
                return schema.model_validate(data)
            return schema.parse_obj(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"JSON Validation failed: {str(e)}. Content: {clean_content[:100]}...")
            raise e

    @staticmethod
    def repair_one_shot(content: str, error_msg: str) -> Optional[str]:
        """Placeholder for one-shot LLM repair loop logic (Sprint 3)."""
        # For now, we just return None to indicate automated repair is triggered elsewhere.
        return None
