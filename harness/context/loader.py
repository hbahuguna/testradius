import json
from pathlib import Path
from .schema import ContextBundle


def load_context(path: str) -> ContextBundle:
    data = json.loads(Path(path).read_text())
    return ContextBundle.model_validate(data)


def validate_context(path: str) -> ContextBundle:
    return load_context(path)
