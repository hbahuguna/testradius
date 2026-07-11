"""Package entry point: `python -m sdet_agent` runs the CLI."""

from .interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
