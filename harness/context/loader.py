import json
from pathlib import Path
from typing import Any, Union

from .normalization import ContextNormalizer
from .schema import ContextBundle


def load_context(path: Union[str, Path]) -> ContextBundle:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ContextBundle.model_validate(data)


def validate_context(path: Union[str, Path]) -> ContextBundle:
    return load_context(path)


def save_context(bundle: ContextBundle, path: Union[str, Path], *, redact: bool = True) -> Path:
    """Save a context bundle as JSON. By default applies safety redaction."""
    normalizer = ContextNormalizer()
    if redact:
        return normalizer.save_bundle(bundle, path)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bundle.to_compiler_input(), indent=2, ensure_ascii=False), encoding="utf-8")
    return p
