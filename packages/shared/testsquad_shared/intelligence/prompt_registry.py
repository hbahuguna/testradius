import os
import yaml
from typing import Dict, Any, Optional
from jinja2 import Template

class PromptRegistry:
    """Manages LLM prompts stored as Markdown files with YAML front-matter."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptRegistry, cls).__new__(cls)
            cls._instance._prompts = {}
            # Base directory for prompts
            cls._instance._base_dir = os.path.join(
                os.path.dirname(__file__), 
                "prompts"
            )
        return cls._instance

    def get_prompt(self, name: str, **context) -> Dict[str, Any]:
        """
        Loads a prompt by name, renders it with Jinja2, and returns content + metadata.
        """
        if name not in self._prompts:
            self._load_prompt(name)
            
        raw_content, metadata = self._prompts[name]
        
        # Render with Jinja2
        template = Template(raw_content)
        rendered_content = template.render(**context)
        
        return {
            "content": rendered_content.strip(),
            "metadata": metadata
        }

    def _load_prompt(self, name: str):
        """Reads the markdown file and parses front-matter."""
        path = os.path.join(self._base_dir, f"{name}.md")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Prompt template not found: {path}")
            
        with open(path, "r") as f:
            content = f.read()
            
        # Parse YAML front-matter
        if content.startswith("---"):
            _, front_matter, body = content.split("---", 2)
            metadata = yaml.safe_load(front_matter)
            self._prompts[name] = (body.strip(), metadata)
        else:
            self._prompts[name] = (content.strip(), {})

prompt_registry = PromptRegistry()
