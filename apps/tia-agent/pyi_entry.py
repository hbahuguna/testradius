"""Frozen-binary entry point (E6/R1).

PyInstaller executes the entry script as top-level ``__main__``, so the
package-relative ``from .interfaces.cli import main`` in
``tia_agent/__main__.py`` cannot be used. This absolute-import shim exists only
for the frozen build; ``python -m tia_agent`` keeps using ``__main__.py``.
"""

from tia_agent.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
